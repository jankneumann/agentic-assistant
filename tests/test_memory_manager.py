"""Tests for core/memory.py — MemoryManager Postgres path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
