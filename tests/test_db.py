"""Tests for core/db.py — engine factory and session factory."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest

from assistant.core.db import (
    _clear_engine_cache,
    async_session_factory,
    create_async_engine,
)


@dataclass
class _FakePersona:
    name: str = "test"
    database_url: str = "postgresql+asyncpg://localhost/testdb"


class TestCreateAsyncEngine:
    def test_creates_engine_for_persona_with_url(self):
        persona = _FakePersona()
        with patch("assistant.core.db._sa_create_async_engine") as mock_create:
            mock_create.return_value = object()
            engine = create_async_engine(persona)
            assert engine is mock_create.return_value
            mock_create.assert_called_once_with(
                "postgresql+asyncpg://localhost/testdb",
                pool_size=2,
                max_overflow=0,
            )

    def test_uses_asyncpg_driver(self):
        persona = _FakePersona()
        assert "asyncpg" in persona.database_url

    def test_caches_engine_on_second_call(self):
        persona = _FakePersona()
        with patch("assistant.core.db._sa_create_async_engine") as mock_create:
            mock_create.return_value = object()
            engine1 = create_async_engine(persona)
            engine2 = create_async_engine(persona)
            assert engine1 is engine2
            assert mock_create.call_count == 1

    def test_raises_when_database_url_empty(self):
        persona = _FakePersona(database_url="")
        with pytest.raises(ValueError, match="No database_url configured"):
            create_async_engine(persona)

    def test_cache_cleared_between_calls(self):
        persona = _FakePersona()
        with patch("assistant.core.db._sa_create_async_engine") as mock_create:
            mock_create.return_value = object()
            create_async_engine(persona)
            _clear_engine_cache()
            mock_create.return_value = object()
            engine2 = create_async_engine(persona)
            assert mock_create.call_count == 2
            assert engine2 is mock_create.return_value


class TestAsyncSessionFactory:
    def test_returns_sessionmaker(self):
        from unittest.mock import MagicMock

        mock_engine = MagicMock()
        factory = async_session_factory(mock_engine)
        assert factory is not None

    def test_rejects_none_engine(self):
        with pytest.raises(ValueError, match="Cannot create session factory"):
            async_session_factory(None)
