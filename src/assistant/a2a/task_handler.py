"""A2A task lifecycle over ``SdkHarnessAdapter.astream_invoke``.

``A2ATaskHandler`` — task lifecycle (submitted → working →
completed/failed, with the input-required approval bridge handled by
the transports/a2a mapper): resolves the session from the incoming
message's ``contextId`` (A2A contextId ≡ session ``thread_id``), runs
the harness stream through ``map_harness_to_a2a``, and maintains an
in-memory task store so ``message/send`` can return the terminal Task
snapshot.

``SessionRegistry`` moved to ``assistant.harnesses.sessions`` in P30
durable-sessions (the recorded P17 D7 relocation — the registry is
shared with the MCP surface and now optionally durable). This module
re-exports the session names so existing imports keep working.
Unknown-``contextId`` handling upgraded with it: the handler resolves
through ``SessionRegistry.resolve`` — live session, else durable
re-bind (the checkpointer restores conversation state), and only a
truly unknown/expired id is rejected.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing

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
from assistant.harnesses.sessions import (
    DEFAULT_IDLE_TTL_SECONDS,
    Session,
    SessionFactory,
    SessionRegistry,
)
from assistant.transports.a2a.mapper import map_harness_to_a2a

logger = logging.getLogger(__name__)


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
            # P30 durable-sessions: live session first, then durable
            # re-bind (checkpointer restores conversation state); only a
            # truly unknown/expired contextId is rejected.
            session = await self._registry.resolve(message.context_id)
            if session is None:
                raise A2AProtocolError(
                    INVALID_PARAMS,
                    f"unknown contextId '{message.context_id}' "
                    "(never created, expired, or not durably resumable)",
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
