"""Tests for CapabilityResolver memory policy selection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from assistant.core.capabilities.memory import (
    FileMemoryPolicy,
    HostProvidedMemoryPolicy,
    PostgresGraphitiMemoryPolicy,
)
from assistant.core.capabilities.resolver import CapabilityResolver


def _persona(database_url: str = "") -> MagicMock:
    p = MagicMock()
    p.name = "test"
    p.database_url = database_url
    p.graphiti_url = ""
    p.raw = {"graphiti": {}}
    return p


class TestResolverMemorySelection:
    @patch("assistant.core.graphiti.create_graphiti_client", return_value=None)
    @patch("assistant.core.db.async_session_factory")
    @patch("assistant.core.db.create_async_engine")
    def test_selects_postgres_when_database_url_present(self, mock_eng, mock_sf, mock_gc):
        resolver = CapabilityResolver()
        persona = _persona("postgresql+asyncpg://localhost/testdb")
        role = MagicMock()
        cs = resolver.resolve(persona, "sdk", role)
        assert isinstance(cs.memory, PostgresGraphitiMemoryPolicy)

    def test_selects_file_when_database_url_empty(self):
        resolver = CapabilityResolver()
        persona = _persona("")
        role = MagicMock()
        cs = resolver.resolve(persona, "sdk", role)
        assert isinstance(cs.memory, FileMemoryPolicy)

    def test_host_harness_unchanged(self):
        resolver = CapabilityResolver()
        persona = _persona("postgresql+asyncpg://localhost/testdb")
        role = MagicMock()
        cs = resolver.resolve(persona, "host", role)
        assert isinstance(cs.memory, HostProvidedMemoryPolicy)
