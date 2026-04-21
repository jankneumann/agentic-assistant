"""Tests for core/memory.py — MemoryManager Graphiti path."""

from __future__ import annotations

import logging
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


def _empty_session():
    session = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)
    return session


class TestGetContextWithGraphiti:
    @pytest.mark.asyncio
    async def test_includes_semantic_context(self):
        session = _empty_session()
        graphiti = AsyncMock()
        graphiti.search = AsyncMock(return_value=["Entity: newsletter system"])

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=graphiti)
        ctx = await mgr.get_context("test", "researcher")

        assert "## Semantic Context" in ctx
        assert "newsletter system" in ctx

    @pytest.mark.asyncio
    async def test_degrades_on_connection_error(self, caplog):
        session = _empty_session()
        graphiti = AsyncMock()
        graphiti.search = AsyncMock(side_effect=ConnectionError("FalkorDB down"))

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=graphiti)

        with caplog.at_level(logging.WARNING):
            ctx = await mgr.get_context("test", "researcher")

        assert "## Active Context" in ctx
        assert "## Semantic Context" not in ctx
        assert "Graphiti search failed" in caplog.text


class TestStoreEpisode:
    @pytest.mark.asyncio
    async def test_calls_add_episode(self):
        session = _empty_session()
        graphiti = AsyncMock()
        graphiti.add_episode = AsyncMock()

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=graphiti)
        await mgr.store_episode("test", "User likes concise replies", "conversation")

        graphiti.add_episode.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_when_graphiti_none(self, caplog):
        session = _empty_session()
        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)

        with caplog.at_level(logging.WARNING):
            await mgr.store_episode("test", "content", "conversation")

        assert "Graphiti unavailable for persona 'test'" in caplog.text
        assert "source=conversation" in caplog.text

    @pytest.mark.asyncio
    async def test_degrades_on_connection_error(self, caplog):
        session = _empty_session()
        graphiti = AsyncMock()
        graphiti.add_episode = AsyncMock(side_effect=ConnectionError("down"))

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=graphiti)

        with caplog.at_level(logging.WARNING):
            await mgr.store_episode("test", "content", "conversation")

        assert "add_episode failed" in caplog.text


class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_list_of_strings(self):
        session = _empty_session()
        graphiti = AsyncMock()
        graphiti.search = AsyncMock(return_value=["result1", "result2"])

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=graphiti)
        results = await mgr.search("test", "newsletter", num_results=5)

        assert results == ["result1", "result2"]
        graphiti.search.assert_called_once_with("newsletter", num_results=5)

    @pytest.mark.asyncio
    async def test_defaults_num_results_to_5(self):
        session = _empty_session()
        graphiti = AsyncMock()
        graphiti.search = AsyncMock(return_value=[])

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=graphiti)
        await mgr.search("test", "query")

        graphiti.search.assert_called_once_with("query", num_results=5)

    @pytest.mark.asyncio
    async def test_returns_empty_when_graphiti_none(self):
        session = _empty_session()
        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        results = await mgr.search("test", "query")
        assert results == []


class TestExportMemoryWithGraphiti:
    @pytest.mark.asyncio
    async def test_includes_knowledge_graph(self):
        session = AsyncMock()

        entries_scalars = MagicMock()
        entries_scalars.all.return_value = []
        prefs_scalars = MagicMock()
        prefs_scalars.all.return_value = []
        inters_scalars = MagicMock()
        inters_scalars.all.return_value = []

        results = []
        for scalars in [entries_scalars, prefs_scalars, inters_scalars]:
            r = MagicMock()
            r.scalars.return_value = scalars
            results.append(r)

        session.execute = AsyncMock(side_effect=results)

        graphiti = AsyncMock()
        graphiti.search = AsyncMock(return_value=["Entity: newsletter"])

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=graphiti)
        output = await mgr.export_memory("test")

        assert "## Knowledge Graph Summary" in output
        assert "newsletter" in output

    @pytest.mark.asyncio
    async def test_omits_knowledge_graph_when_none(self):
        session = AsyncMock()
        for _ in range(3):
            scalars = MagicMock()
            scalars.all.return_value = []

        entries_r = MagicMock()
        entries_r.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        prefs_r = MagicMock()
        prefs_r.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        inters_r = MagicMock()
        inters_r.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        session.execute = AsyncMock(side_effect=[entries_r, prefs_r, inters_r])

        factory = _make_session_factory(session)
        mgr = MemoryManager(factory, graphiti_client=None)
        output = await mgr.export_memory("test")

        assert "## Knowledge Graph Summary" not in output
