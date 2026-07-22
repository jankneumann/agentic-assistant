"""MemoryPolicy protocol, FileMemoryPolicy, and PostgresGraphitiMemoryPolicy."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from collections.abc import Coroutine
from typing import Any, Protocol, runtime_checkable

from assistant.core.capabilities.types import MemoryConfig, MemoryScoping

logger = logging.getLogger(__name__)

#: Total character budget for FileMemoryPolicy snippet excerpts. Keeps
#: the ``## Recent context`` prepend bounded for personas whose
#: ``memory.md`` has grown large (memory-retrieval-activation).
_FILE_SNIPPET_CHAR_BUDGET: int = 4000

#: Per-side excerpt cap for post-turn interaction summaries.
_CAPTURE_EXCERPT_CHARS: int = 240


def _run_blocking[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion from synchronous code.

    Sync-edge bridge only (memory-retrieval-activation design.md D1, as
    amended by the capability-protocols-v2 owner review verdict C8,
    2026-07-16): snippet retrieval is async at the protocol level and is
    awaited directly on the hot ``create_agent`` path, so this helper
    serves only true sync edges — today the sync
    ``export_memory_context`` consumed by host-harness
    ``export_context`` / CLI ``export``.

    - **No running loop** (CLI export, sync tests): ``asyncio.run``.
    - **Inside a running loop** (defensive — a sync edge invoked from
      async code): dispatch ``asyncio.run`` to a fresh worker thread and
      block on its result. Calling ``loop.run_until_complete`` here
      would deadlock; the worker thread runs the coroutine on its own
      private event loop instead. Note this path runs a *new* event
      loop each call, so loop-bound resources (e.g. asyncpg pooled
      connections) cannot be reused across calls.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _split_markdown_sections(text: str) -> list[str]:
    """Split markdown into ``## ``-headed sections, in document order.

    Content before the first ``## `` heading forms its own leading
    section. Empty sections are dropped.
    """
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [s for s in sections if s]


def _summarize_turn(user_message: str, response: str) -> str:
    """One-line turn summary for the ``interactions`` table.

    Whitespace-normalized, each side capped at
    ``_CAPTURE_EXCERPT_CHARS`` so a pathological turn cannot bloat the
    row. Full-fidelity transcripts are out of scope for P21 — the
    summary is a retrieval cue, not a replay log.
    """
    user = " ".join(user_message.split())[:_CAPTURE_EXCERPT_CHARS]
    assistant = " ".join(response.split())[:_CAPTURE_EXCERPT_CHARS]
    return f"user: {user} | assistant: {assistant}"


@runtime_checkable
class MemoryPolicy(Protocol):
    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig: ...
    def export_memory_context(self, persona: Any) -> str: ...
    async def get_recent_snippets(
        self, persona: Any, role: Any, *, limit: int = 10
    ) -> list[str]:
        """Return up to ``limit`` recent memory snippets for prepend.

        Added in ms-graph-extension D27; activated for real retrieval
        in memory-retrieval-activation; async at the protocol level per
        the capability-protocols-v2 owner review verdict C8
        (2026-07-16). SDK harnesses await the result and prepend it
        under a ``## Recent context`` heading at ``create_agent`` time;
        sync callers bridge at their own edge. Implementations MUST
        degrade to ``[]`` on backend failure — snippet retrieval must
        never break agent construction.
        """
        ...

    async def record_interaction(
        self, persona: Any, role: Any, *, user_message: str, response: str
    ) -> None:
        """Persist a completed turn to the policy's backend (best effort).

        Added in memory-retrieval-activation. SDK harnesses call this
        after a successful ``invoke`` / ``astream_invoke``; policies
        without a per-turn write path implement it as a no-op. Callers
        swallow exceptions — memory capture must never break a
        conversation.
        """
        ...


class FileMemoryPolicy:
    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig:
        harness_cfg = persona.harnesses.get(harness_name, {}) or {}
        memory_files = harness_cfg.get("memory_files") or ["./AGENTS.md"]
        return MemoryConfig(
            backend_type="file",
            config={"memory_files": memory_files},
            scoping=MemoryScoping(),
        )

    def export_memory_context(self, persona: Any) -> str:
        return persona.memory_content or ""

    async def get_recent_snippets(
        self, persona: Any, role: Any, *, limit: int = 10
    ) -> list[str]:
        """Bounded excerpts from the persona's ``memory.md``.

        The file is treated as append-ordered: later ``## `` sections
        are more recent, so sections are returned most-recent-first.
        Bounds: at most ``limit`` sections AND at most
        ``_FILE_SNIPPET_CHAR_BUDGET`` total characters (the section
        that crosses the budget is truncated to fit).
        """
        if limit <= 0:
            return []
        content = (getattr(persona, "memory_content", "") or "").strip()
        if not content:
            return []
        snippets: list[str] = []
        used = 0
        for section in reversed(_split_markdown_sections(content)):
            if len(snippets) >= limit:
                break
            remaining = _FILE_SNIPPET_CHAR_BUDGET - used
            if remaining <= 0:
                break
            excerpt = section[:remaining]
            snippets.append(excerpt)
            used += len(excerpt)
        return snippets

    async def record_interaction(
        self, persona: Any, role: Any, *, user_message: str, response: str
    ) -> None:
        # File-backed memory has no per-turn write path — memory.md is
        # curated by the user, not appended to by the harness.
        return None


class PostgresGraphitiMemoryPolicy:
    """MemoryPolicy backed by MemoryManager (Postgres + Graphiti)."""

    def __init__(self, persona: Any) -> None:
        from assistant.core.db import async_session_factory, create_async_engine
        from assistant.core.graphiti import create_graphiti_client
        from assistant.core.memory import MemoryManager

        engine = create_async_engine(persona)
        session_fac = async_session_factory(engine)
        graphiti = create_graphiti_client(persona)
        self._manager = MemoryManager(session_fac, graphiti_client=graphiti)
        self._persona_name = persona.name

    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig:
        return MemoryConfig(
            backend_type="postgres",
            config={},
            scoping=MemoryScoping(),
        )

    def export_memory_context(self, persona: Any) -> str:
        return _run_blocking(self._manager.export_memory(persona.name))

    async def get_recent_snippets(
        self, persona: Any, role: Any, *, limit: int = 10
    ) -> list[str]:
        """Live snippet retrieval via ``MemoryManager.get_recent_snippets``.

        Awaits the async manager directly on the caller's event loop
        (no worker-thread bridge — capability-protocols-v2 owner review
        verdict C8, 2026-07-16). Degrades to ``[]`` with a warning on
        any backend failure — a down database must never break
        ``create_agent``.
        """
        persona_name = getattr(persona, "name", None) or self._persona_name
        role_name = getattr(role, "name", str(role))
        try:
            return await self._manager.get_recent_snippets(
                persona_name, role_name, limit=limit
            )
        except Exception:
            logger.warning(
                "Memory snippet retrieval failed for persona '%s', "
                "continuing without snippets",
                persona_name,
            )
            return []

    async def record_interaction(
        self, persona: Any, role: Any, *, user_message: str, response: str
    ) -> None:
        """Store a one-line turn summary in the ``interactions`` table.

        Telemetry rides on ``MemoryManager.store_interaction``'s
        ``@trace_memory_op("interaction_write")``. Exceptions propagate
        — the harness-side capture helper owns swallow-and-warn.
        """
        persona_name = getattr(persona, "name", None) or self._persona_name
        role_name = getattr(role, "name", str(role))
        await self._manager.store_interaction(
            persona_name,
            role_name,
            _summarize_turn(user_message, response),
            metadata={"source": "post_turn_capture"},
        )


class HostProvidedMemoryPolicy:
    """Returns host_provided config for host harnesses (Claude Code, Codex)."""

    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig:
        return MemoryConfig(
            backend_type="host_provided",
            config={},
            scoping=MemoryScoping(),
        )

    def export_memory_context(self, persona: Any) -> str:
        return persona.memory_content or ""

    async def get_recent_snippets(
        self, persona: Any, role: Any, *, limit: int = 10
    ) -> list[str]:
        # Host-provided memory leaves snippet retrieval to the host —
        # SDK harnesses asking for snippets get an empty list back.
        return []

    async def record_interaction(
        self, persona: Any, role: Any, *, user_message: str, response: str
    ) -> None:
        # The host owns memory persistence for host harnesses.
        return None
