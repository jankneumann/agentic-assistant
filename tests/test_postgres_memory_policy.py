"""Tests for PostgresGraphitiMemoryPolicy."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.core.capabilities.memory import (
    MemoryPolicy,
    PostgresGraphitiMemoryPolicy,
)


@pytest.fixture
def mock_persona():
    persona = MagicMock()
    persona.name = "test"
    persona.database_url = "postgresql+asyncpg://localhost/testdb"
    persona.graphiti_url = ""
    persona.raw = {"graphiti": {}}
    return persona


def _make_policy(mock_persona) -> PostgresGraphitiMemoryPolicy:
    with (
        patch("assistant.core.graphiti.create_graphiti_client", return_value=None),
        patch("assistant.core.db.async_session_factory"),
        patch("assistant.core.db.create_async_engine"),
    ):
        return PostgresGraphitiMemoryPolicy(mock_persona)


class TestPostgresGraphitiMemoryPolicy:
    @patch("assistant.core.graphiti.create_graphiti_client", return_value=None)
    @patch("assistant.core.db.async_session_factory")
    @patch("assistant.core.db.create_async_engine")
    def test_satisfies_protocol(self, mock_engine, mock_sf, mock_gc, mock_persona):
        policy = PostgresGraphitiMemoryPolicy(mock_persona)
        assert isinstance(policy, MemoryPolicy)

    @patch("assistant.core.graphiti.create_graphiti_client", return_value=None)
    @patch("assistant.core.db.async_session_factory")
    @patch("assistant.core.db.create_async_engine")
    def test_resolve_returns_postgres_backend(self, mock_engine, mock_sf, mock_gc, mock_persona):
        policy = PostgresGraphitiMemoryPolicy(mock_persona)
        config = policy.resolve(mock_persona, "deep_agents")
        assert config.backend_type == "postgres"


class TestGetRecentSnippets:
    """memory-retrieval-activation: live retrieval via MemoryManager.

    Async at the protocol level (capability-protocols-v2 owner review
    verdict C8, 2026-07-16) — the policy awaits the manager directly on
    the caller's event loop; the former running-loop bridge test is
    gone with the bridge (see memory-retrieval-activation design.md D1).
    """

    async def test_returns_manager_snippets(self, mock_persona):
        policy = _make_policy(mock_persona)
        role = MagicMock()
        role.name = "researcher"
        policy._manager = MagicMock()
        policy._manager.get_recent_snippets = AsyncMock(
            return_value=["snippet-a", "snippet-b"]
        )

        snippets = await policy.get_recent_snippets(mock_persona, role, limit=5)

        assert snippets == ["snippet-a", "snippet-b"]
        policy._manager.get_recent_snippets.assert_awaited_once_with(
            "test", "researcher", limit=5
        )

    async def test_degrades_to_empty_on_backend_failure(
        self, mock_persona, caplog
    ):
        policy = _make_policy(mock_persona)
        role = MagicMock()
        role.name = "researcher"
        policy._manager = MagicMock()
        policy._manager.get_recent_snippets = AsyncMock(
            side_effect=ConnectionError("db down")
        )

        with caplog.at_level(logging.WARNING):
            snippets = await policy.get_recent_snippets(mock_persona, role)

        assert snippets == []
        assert "snippet retrieval failed" in caplog.text.lower()
        assert "test" in caplog.text


class TestExportMemoryContext:
    """The remaining sync edge — export bridges via ``_run_blocking``.

    ``export_memory_context`` stays sync for its true sync callers
    (host-harness ``export_context`` / CLI ``export``); the bridge
    tests moved here from ``get_recent_snippets`` when retrieval went
    async at the protocol level (capability-protocols-v2 owner review
    verdict C8, 2026-07-16)."""

    def test_bridges_outside_event_loop(self, mock_persona):
        policy = _make_policy(mock_persona)
        policy._manager = MagicMock()
        policy._manager.export_memory = AsyncMock(return_value="exported")

        assert policy.export_memory_context(mock_persona) == "exported"
        # The caller's persona name is passed through, not swallowed. The
        # real MemoryManager (bound to the same persona) then validates that
        # it matches; passing None would ignore the argument entirely.
        policy._manager.export_memory.assert_awaited_once_with("test")

    def test_export_rejects_mismatched_persona(self, mock_persona):
        """A policy bound to one persona must refuse to export another's
        memory rather than silently returning the bound persona's."""
        policy = _make_policy(mock_persona)  # bound to "test"

        other = MagicMock()
        other.name = "someone_else"

        with pytest.raises(ValueError, match="persona mismatch"):
            policy.export_memory_context(other)

    def test_bridges_from_inside_running_event_loop(self, mock_persona):
        """A sync edge invoked from async code must not deadlock —
        ``_run_blocking`` dispatches to a worker thread (design D1)."""
        policy = _make_policy(mock_persona)
        policy._manager = MagicMock()
        policy._manager.export_memory = AsyncMock(return_value="from-thread")

        async def _call_from_loop() -> str:
            return policy.export_memory_context(mock_persona)

        assert asyncio.run(_call_from_loop()) == "from-thread"


class TestRecordInteraction:
    """memory-retrieval-activation: post-turn capture delegate."""

    def test_delegates_to_store_interaction(self, mock_persona):
        policy = _make_policy(mock_persona)
        role = MagicMock()
        role.name = "researcher"
        policy._manager = MagicMock()
        policy._manager.store_interaction = AsyncMock()

        asyncio.run(
            policy.record_interaction(
                mock_persona,
                role,
                user_message="  what's   new? ",
                response="not much",
            )
        )

        policy._manager.store_interaction.assert_awaited_once()
        args, kwargs = policy._manager.store_interaction.await_args
        assert args[0] == "test"
        assert args[1] == "researcher"
        assert "what's new?" in args[2]
        assert "not much" in args[2]
        assert kwargs["metadata"] == {"source": "post_turn_capture"}

    def test_summary_is_bounded(self, mock_persona):
        from assistant.core.capabilities.memory import _CAPTURE_EXCERPT_CHARS

        policy = _make_policy(mock_persona)
        role = MagicMock()
        role.name = "researcher"
        policy._manager = MagicMock()
        policy._manager.store_interaction = AsyncMock()

        asyncio.run(
            policy.record_interaction(
                mock_persona,
                role,
                user_message="u" * 10_000,
                response="r" * 10_000,
            )
        )

        summary = policy._manager.store_interaction.await_args.args[2]
        assert len(summary) <= 2 * _CAPTURE_EXCERPT_CHARS + len(
            "user:  | assistant: "
        )

    def test_backend_errors_propagate_to_caller(self, mock_persona):
        """The policy does NOT swallow — the harness capture helper owns
        swallow-and-warn (spec: Post-Turn Interaction Capture)."""
        policy = _make_policy(mock_persona)
        role = MagicMock()
        role.name = "researcher"
        policy._manager = MagicMock()
        policy._manager.store_interaction = AsyncMock(
            side_effect=ConnectionError("db down")
        )

        with pytest.raises(ConnectionError):
            asyncio.run(
                policy.record_interaction(
                    mock_persona, role, user_message="hi", response="yo"
                )
            )
