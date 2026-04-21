"""Tests for core/graphiti.py — Graphiti client factory with FalkorDB."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from assistant.core.graphiti import _clear_graphiti_cache, create_graphiti_client


@dataclass
class _FakePersona:
    name: str = "test"
    graphiti_url: str = "falkordb://localhost:6379"
    raw: dict[str, Any] = field(default_factory=lambda: {
        "graphiti": {
            "host_env": "TEST_FALKORDB_HOST",
            "port_env": "TEST_FALKORDB_PORT",
            "password_env": "TEST_FALKORDB_PASSWORD",
            "database": "test_graph",
        }
    })


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("TEST_FALKORDB_HOST", "localhost")
    monkeypatch.setenv("TEST_FALKORDB_PORT", "6379")
    monkeypatch.setenv("TEST_FALKORDB_PASSWORD", "testpass")


class TestCreateGraphitiClient:
    @patch("assistant.core.graphiti.Graphiti")
    @patch("assistant.core.graphiti.FalkorDriver")
    def test_creates_client_with_falkor_driver(self, mock_driver_cls, mock_graphiti_cls):
        mock_driver = MagicMock()
        mock_driver_cls.return_value = mock_driver
        mock_client = MagicMock()
        mock_graphiti_cls.return_value = mock_client

        persona = _FakePersona()
        result = create_graphiti_client(persona)

        assert result is mock_client
        mock_driver_cls.assert_called_once_with(
            host="localhost",
            port=6379,
            username="",
            password="testpass",
            database="test_graph",
        )
        mock_graphiti_cls.assert_called_once_with(driver=mock_driver)

    @patch("assistant.core.graphiti.Graphiti")
    @patch("assistant.core.graphiti.FalkorDriver")
    def test_caches_on_second_call(self, mock_driver_cls, mock_graphiti_cls):
        mock_graphiti_cls.return_value = MagicMock()
        persona = _FakePersona()

        client1 = create_graphiti_client(persona)
        client2 = create_graphiti_client(persona)
        assert client1 is client2
        assert mock_graphiti_cls.call_count == 1

    def test_returns_none_when_graphiti_url_empty(self):
        persona = _FakePersona(graphiti_url="")
        result = create_graphiti_client(persona)
        assert result is None

    @patch("assistant.core.graphiti.Graphiti")
    @patch("assistant.core.graphiti.FalkorDriver")
    def test_cache_cleared(self, mock_driver_cls, mock_graphiti_cls):
        mock_graphiti_cls.return_value = MagicMock()
        persona = _FakePersona()

        create_graphiti_client(persona)
        _clear_graphiti_cache()
        mock_graphiti_cls.return_value = MagicMock()
        client2 = create_graphiti_client(persona)
        assert mock_graphiti_cls.call_count == 2
        assert client2 is mock_graphiti_cls.return_value

    @patch("assistant.core.graphiti.Graphiti")
    @patch("assistant.core.graphiti.FalkorDriver")
    def test_defaults_database_to_persona_name(self, mock_driver_cls, mock_graphiti_cls):
        mock_graphiti_cls.return_value = MagicMock()
        persona = _FakePersona(
            name="personal",
            raw={"graphiti": {"host_env": "TEST_FALKORDB_HOST"}},
        )
        create_graphiti_client(persona)
        call_kwargs = mock_driver_cls.call_args[1]
        assert call_kwargs["database"] == "personal_graph"
