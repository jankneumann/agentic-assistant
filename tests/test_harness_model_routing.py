"""Harness integration tests for model-provider-routing (P19).

Both SDK harnesses consume ``CapabilitySet.models`` + a per-consumer
binding; the persona ``models:`` registry is the only model-selection
mechanism (owner review verdict #3 — registry-only). These tests
cover the registry-backed path (with and without consumer bindings),
the synthesized default registry when ``models:`` is absent,
fallback-chain binding, budget-hook denial, and cost attribution on
the emitted spans.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from assistant.core.capabilities.model_bindings import ModelCallDeniedError
from assistant.core.capabilities.models import (
    ModelRef,
    ModelRequest,
    parse_model_registry,
)
from assistant.core.capabilities.types import ActionDecision, ActionRequest
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.sdk.deep_agents import DeepAgentsHarness
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness


def _persona(models_raw: dict | None = None) -> PersonaConfig:
    return PersonaConfig(
        name="p",
        display_name="P",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={
            "deep_agents": {"enabled": True},
            "ms_agent_framework": {"enabled": True},
        },
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
        models=parse_model_registry(models_raw or {}),
    )


def _role() -> RoleConfig:
    return RoleConfig(
        name="r",
        display_name="R",
        description="",
        prompt="test prompt",
        delegation={"allowed_sub_roles": []},
    )


_REGISTRY = {
    "entries": {
        "sonnet": {
            "dialect": "anthropic",
            "id": "claude-sonnet-4-20250514",
            "credential_ref": "ANTHROPIC_API_KEY",
            "tags": ["coding", "long-context"],
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "fallbacks": ["local-fast"],
        },
        "local-fast": {
            "dialect": "openai-compatible",
            "id": "llama-3.1-8b-instruct",
            "endpoint": "http://gx10.local:8000/v1",
            "tags": ["fast", "cheap"],
        },
    }
}


class _DenyGuardrails:
    def check_action(self, action: ActionRequest) -> ActionDecision:
        return ActionDecision(allowed=False, reason="budget exceeded")

    def check_delegation(self, parent: str, sub: str, task: str) -> ActionDecision:
        return ActionDecision(allowed=True)

    def declare_risk(self, action: ActionRequest) -> Any:
        return 1


# ── DeepAgents ───────────────────────────────────────────────────────


def test_deep_agents_registry_persona_binds_registry_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(name="model-handle"),
    ) as init_mock, patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(_REGISTRY), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        init_mock.assert_called_once_with(
            "anthropic:claude-sonnet-4-20250514", api_key="sk-ant"
        )
    # span-facing state follows the resolved ref, not the raw config
    assert h._active_model == "claude-sonnet-4-20250514"
    assert h._active_model_ref is not None
    assert h._active_model_ref.name == "sonnet"


def test_deep_agents_no_registry_uses_synthesized_default() -> None:
    """Persona without ``models:``: the synthesized default registry
    binds this harness to its default entry, preserving the exact
    single-argument ``init_chat_model`` call."""
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ) as init_mock, patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        init_mock.assert_called_once_with("anthropic:claude-sonnet-4-20250514")
    assert h._active_model == "anthropic:claude-sonnet-4-20250514"
    assert h._active_model_ref is not None
    assert h._active_model_ref.dialect == "anthropic"


def test_deep_agents_consumer_binding_selects_bound_entry() -> None:
    """A ``bindings:`` map routes each harness to its own entry — the
    DeepAgents consumer binding wins over declaration order."""
    registry = {
        "entries": dict(_REGISTRY["entries"]),
        "bindings": {"deep_agents": "local-fast", "default": "sonnet"},
    }
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ) as init_mock, patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(registry), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        init_mock.assert_called_once_with(
            "openai:llama-3.1-8b-instruct",
            base_url="http://gx10.local:8000/v1",
        )
    assert h._active_model_ref is not None
    assert h._active_model_ref.name == "local-fast"


def test_deep_agents_falls_back_when_primary_binding_fails() -> None:
    calls: list[str] = []

    def _failing_init(model: str, **kwargs: Any) -> Any:
        calls.append(model)
        if model.startswith("anthropic:"):
            raise RuntimeError("anthropic connector unavailable")
        return MagicMock(name="fallback-model")

    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        side_effect=_failing_init,
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(_REGISTRY), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
    assert calls == [
        "anthropic:claude-sonnet-4-20250514",
        "openai:llama-3.1-8b-instruct",
    ]
    assert h._active_model_ref is not None
    assert h._active_model_ref.name == "local-fast"


def test_deep_agents_guardrail_denial_stops_before_model_construction() -> None:
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model"
    ) as init_mock, patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ):
        h = DeepAgentsHarness(
            _persona(_REGISTRY), _role(), guardrail_provider=_DenyGuardrails()
        )
        with pytest.raises(ModelCallDeniedError, match="budget exceeded"):
            asyncio.run(h.create_agent(tools=[], extensions=[]))
        init_mock.assert_not_called()


def test_deep_agents_injected_model_provider_wins() -> None:
    class _OneRefProvider:
        def resolve(self, request: ModelRequest) -> list[ModelRef]:
            return [
                ModelRef(
                    name="injected",
                    dialect="openai-compatible",
                    model_id="openai:injected-model",
                )
            ]

        def list_models(self) -> list[ModelRef]:
            return self.resolve(ModelRequest())

    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ) as init_mock, patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(
            _persona(), _role(), model_provider=_OneRefProvider()
        )
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        init_mock.assert_called_once_with("openai:injected-model")


# ── MSAF ─────────────────────────────────────────────────────────────


def test_msaf_registry_persona_binds_openai_compatible_ref() -> None:
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    registry = {
        "entries": {
            "router": {
                "dialect": "openai-compatible",
                "id": "openai/gpt-4o",
                "endpoint": "https://openrouter.ai/api/v1",
            }
        }
    }
    h = MSAgentFrameworkHarness(_persona(registry), _role())
    with patch(
        "agent_framework.openai.OpenAIChatClient", new=_FakeClient, create=True
    ):
        client = h._build_chat_client()
    assert isinstance(client, _FakeClient)
    assert captured == {
        "model_id": "openai/gpt-4o",
        "base_url": "https://openrouter.ai/api/v1",
    }
    assert h._active_model == "openai/gpt-4o"
    assert h._active_model_ref is not None
    assert h._active_model_ref.name == "router"


def test_msaf_registry_skips_unbindable_dialect_to_fallback() -> None:
    """An anthropic ref cannot bind to the MSAF client; the chain's
    openai-compatible fallback must be used instead."""
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    h = MSAgentFrameworkHarness(_persona(_REGISTRY), _role())
    with patch(
        "agent_framework.openai.OpenAIChatClient", new=_FakeClient, create=True
    ):
        h._build_chat_client()
    assert captured["model_id"] == "llama-3.1-8b-instruct"
    assert h._active_model_ref is not None
    assert h._active_model_ref.name == "local-fast"


def test_msaf_consumer_binding_selects_bound_entry() -> None:
    """The MSAF consumer binding routes to its own entry independently
    of the DeepAgents binding."""
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    registry = {
        "entries": dict(_REGISTRY["entries"]),
        "bindings": {"ms_agent_framework": "local-fast", "default": "sonnet"},
    }
    h = MSAgentFrameworkHarness(_persona(registry), _role())
    with patch(
        "agent_framework.openai.OpenAIChatClient", new=_FakeClient, create=True
    ):
        h._build_chat_client()
    assert captured == {
        "model_id": "llama-3.1-8b-instruct",
        "base_url": "http://gx10.local:8000/v1",
    }
    assert h._active_model_ref is not None
    assert h._active_model_ref.name == "local-fast"


def test_msaf_guardrail_denial_propagates() -> None:
    h = MSAgentFrameworkHarness(
        _persona(_REGISTRY), _role(), guardrail_provider=_DenyGuardrails()
    )
    with pytest.raises(ModelCallDeniedError, match="budget exceeded"):
        h._build_chat_client()


def test_msaf_synthesized_default_uses_gpt4o_model_id() -> None:
    """No registry: the synthesized default ('openai:gpt-4o') flows
    through the binding with the provider prefix stripped."""
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    h = MSAgentFrameworkHarness(_persona(), _role())
    with patch(
        "agent_framework.openai.OpenAIChatClient", new=_FakeClient, create=True
    ):
        h._build_chat_client()
    assert captured == {"model_id": "gpt-4o"}
    assert h._active_model == "openai:gpt-4o"


# ── Cost attribution through @traced_harness ─────────────────────────


class _SpyProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def trace_llm_call(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    def __getattr__(self, name: str) -> Any:  # other trace_* methods
        return lambda *a, **k: None


def test_invoke_span_carries_model_identity_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant.telemetry import factory

    spy = _SpyProvider()
    monkeypatch.setattr(factory, "_provider", spy)

    class _FakeAgent:
        async def ainvoke(self, payload: Any, config: Any = None) -> Any:
            return {"messages": [{"role": "assistant", "content": "ok"}]}

    h = DeepAgentsHarness(_persona(), _role())
    h._active_model = "sonnet"
    h._active_model_ref = ModelRef(
        name="sonnet",
        dialect="anthropic",
        pricing={"prompt": "0.000003", "completion": "0.000015"},
    )
    asyncio.run(h.invoke(_FakeAgent(), "q"))

    (call,) = spy.calls
    assert call["model"] == "sonnet"
    meta = call["metadata"]
    assert meta["model_ref"] == "sonnet"
    assert meta["model_dialect"] == "anthropic"
    # No LLM tokens flowed through the fake agent → computed cost is 0.0
    assert meta["cost_usd"] == pytest.approx(0.0)


def test_invoke_span_omits_cost_when_pricing_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local endpoints have no pricing — identity is emitted, cost is
    omitted, never guessed."""
    from assistant.telemetry import factory

    spy = _SpyProvider()
    monkeypatch.setattr(factory, "_provider", spy)

    class _FakeAgent:
        async def ainvoke(self, payload: Any, config: Any = None) -> Any:
            return {"messages": [{"role": "assistant", "content": "ok"}]}

    h = DeepAgentsHarness(_persona(), _role())
    h._active_model_ref = ModelRef(
        name="local-fast", dialect="openai-compatible"
    )
    asyncio.run(h.invoke(_FakeAgent(), "q"))

    (call,) = spy.calls
    meta = call["metadata"]
    assert meta["model_ref"] == "local-fast"
    assert "cost_usd" not in meta


def test_invoke_span_unchanged_without_active_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant.telemetry import factory

    spy = _SpyProvider()
    monkeypatch.setattr(factory, "_provider", spy)

    class _FakeAgent:
        async def ainvoke(self, payload: Any, config: Any = None) -> Any:
            return {"messages": [{"role": "assistant", "content": "ok"}]}

    h = DeepAgentsHarness(_persona(), _role())
    assert h._active_model_ref is None
    asyncio.run(h.invoke(_FakeAgent(), "q"))

    (call,) = spy.calls
    assert call["metadata"] is None  # pre-P19 span shape preserved
