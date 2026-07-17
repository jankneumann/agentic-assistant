"""Tests for the Graphiti embeddings-binding wiring (P20 local-inference-node).

Covers the memory-policy delta "Embeddings Consumer Binding for
Graphiti": an explicit ``embeddings`` binding constructs the Graphiti
client with a ``RegistryEmbedder`` over the raw OpenAI-compatible
binding; no binding preserves the exact pre-P20 constructor call; an
unhonorable binding disables Graphiti instead of falling back to the
default cloud embedder; embedding dispatch stays budget-gated.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from assistant.core.capabilities.health import _reset_default_health_monitor
from assistant.core.capabilities.model_bindings import (
    ModelCallDeniedError,
    OpenAICompatibleClient,
)
from assistant.core.capabilities.models import (
    ModelRef,
    ModelRegistry,
    parse_model_registry,
)
from assistant.core.capabilities.types import ActionDecision, ActionRequest
from assistant.core.graphiti import (
    RegistryEmbedder,
    _clear_graphiti_cache,
    create_graphiti_client,
)


@pytest.fixture(autouse=True)
def _isolation(monkeypatch: pytest.MonkeyPatch):
    _clear_graphiti_cache()
    _reset_default_health_monitor()
    monkeypatch.setenv("TEST_FALKORDB_HOST", "localhost")
    yield
    _clear_graphiti_cache()
    _reset_default_health_monitor()


def _models_with_embeddings_binding(**entry_overrides: Any) -> ModelRegistry:
    entry: dict[str, Any] = {
        "dialect": "openai-compatible",
        "id": "nvidia/nv-embedqa-e5-v5",
        "endpoint": "http://gx10.local:8001/v1",
        "tags": ["cheap", "local-only", "private-data-ok"],
    }
    entry.update(entry_overrides)
    return parse_model_registry(
        {
            "entries": {"gx10-embed": entry},
            "bindings": {"embeddings": "gx10-embed"},
        }
    )


@dataclass
class _FakePersona:
    name: str = "test"
    graphiti_url: str = "falkordb://localhost:6379"
    models: ModelRegistry = field(default_factory=ModelRegistry)
    raw: dict[str, Any] = field(
        default_factory=lambda: {
            "graphiti": {"host_env": "TEST_FALKORDB_HOST", "database": "test_graph"}
        }
    )


# ── create_graphiti_client wiring ────────────────────────────────────


@patch("assistant.core.graphiti.Graphiti")
@patch("assistant.core.graphiti.FalkorDriver")
def test_embeddings_binding_selects_registry_embedder(
    mock_driver_cls: MagicMock, mock_graphiti_cls: MagicMock
) -> None:
    persona = _FakePersona(models=_models_with_embeddings_binding())
    client = create_graphiti_client(persona)

    assert client is mock_graphiti_cls.return_value
    kwargs = mock_graphiti_cls.call_args.kwargs
    assert isinstance(kwargs["embedder"], RegistryEmbedder)


@patch("assistant.core.graphiti.Graphiti")
@patch("assistant.core.graphiti.FalkorDriver")
def test_no_embeddings_binding_preserves_default_constructor_call(
    mock_driver_cls: MagicMock, mock_graphiti_cls: MagicMock
) -> None:
    registry = parse_model_registry(
        {
            "entries": {
                "sonnet": {"dialect": "anthropic", "id": "claude-sonnet-4"}
            },
            "bindings": {"default": "sonnet"},
        }
    )
    persona = _FakePersona(models=registry)
    create_graphiti_client(persona)
    mock_graphiti_cls.assert_called_once_with(
        graph_driver=mock_driver_cls.return_value
    )


@patch("assistant.core.graphiti.Graphiti")
@patch("assistant.core.graphiti.FalkorDriver")
def test_default_binding_does_not_activate_embeddings_wiring(
    mock_driver_cls: MagicMock, mock_graphiti_cls: MagicMock
) -> None:
    """The reserved `default` binding never spills into embeddings."""
    registry = parse_model_registry(
        {
            "entries": {
                "local": {
                    "dialect": "openai-compatible",
                    "endpoint": "http://gx10.local:8000/v1",
                }
            },
            "bindings": {"default": "local"},
        }
    )
    persona = _FakePersona(models=registry)
    create_graphiti_client(persona)
    assert "embedder" not in mock_graphiti_cls.call_args.kwargs


@patch("assistant.core.graphiti.Graphiti")
@patch("assistant.core.graphiti.FalkorDriver")
def test_unhonorable_binding_disables_graphiti_with_warning(
    mock_driver_cls: MagicMock,
    mock_graphiti_cls: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-openai-compatible embeddings target → None, never cloud."""
    registry = parse_model_registry(
        {
            "entries": {
                "cloud-embed": {"dialect": "gemini", "id": "text-embedding-004"}
            },
            "bindings": {"embeddings": "cloud-embed"},
        }
    )
    persona = _FakePersona(models=registry)
    with caplog.at_level(logging.WARNING):
        assert create_graphiti_client(persona) is None
    assert "test" in caplog.text
    assert "embeddings" in caplog.text
    mock_graphiti_cls.assert_not_called()


