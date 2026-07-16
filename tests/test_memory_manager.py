"""Tests for core/memory.py — MemoryManager Postgres path."""

from __future__ import annotations

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


def _mock_entry(key: str, value: dict):
    entry = MagicMock()
    entry.key = key
    entry.value = value
    entry.updated_at = "2026-04-21T00:00:00"
    return entry


def _mock_pref(category: str, key: str, value, confidence: float):
    pref = MagicMock()
    pref.category = category
    pref.key = key
    pref.value = value
    pref.confidence = confidence
    return pref


def _mock_interaction(role: str, summary: str, created_at: str):
    inter = MagicMock()
    inter.role = role
    inter.summary = summary
    inter.created_at = created_at
    return inter


class TestGetContext:
    @pytest.mark.asyncio
    async def test_returns_active_context_section(self):
        session = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = [_mock_entry("project", {"name": "test"})]
        result = MagicMock()
        result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result)

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        ctx = await mgr.get_context("test", "researcher")

        assert "## Active Context" in ctx
        assert "project" in ctx

    @pytest.mark.asyncio
    async def test_postgres_only_when_no_graphiti(self):
        session = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        result = MagicMock()
        result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result)

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        ctx = await mgr.get_context("test", "researcher")

        assert "## Active Context" in ctx
        assert "## Semantic Context" not in ctx


def _result_for(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


class TestGetRecentSnippets:
    @pytest.mark.asyncio
    async def test_happy_path_mixes_durable_and_recent(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _result_for([_mock_entry("project", {"name": "newsletter"})]),
                _result_for([_mock_pref("comm", "tone", "concise", 0.9)]),
                _result_for(
                    [_mock_interaction("researcher", "Found papers", "2026-07-01")]
                ),
            ]
        )

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        snippets = await mgr.get_recent_snippets("test", "researcher", limit=10)

        assert any("project" in s for s in snippets)
        assert any("tone" in s for s in snippets)
        assert any("Found papers" in s for s in snippets)
        assert len(snippets) <= 10

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[_result_for([]), _result_for([]), _result_for([])]
        )

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        snippets = await mgr.get_recent_snippets("test", "researcher")

        assert snippets == []

    @pytest.mark.asyncio
    async def test_limit_budget_split_between_durable_and_recent(self):
        entries = [_mock_entry(f"key{i}", {"v": i}) for i in range(10)]
        interactions = [
            _mock_interaction("researcher", f"turn {i}", "2026-07-01")
            for i in range(10)
        ]
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _result_for(entries),
                _result_for([]),
                _result_for(interactions),
            ]
        )

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        snippets = await mgr.get_recent_snippets("test", "researcher", limit=4)

        assert len(snippets) == 4
        # Ceil half durable (facts), floor half recent (interactions).
        assert sum("key" in s for s in snippets) == 2
        assert sum("turn" in s for s in snippets) == 2

    @pytest.mark.asyncio
    async def test_recent_backfills_when_durable_scarce(self):
        interactions = [
            _mock_interaction("researcher", f"turn {i}", "2026-07-01")
            for i in range(10)
        ]
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _result_for([]),
                _result_for([]),
                _result_for(interactions),
            ]
        )

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        snippets = await mgr.get_recent_snippets("test", "researcher", limit=4)

        assert len(snippets) == 4
        assert all("turn" in s for s in snippets)

    @pytest.mark.asyncio
    async def test_nonpositive_limit_returns_empty(self):
        session = AsyncMock()
        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)

        assert await mgr.get_recent_snippets("test", "researcher", limit=0) == []
        session.execute.assert_not_called()


class TestStoreFact:
    @pytest.mark.asyncio
    async def test_persists_to_postgres(self):
        session = AsyncMock()
        factory = _make_session_factory(session)
        mgr = MemoryManager(factory)

        await mgr.store_fact("test", "project", {"name": "newsletter"})
        session.execute.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_non_serializable(self):
        session = AsyncMock()
        factory = _make_session_factory(session)
        mgr = MemoryManager(factory)

        with pytest.raises(ValueError, match="not JSON-serializable"):
            await mgr.store_fact("test", "bad", object())


class TestStoreInteraction:
    @pytest.mark.asyncio
    async def test_persists_with_metadata(self):
        session = AsyncMock()
        factory = _make_session_factory(session)
        mgr = MemoryManager(factory)

        await mgr.store_interaction("test", "researcher", "Found papers", {"count": 3})
        session.add.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_defaults_metadata_to_empty_dict(self):
        session = AsyncMock()
        factory = _make_session_factory(session)
        mgr = MemoryManager(factory)

        await mgr.store_interaction("test", "researcher", "Found papers")
        call_args = session.add.call_args[0][0]
        assert call_args.metadata_ == {}


class TestExportMemory:
    @pytest.mark.asyncio
    async def test_produces_structured_markdown(self):
        session = AsyncMock()

        entries_scalars = MagicMock()
        entries_scalars.all.return_value = [_mock_entry("project", {"name": "test"})]
        entries_result = MagicMock()
        entries_result.scalars.return_value = entries_scalars

        prefs_scalars = MagicMock()
        prefs_scalars.all.return_value = [_mock_pref("comm", "tone", "concise", 0.9)]
        prefs_result = MagicMock()
        prefs_result.scalars.return_value = prefs_scalars

        inters_scalars = MagicMock()
        inters_scalars.all.return_value = [_mock_interaction("researcher", "Found papers", "2026-04-21")]
        inters_result = MagicMock()
        inters_result.scalars.return_value = inters_scalars

        session.execute = AsyncMock(side_effect=[entries_result, prefs_result, inters_result])

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        output = await mgr.export_memory("test")

        assert "## Active Context" in output
        assert "project" in output
        assert "## Preferences" in output
        assert "tone" in output
        assert "## Recent Interactions" in output
        assert "Found papers" in output
        assert "## Knowledge Graph Summary" not in output
        assert output.endswith("\n")


class TestListInteractions:
    @pytest.mark.asyncio
    async def test_returns_json_safe_dicts_newest_first(self):
        from datetime import UTC, datetime

        session = AsyncMock()
        inter = _mock_interaction("researcher", "Found papers", "unused")
        inter.created_at = datetime(2026, 7, 16, tzinfo=UTC)
        inter.id = 7
        inter.metadata_ = {"harness": "deep_agents"}
        scalars = MagicMock()
        scalars.all.return_value = [inter]
        result = MagicMock()
        result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result)

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        records = await mgr.list_interactions("test", limit=10)

        assert records == [
            {
                "id": 7,
                "role": "researcher",
                "summary": "Found papers",
                "created_at": "2026-07-16T00:00:00+00:00",
                "metadata": {"harness": "deep_agents"},
            }
        ]

    @pytest.mark.asyncio
    async def test_non_datetime_created_at_stringified(self):
        session = AsyncMock()
        inter = _mock_interaction("coder", "Fixed bug", "2026-04-21")
        inter.id = 1
        inter.metadata_ = None
        scalars = MagicMock()
        scalars.all.return_value = [inter]
        result = MagicMock()
        result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result)

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        records = await mgr.list_interactions("test")

        assert records[0]["created_at"] == "2026-04-21"
        assert records[0]["metadata"] == {}

    @pytest.mark.asyncio
    async def test_nonpositive_limit_short_circuits(self):
        session = AsyncMock()
        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)

        assert await mgr.list_interactions("test", limit=0) == []
        session.execute.assert_not_called()
