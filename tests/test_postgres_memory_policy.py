"""Tests for PostgresGraphitiMemoryPolicy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
