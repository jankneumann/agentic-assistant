"""A2A task lifecycle over ``SdkHarnessAdapter.astream_invoke``.

Two pieces live here:

``SessionRegistry`` — the first consumer of the harness-adapter spec's
SESSION REGISTRY requirement (added by capability-protocols-v2):
create / lookup / expire sessions keyed by ``thread_id`` so serving
surfaces can multiplex concurrent tasks instead of binding one global
harness at startup. This implementation is in-memory; expiry releases
in-process resources only. The durable Postgres checkpointer (which
would make expired thread_ids re-creatable with history) remains
deferred to the harness-adapter Durable Session Persistence work — an
expired/unknown ``contextId`` is therefore rejected rather than
resumed.

``A2ATaskHandler`` — task lifecycle (submitted → working →
completed/failed, with the input-required approval bridge handled by
the transports/a2a mapper): resolves the session from the incoming
message's ``contextId`` (A2A contextId ≡ session ``thread_id``), runs
the harness stream through ``map_harness_to_a2a``, and maintains an
in-memory task store so ``message/send`` can return the terminal Task
snapshot.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from assistant.a2a.types import (
    CONTENT_TYPE_NOT_SUPPORTED,
    INVALID_PARAMS,
    TASK_NOT_FOUND,
    UNSUPPORTED_OPERATION,
    A2AProtocolError,
    A2AStreamEvent,
    Message,
    MessageSendParams,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from assistant.transports.a2a.mapper import map_harness_to_a2a

logger = logging.getLogger(__name__)

# Builds a fresh (harness, agent) pair per session — the same
# persona/role/harness pipeline the web lifespan runs, packaged as an
# injectable factory so tests can supply fakes.
SessionFactory = Callable[[], Awaitable[tuple[Any, Any]]]

DEFAULT_IDLE_TTL_SECONDS = 3600.0


@dataclass
class Session:
    """One live conversation: a harness instance plus its agent."""

    thread_id: str
    harness: Any
    agent: Any
    created_at: float
    last_used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionRegistry:
    """In-memory create/lookup/expire session registry keyed by thread_id.

    Semantics per the harness-adapter Session Registry requirement:
    ``create`` builds a new session (fresh harness + agent via the
    injected factory) and keys it by the harness's own ``thread_id``;
    ``lookup`` returns the live session or ``None`` (never silently
    creates); ``expire`` releases in-process resources by thread_id, and
    an idle-TTL sweep (run opportunistically on create/lookup) expires
    sessions unused for ``idle_ttl_seconds``. Durably checkpointed state
    is NOT deleted by expiry — but re-creating a session bound to the
    same thread_id requires the deferred Postgres checkpointer, so v1
    treats expired ids as unknown.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory = session_factory
        self._idle_ttl = idle_ttl_seconds
        self._clock = clock
        self._sessions: dict[str, Session] = {}

    def __len__(self) -> int:
        return len(self._sessions)

    async def create(self) -> Session:
        """Build a new session and register it under its thread_id."""
        self.expire_idle()
        harness, agent = await self._factory()
        thread_id = str(harness.thread_id)
        if not thread_id:
            raise ValueError("session factory produced an empty thread_id")
        if thread_id in self._sessions:
            raise ValueError(
                f"duplicate thread_id '{thread_id}' from session factory"
            )
        now = self._clock()
        session = Session(
            thread_id=thread_id,
            harness=harness,
            agent=agent,
            created_at=now,
            last_used=now,
        )
        self._sessions[thread_id] = session
        return session

    def lookup(self, thread_id: str) -> Session | None:
        """Return the live session for ``thread_id`` or ``None``.

        Unknown ids are signaled distinctly (``None``) — the registry
        never silently creates. A successful lookup refreshes the
        session's idle clock.
        """
        self.expire_idle()
        session = self._sessions.get(thread_id)
        if session is not None:
            session.last_used = self._clock()
        return session

    def expire(self, thread_id: str) -> bool:
        """Release the in-process session; True if one was registered."""
        return self._sessions.pop(thread_id, None) is not None

    def expire_idle(self) -> list[str]:
        """Expire sessions idle longer than the TTL; returns expired ids."""
        now = self._clock()
        expired = [
            tid
            for tid, s in self._sessions.items()
            if now - s.last_used > self._idle_ttl
        ]
        for tid in expired:
            del self._sessions[tid]
            logger.info("A2A session '%s' expired after idle TTL", tid)
        return expired


def _now_ts() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).isoformat()