@patch("assistant.core.graphiti.Graphiti")
@patch("assistant.core.graphiti.FalkorDriver")
def test_unhealthy_embeddings_endpoint_fails_closed_to_none(
    mock_driver_cls: MagicMock,
    mock_graphiti_cls: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Health-aware resolution: a fresh unhealthy verdict on the only
    private embeddings entry disables Graphiti (no cloud fallback)."""
    from assistant.core.capabilities.health import default_health_monitor

    persona = _FakePersona(
        models=_models_with_embeddings_binding(health={"path": "/models"})
    )
    default_health_monitor().record("gx10-embed", False)
    with caplog.at_level(logging.WARNING):
        assert create_graphiti_client(persona) is None
    mock_graphiti_cls.assert_not_called()


# ── RegistryEmbedder wire shape ──────────────────────────────────────


def _embed_ref() -> ModelRef:
    return ModelRef(
        name="gx10-embed",
        dialect="openai-compatible",
        model_id="nvidia/nv-embedqa-e5-v5",
        endpoint="http://gx10.local:8001/v1",
    )


def _capture_client(
    seen: list[httpx.Request], dims: int = 8
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = json.loads(request.content)
        n = 1 if isinstance(payload["input"], str) else len(payload["input"])
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [float(i)] * dims, "index": i}
                    for i in range(n)
                ]
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_create_posts_to_embeddings_with_wire_model_id() -> None:
    seen: list[httpx.Request] = []
    async with _capture_client(seen) as http_client:
        client = OpenAICompatibleClient(_embed_ref(), http_client=http_client)
        embedder = RegistryEmbedder(client, embedding_dim=4)
        vector = await embedder.create("hello world")

    assert vector == [0.0, 0.0, 0.0, 0.0]  # truncated to embedding_dim
    (request,) = seen
    assert str(request.url) == "http://gx10.local:8001/v1/embeddings"
    payload = json.loads(request.content)
    assert payload["model"] == "nvidia/nv-embedqa-e5-v5"
    assert payload["input"] == "hello world"


async def test_create_batch_returns_one_vector_per_input() -> None:
    seen: list[httpx.Request] = []
    async with _capture_client(seen) as http_client:
        client = OpenAICompatibleClient(_embed_ref(), http_client=http_client)
        embedder = RegistryEmbedder(client, embedding_dim=2)
        vectors = await embedder.create_batch(["a", "b", "c"])

    assert vectors == [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]
    payload = json.loads(seen[0].content)
    assert payload["input"] == ["a", "b", "c"]


async def test_embedding_dispatch_is_budget_gated() -> None:
    class _DenyGuardrails:
        def check_action(self, action: ActionRequest) -> ActionDecision:
            return ActionDecision(allowed=False, reason="budget exceeded")

        def check_delegation(
            self, parent: str, sub: str, task: str
        ) -> ActionDecision:  # pragma: no cover
            return ActionDecision(allowed=True)

        def declare_risk(self, action: ActionRequest) -> Any:  # pragma: no cover
            return 1

    seen: list[httpx.Request] = []
    async with _capture_client(seen) as http_client:
        client = OpenAICompatibleClient(
            _embed_ref(), guardrails=_DenyGuardrails(), http_client=http_client
        )
        embedder = RegistryEmbedder(client, embedding_dim=4)
        with pytest.raises(ModelCallDeniedError, match="budget exceeded"):
            await embedder.create("private text")
    assert seen == []  # denial happened before the wire
