"""Session registry — neutral home for serving-surface sessions (P30).

Extracted from ``assistant.a2a.task_handler`` (the recorded P17 D7
relocation follow-up): the registry is shared by the A2A and MCP
surfaces (and any future one), so it lives in the harness layer where
both may import it without an A2A→MCP dependency. The old import path
re-exports these names for compatibility.

``SessionRegistry`` implements the harness-adapter Session Registry
requirement: create / lookup / expire sessions keyed by ``thread_id``.
The in-memory maps stay the default. P30 durable-sessions adds the
optional durable tier:

- a ``store`` (``core.durable`` SessionStore shape) records session
  metadata rows on create and refreshes them on lookup;
- a ``rebind_factory`` re-creates a harness+agent bound to a SPECIFIC
  ``thread_id`` — the durable LangGraph checkpointer restores the
  conversation state, so an in-process-expired (or restart-lost)
  session becomes resumable;
- the async :meth:`SessionRegistry.resolve` is the serving surfaces'
  new lookup: live session first, then durable re-bind, and ``None``
  only for truly unknown/expired ids.

In-process idle expiry releases process resources ONLY — it never
deletes durably checkpointed state, and a re-bind after expiry sees
the prior history. Durable validity is governed separately by the
persona's ``sessions.session_ttl_seconds`` window (0 = never lapses),
stamped on the metadata row.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Builds a fresh (harness, agent) pair per session — the same
# persona/role/harness pipeline the web lifespan runs, packaged as an
# injectable factory so tests can supply fakes.
SessionFactory = Callable[[], Awaitable[tuple[Any, Any]]]

# Re-builds a (harness, agent) pair bound to an EXISTING thread_id
# (durable re-bind; the checkpointer restores the conversation state).
RebindFactory = Callable[[str], Awaitable[tuple[Any, Any]]]

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
    """Create/lookup/expire session registry keyed by thread_id.

    Semantics per the harness-adapter Session Registry requirement:
    ``create`` builds a new session (fresh harness + agent via the
    injected factory) and keys it by the harness's own ``thread_id``;
    ``lookup`` returns the live session or ``None`` (never silently
    creates); ``expire`` releases in-process resources by thread_id,
    and an idle-TTL sweep (run opportunistically on create/lookup)
    expires sessions unused for ``idle_ttl_seconds``. Durably
    checkpointed state is NOT deleted by expiry — with a durable
    ``store`` + ``rebind_factory`` configured, :meth:`resolve`
    re-creates a session bound to the same thread_id; without them
    (the default) expired/unknown ids stay unresumable (pre-P30
    behavior).
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        store: Any | None = None,
        rebind_factory: RebindFactory | None = None,
        persona: str = "",
        role: str = "",
        harness: str = "",
        durable_ttl_seconds: float = 0.0,
    ) -> None:
        self._factory = session_factory
        self._idle_ttl = idle_ttl_seconds
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        # P30 durable tier (all optional; None/empty = in-memory only).
        self._store = store
        self._rebind = rebind_factory
        self._persona = persona
        self._role = role
        self._harness = harness
        self._durable_ttl = durable_ttl_seconds

    def __len__(self) -> int:
        return len(self._sessions)

    # -- durable metadata (best-effort; failures never break serving) --

    def _record_session(self, thread_id: str) -> None:
        if self._store is None:
            return
        try:
            from assistant.core.durable import SessionRecord

            now = datetime.now(UTC)
            expires_at = None
            if self._durable_ttl > 0:
                from datetime import timedelta

                expires_at = now + timedelta(seconds=self._durable_ttl)
            self._store.record(
                SessionRecord(
                    thread_id=thread_id,
                    persona=self._persona,
                    role=self._role,
                    harness=self._harness,
                    created_at=now,
                    last_used=now,
                    expires_at=expires_at,
                )
            )
        except Exception as exc:
            logger.warning(
                "session metadata not recorded for '%s' (%s); the "
                "in-process session is unaffected",
                thread_id,
                type(exc).__name__,
            )

    def _touch_session(self, thread_id: str) -> None:
        if self._store is None:
            return
        try:
            self._store.touch(thread_id, ttl_seconds=self._durable_ttl)
        except Exception as exc:
            logger.warning(
                "session metadata touch failed for '%s' (%s)",
                thread_id,
                type(exc).__name__,
            )

    # -- in-memory registry (pre-P30 semantics, unchanged) -------------

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
        self._record_session(thread_id)
        return session

    def lookup(self, thread_id: str) -> Session | None:
        """Return the live session for ``thread_id`` or ``None``.

        Unknown ids are signaled distinctly (``None``) — the registry
        never silently creates. A successful lookup refreshes the
        session's idle clock (and its durable metadata row).
        """
        self.expire_idle()
        session = self._sessions.get(thread_id)
        if session is not None:
            session.last_used = self._clock()
            self._touch_session(thread_id)
        return session

    async def resolve(self, thread_id: str) -> Session | None:
        """Live session, else durable re-bind, else ``None``.

        The P30 unknown-contextId contract for serving surfaces:

        1. a live in-process session wins (pre-P30 lookup);
        2. with a durable store, a known-``active``, un-lapsed metadata
           row for the SAME role is re-bound — the rebind factory
           constructs a fresh harness with the recorded ``thread_id``
           and the durable checkpointer restores the conversation;
        3. anything else (never created, expired, foreign role) is
           ``None`` — the caller rejects, exactly as before.
        """
        session = self.lookup(thread_id)
        if session is not None:
            return session
        if self._store is None or self._rebind is None:
            return None
        try:
            record = self._store.get(thread_id)
        except Exception as exc:
            logger.warning(
                "durable session lookup failed for '%s' (%s); treating "
                "as unknown",
                thread_id,
                type(exc).__name__,
            )
            return None
        if record is None or record.status != "active":
            return None
        if record.expires_at is not None and record.expires_at <= datetime.now(
            UTC
        ):
            try:
                self._store.mark_expired(thread_id)
            except Exception:  # pragma: no cover — best-effort
                pass
            logger.info(
                "durable session '%s' lapsed (session_ttl); rejecting",
                thread_id,
            )
            return None
        if self._role and record.role != self._role:
            # A thread created under another role's registry — never
            # silently continue it under this role.
            return None
        harness, agent = await self._rebind(thread_id)
        rebound_id = str(harness.thread_id)
        if rebound_id != thread_id:
            raise ValueError(
                f"rebind factory produced thread_id '{rebound_id}' for "
                f"requested '{thread_id}'"
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
        self._touch_session(thread_id)
        logger.info("durable session '%s' re-bound", thread_id)
        return session

    def expire(self, thread_id: str) -> bool:
        """Release the in-process session; True if one was registered.

        Durably checkpointed state (and the metadata row) is NOT
        deleted — a durable registry can re-bind the same thread_id
        later via :meth:`resolve`.
        """
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
            logger.info("session '%s' expired after idle TTL", tid)
        return expired


__all__ = [
    "DEFAULT_IDLE_TTL_SECONDS",
    "RebindFactory",
    "Session",
    "SessionFactory",
    "SessionRegistry",
]
