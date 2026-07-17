"""MemoryManager structured reads + prefix deletion (P26 clean-room).

Mirrors the mocked-session style of tests/test_memory_manager.py — no
real database; the SQL surface is asserted through the session mock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.core.memory import MemoryManager


def _make_session_factory(session: AsyncMock) -> MagicMock:
    factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = ctx
    return factory


def _session_returning(rows) -> AsyncMock:
    session = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)
    return session


class TestListFacts:
    @pytest.mark.asyncio
    async def test_returns_json_safe_dicts(self):
        entry = MagicMock()
        entry.id = 3
        entry.key = "project"
        entry.value = {"name": "apollo"}
        entry.updated_at = datetime(2026, 7, 17, tzinfo=UTC)
        session = _session_returning([entry])

        mgr = MemoryManager(_make_session_factory(session))
        facts = await mgr.list_facts("fixture", limit=10)

        assert facts == [
            {
                "id": 3,
                "key": "project",
                "value": {"name": "apollo"},
                "updated_at": "2026-07-17T00:00:00+00:00",
            }
        ]

    @pytest.mark.asyncio
    async def test_non_positive_limit_short_circuits(self):
        session = AsyncMock()
        mgr = MemoryManager(_make_session_factory(session))
        assert await mgr.list_facts("fixture", limit=0) == []
        session.execute.assert_not_awaited()


class TestListPreferences:
    @pytest.mark.asyncio
    async def test_returns_json_safe_dicts(self):
        pref = MagicMock()
        pref.id = 1
        pref.category = "communication"
        pref.key = "tone"
        pref.value = "concise"
        pref.confidence = 0.9
        pref.updated_at = datetime(2026, 7, 17, tzinfo=UTC)
        session = _session_returning([pref])

        mgr = MemoryManager(_make_session_factory(session))
        prefs = await mgr.list_preferences("fixture")

        assert prefs[0]["category"] == "communication"
        assert prefs[0]["key"] == "tone"
        assert prefs[0]["confidence"] == 0.9
        assert prefs[0]["updated_at"] == "2026-07-17T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_non_positive_limit_short_circuits(self):
        session = AsyncMock()
        mgr = MemoryManager(_make_session_factory(session))
        assert await mgr.list_preferences("fixture", limit=-1) == []
        session.execute.assert_not_awaited()


class TestDeleteFactsByPrefix:
    @pytest.mark.asyncio
    async def test_deletes_and_returns_rowcount(self):
        session = AsyncMock()
        result = MagicMock()
        result.rowcount = 3
        session.execute = AsyncMock(return_value=result)

        mgr = MemoryManager(_make_session_factory(session))
        deleted = await mgr.delete_facts_by_prefix(
            "fixture", "cleanroom/abc123/"
        )

        assert deleted == 3
        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_prefix_is_refused(self):
        session = AsyncMock()
        mgr = MemoryManager(_make_session_factory(session))
        with pytest.raises(ValueError, match="non-empty"):
            await mgr.delete_facts_by_prefix("fixture", "")
        session.execute.assert_not_awaited()
