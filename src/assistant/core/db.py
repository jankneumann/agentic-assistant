"""Async database engine factory with per-persona connection pooling."""

from __future__ import annotations

from typing import Any

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