class A2ATaskHandler:
    """message/send + message/stream over the session registry."""

    def __init__(self, registry: SessionRegistry) -> None:
        self._registry = registry
        self._tasks: dict[str, Task] = {}

    # -- task store ---------------------------------------------------

    def get_task(self, task_id: str) -> Task | None:
        """Return a snapshot of a known task (internal store; a
        ``tasks/get`` JSON-RPC method is deferred — see design.md)."""
        task = self._tasks.get(task_id)
        return task.model_copy(deep=True) if task is not None else None

    def _apply_event(self, task: Task, event: A2AStreamEvent) -> None:
        if isinstance(event, TaskStatusUpdateEvent):
            task.status = event.status
        elif isinstance(event, TaskArtifactUpdateEvent):
            artifacts = task.artifacts if task.artifacts is not None else []
            existing = next(
                (
                    a
                    for a in artifacts
                    if a.artifact_id == event.artifact.artifact_id
                ),
                None,
            )
            if existing is None or not event.append:
                if existing is not None:
                    artifacts.remove(existing)
                artifacts.append(event.artifact.model_copy(deep=True))
            else:
                existing.parts.extend(event.artifact.parts)
            task.artifacts = artifacts

    # -- request validation / session resolution ----------------------

    @staticmethod
    def _extract_text(message: Message) -> str:
        if not message.parts:
            raise A2AProtocolError(
                INVALID_PARAMS, "message.parts must not be empty"
            )
        texts = [p.text for p in message.parts if isinstance(p, TextPart)]
        if not texts:
            raise A2AProtocolError(
                CONTENT_TYPE_NOT_SUPPORTED,
                "only text parts are supported (v1 text-only surface)",
            )
        return "\n".join(texts)

    async def _resolve_session(self, message: Message) -> Session:
        if message.task_id is not None:
            # Multi-turn continuation of an existing task (the A2A
            # input-required round-trip) needs the approval
            # interrupt/resume flow — deferred (design.md).
            if message.task_id in self._tasks:
                raise A2AProtocolError(
                    UNSUPPORTED_OPERATION,
                    "continuing an existing task is not supported yet "
                    "(approval interrupt/resume is deferred)",
                )
            raise A2AProtocolError(
                TASK_NOT_FOUND, f"unknown task '{message.task_id}'"
            )
        if message.context_id is not None:
            session = self._registry.lookup(message.context_id)
            if session is None:
                raise A2AProtocolError(
                    INVALID_PARAMS,
                    f"unknown contextId '{message.context_id}' "
                    "(sessions are in-memory; expired or never created)",
                )
            return session
        return await self._registry.create()

    # -- handlers ------------------------------------------------------

    async def handle_message_stream(
        self, params: MessageSendParams
    ) -> AsyncGenerator[A2AStreamEvent, None]:
        """Yield the initial Task snapshot, then mapped harness events.

        Terminal guarantee: the last yielded event is always a
        status-update with ``final=True`` — a misbehaving harness (raw
        raise without the Phase-1 terminal ``RunFinished``) results in a
        synthesized ``failed`` update with class-name-only redaction.
        """
        text = self._extract_text(params.message)
        session = await self._resolve_session(params.message)

        task_id = str(uuid.uuid4())
        context_id = session.thread_id
        incoming = params.message.model_copy(
            update={"task_id": task_id, "context_id": context_id}
        )
        task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.SUBMITTED, timestamp=_now_ts()),
            history=[incoming],
        )
        self._tasks[task_id] = task
        yield task.model_copy(deep=True)

        async with session.lock:
            stream = session.harness.astream_invoke(session.agent, text)
            async with aclosing(stream) as hs:
                try:
                    async for event in map_harness_to_a2a(
                        hs, task_id=task_id, context_id=context_id
                    ):
                        self._apply_event(task, event)
                        yield event
                except Exception as exc:
                    # The mapper only propagates when the harness raised
                    # WITHOUT the Phase-1 terminal event. Synthesize the
                    # final failed update so every stream ends with
                    # final=True (class-name only per the D8 redaction
                    # rule).
                    cls_name = type(exc).__name__
                    failed = TaskStatusUpdateEvent(
                        task_id=task_id,
                        context_id=context_id,
                        status=TaskStatus(
                            state=TaskState.FAILED,
                            message=Message(
                                role="agent",
                                parts=[TextPart(text=cls_name)],
                                message_id=f"{task_id}-failure",
                                task_id=task_id,
                                context_id=context_id,
                            ),
                            timestamp=_now_ts(),
                        ),
                        final=True,
                    )
                    self._apply_event(task, failed)
                    yield failed

    async def handle_message_send(self, params: MessageSendParams) -> Task:
        """Blocking variant: drain the stream, return the terminal Task."""
        task_id: str | None = None
        async with aclosing(self.handle_message_stream(params)) as events:
            async for event in events:
                if isinstance(event, Task):
                    task_id = event.id
        assert task_id is not None  # first yielded event is always the Task
        final = self.get_task(task_id)
        assert final is not None
        return final


def apply_artifact_text(task: Task) -> str:
    """Concatenate all text parts across a task's artifacts (test helper)."""
    if not task.artifacts:
        return ""
    return "".join(
        part.text
        for artifact in task.artifacts
        for part in artifact.parts
        if isinstance(part, TextPart)
    )


__all__ = [
    "DEFAULT_IDLE_TTL_SECONDS",
    "A2ATaskHandler",
    "Session",
    "SessionFactory",
    "SessionRegistry",
    "apply_artifact_text",
]
