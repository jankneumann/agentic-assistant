"""Tests for harness-adapter spec.

Covers all 10 scenarios across 4 requirements in
``openspec/changes/bootstrap-vertical-slice/specs/harness-adapter/spec.md``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.extensions._stub import StubExtension
from assistant.harnesses.base import HarnessAdapter
from assistant.harnesses.deep_agents import DeepAgentsHarness
from assistant.harnesses.factory import create_harness
from assistant.harnesses.ms_agent_fw import MSAgentFrameworkHarness


def _persona(
    deep_enabled: bool = True,
    ms_enabled: bool = False,
    model: str = "anthropic:claude-sonnet-4-20250514",
) -> PersonaConfig:
    return PersonaConfig(
        name="p",
        display_name="P",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={
            "deep_agents": {"enabled": deep_enabled, "model": model},
            "ms_agent_framework": {"enabled": ms_enabled},
        },
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
    )


def _role() -> RoleConfig:
    return RoleConfig(
        name="r",
        display_name="R",
        description="",
        prompt="",
        delegation={"allowed_sub_roles": []},
    )


# ── Abstract Harness Adapter Contract ────────────────────────────────


def test_instantiating_abstract_class_raises() -> None:
    with pytest.raises(TypeError):
        HarnessAdapter(_persona(), _role())  # type: ignore[abstract]


def test_concrete_subclass_must_implement_all_methods() -> None:
    class Partial(HarnessAdapter):
        def name(self) -> str:
            return "partial"

    with pytest.raises(TypeError):
        Partial(_persona(), _role())  # type: ignore[abstract]


# ── Deep Agents Harness ──────────────────────────────────────────────


def test_harness_name_is_deep_agents() -> None:
    assert DeepAgentsHarness(_persona(), _role()).name() == "deep_agents"


def test_create_agent_uses_persona_configured_model() -> None:
    sentinel_model = MagicMock(name="model-handle")
    with patch(
        "assistant.harnesses.deep_agents.init_chat_model",
        return_value=sentinel_model,
    ) as init_mock, patch(
        "assistant.harnesses.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock(name="agent")
        h = DeepAgentsHarness(_persona(model="anthropic:claude-sonnet-x"), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        init_mock.assert_called_once_with("anthropic:claude-sonnet-x")
        kwargs = cda_mock.call_args.kwargs
        assert kwargs["model"] is sentinel_model


def test_create_agent_includes_extension_tools() -> None:
    tool_a = MagicMock(name="tool_a")
    tool_b = MagicMock(name="tool_b")

    class _Ext(StubExtension):
        def as_langchain_tools(self) -> list:
            return [tool_a]

    ext = _Ext("e", {})
    with patch(
        "assistant.harnesses.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h.create_agent(tools=[tool_b], extensions=[ext]))
        passed_tools = cda_mock.call_args.kwargs["tools"]
        assert tool_a in passed_tools
        assert tool_b in passed_tools


def test_invoke_returns_last_assistant_message_content() -> None:
    class _FakeAgent:
        async def ainvoke(self, payload):
            return {
                "messages": [
                    {"role": "user", "content": "q"},
                    {"role": "assistant", "content": "a"},
                ]
            }

    h = DeepAgentsHarness(_persona(), _role())
    result = asyncio.run(h.invoke(_FakeAgent(), "q"))
    assert result == "a"


# ── MS Agent Framework Harness Registered but Stubbed ───────────────


def test_factory_returns_ms_af_harness_for_enabled_persona() -> None:
    persona = _persona(deep_enabled=False, ms_enabled=True)
    harness = create_harness(persona, _role(), "ms_agent_framework")
    assert isinstance(harness, MSAgentFrameworkHarness)


def test_ms_af_create_agent_raises_not_implemented() -> None:
    h = MSAgentFrameworkHarness(_persona(ms_enabled=True), _role())
    with pytest.raises(NotImplementedError) as exc:
        asyncio.run(h.create_agent(tools=[], extensions=[]))
    # Message references deferred/later proposal
    msg = str(exc.value).lower()
    assert "p5" in msg or "later proposal" in msg or "deferred" in msg


# ── Harness Factory Validation ──────────────────────────────────────


def test_unknown_harness_name_raises() -> None:
    with pytest.raises(ValueError) as exc:
        create_harness(_persona(), _role(), "nonexistent")
    assert "Available:" in str(exc.value)


def test_disabled_harness_raises() -> None:
    persona = _persona(deep_enabled=False)
    with pytest.raises(ValueError) as exc:
        create_harness(persona, _role(), "deep_agents")
    assert "not enabled" in str(exc.value).lower()
