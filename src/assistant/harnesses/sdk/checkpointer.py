"""LangGraph checkpointer resolution for the DeepAgents harness (P30).

Durable session persistence adopts the LangGraph checkpointer
interface rather than inventing a session store (harness-adapter
spec, Durable Session Persistence): the harness accepts an injected
checkpointer at construction, and when none is injected this module
resolves one from persona config:

- no ``sessions:`` section (or ``durable: false``) → a fresh
  :class:`InMemorySaver` per agent (pre-P30 behavior, byte-identical);
- ``sessions: {durable: true}`` + a resolved ``database_url`` →
  a process-cached ``AsyncPostgresSaver`` from
  ``langgraph-checkpoint-postgres``, one per database url, shared by
  every harness bound to that persona DB so all thread_ids land in
  one checkpoint store.

Schema note: the durable saver's ``setup()`` is called exactly once
per process/url on first use — it creates/updates the checkpointer's
OWN tables (``checkpoints`` etc.). That schema belongs to the
langgraph-checkpoint-postgres package and versions with it; the
assistant's alembic migrations (001/002) deliberately do NOT manage
it — two separate concerns, documented in ``core/durable.py`` and the
durable-sessions design doc.

Connection-string note: ``AsyncPostgresSaver.from_conn_string`` takes
a psycopg (v3) conn string, so SQLAlchemy driver suffixes
(``+asyncpg``/``+psycopg``) are stripped.
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import AsyncExitStack
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

logger = logging.getLogger(__name__)

#: Process-wide cache: one durable saver (+ its owning exit stack) per
#: database url. Harnesses are constructed per session/turn; the saver
#: must outlive all of them.
_DURABLE_SAVERS: dict[str, Any] = {}
_SAVER_STACKS: dict[str, AsyncExitStack] = {}
_SAVERS_LOCK = asyncio.Lock()


def _psycopg_conn_string(database_url: str) -> str:
    """Strip SQLAlchemy driver suffixes for the raw psycopg saver."""
    return re.sub(
        r"^postg(?:res|resql)\+[a-z0-9_]+://",
        "postgresql://",
        database_url,
    )


async def _build_durable_saver(database_url: str) -> Any:
    """Construct + ``setup()`` the AsyncPostgresSaver (patch point)."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    stack = AsyncExitStack()
    saver = await stack.enter_async_context(
        AsyncPostgresSaver.from_conn_string(
            _psycopg_conn_string(database_url)
        )
    )
    # First-use schema setup — the checkpointer manages its own tables
    # (separate from alembic; see module docstring).
    await saver.setup()
    _SAVER_STACKS[database_url] = stack
    return saver


async def resolve_checkpointer(persona: Any) -> Any:
    """Resolve the checkpointer for a persona per the P30 contract.

    Durable declared but no database url → actionable error (declared
    durability must never silently degrade to in-memory).
    """
    settings = getattr(persona, "sessions", None)
    if settings is None or not getattr(settings, "durable", False):
        return InMemorySaver()
    database_url = getattr(persona, "database_url", "")
    if not database_url:
        raise ValueError(
            f"Persona '{getattr(persona, 'name', '?')}' declares "
            f"sessions: {{durable: true}} but no database url resolved — "
            f"configure database: {{url_env: ...}} or remove the "
            f"sessions section."
        )
    async with _SAVERS_LOCK:
        saver = _DURABLE_SAVERS.get(database_url)
        if saver is None:
            saver = await _build_durable_saver(database_url)
            _DURABLE_SAVERS[database_url] = saver
            logger.info(
                "durable checkpointer initialized for persona '%s'",
                getattr(persona, "name", "?"),
            )
        return saver


async def close_checkpointers() -> None:
    """Release every cached durable saver (daemon/server shutdown)."""
    async with _SAVERS_LOCK:
        for url, stack in list(_SAVER_STACKS.items()):
            try:
                await stack.aclose()
            except Exception as exc:
                logger.warning(
                    "durable checkpointer close failed (%s)",
                    type(exc).__name__,
                )
            _SAVER_STACKS.pop(url, None)
            _DURABLE_SAVERS.pop(url, None)


def _clear_checkpointer_cache() -> None:
    """Test hook: drop cached savers WITHOUT closing (fakes only)."""
    _DURABLE_SAVERS.clear()
    _SAVER_STACKS.clear()


__all__ = [
    "close_checkpointers",
    "resolve_checkpointer",
]
