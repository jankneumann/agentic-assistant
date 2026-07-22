"""Async database engine factory with per-persona connection pooling.

P30 durable-sessions adds a small SYNC engine tier
(:func:`create_sync_engine`): the durable stores (session metadata,
approvals, spend ledger, audit log — ``core/durable.py``) are consumed
from synchronous call sites (the ``BudgetLedger`` protocol is sync,
and the guardrail confirmation hooks run inside sync functions), so
they run short queries over a sync SQLAlchemy engine. URLs are
normalized to the ``postgresql+psycopg`` dialect (psycopg v3 arrives
with ``langgraph-checkpoint-postgres``); non-Postgres URLs (e.g. the
sqlite URLs the tests use) pass through unchanged.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine
from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as _sa_create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine_cache: dict[str, AsyncEngine] = {}


def create_async_engine(persona: Any) -> AsyncEngine:
    url = persona.database_url
    if not url:
        raise ValueError(
            f"No database_url configured for persona '{persona.name}'"
        )
    if url in _engine_cache:
        return _engine_cache[url]
    engine = _sa_create_async_engine(url, pool_size=2, max_overflow=0)
    _engine_cache[url] = engine
    return engine


def async_session_factory(engine: AsyncEngine | None) -> async_sessionmaker[AsyncSession]:
    if engine is None:
        raise ValueError("Cannot create session factory with None engine")
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _clear_engine_cache() -> None:
    _engine_cache.clear()


# ── Sync tier (P30 durable-sessions) ─────────────────────────────────

_sync_engine_cache: dict[str, Engine] = {}


def sync_db_url(url: str) -> str:
    """Normalize a persona ``database_url`` for the sync psycopg dialect.

    ``postgres://`` / ``postgresql://`` / ``postgresql+asyncpg://`` all
    map onto ``postgresql+psycopg://``; anything else (sqlite test
    URLs, already-psycopg URLs) passes through unchanged.
    """
    for prefix in (
        "postgresql+asyncpg://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def create_sync_engine(database_url: str) -> Engine:
    """Build (and cache per-URL) a sync engine for the durable stores."""
    if not database_url:
        raise ValueError("create_sync_engine requires a non-empty database_url")
    url = sync_db_url(database_url)
    if url in _sync_engine_cache:
        return _sync_engine_cache[url]
    kwargs: dict[str, Any] = {}
    if url.startswith("postgresql"):
        kwargs = {"pool_size": 2, "max_overflow": 0, "pool_pre_ping": True}
    engine = _sa_create_engine(url, **kwargs)
    _sync_engine_cache[url] = engine
    return engine


def _clear_sync_engine_cache() -> None:
    for engine in _sync_engine_cache.values():
        engine.dispose()
    _sync_engine_cache.clear()
