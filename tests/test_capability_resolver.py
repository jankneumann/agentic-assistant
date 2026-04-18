"""Tests for CapabilityResolver — Task 2.1.

Covers: SDK vs host resolution, custom factory injection, defaults.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _make_persona(harnesses: dict | None = None) -> MagicMock:
    persona = MagicMock()
    persona.harnesses = harnesses or {"deep_agents": {"enabled": True}}
    persona.memory_content = ""
    persona.extensions = []
    persona.tool_sources = {}
    return persona


def _make_role() -> MagicMock:
    role = MagicMock()
    role.preferred_tools = []
    return role


def test_sdk_resolves_concrete_providers() -> None:
    from assistant.core.capabilities.guardrails import AllowAllGuardrails
    from assistant.core.capabilities.memory import FileMemoryPolicy
    from assistant.core.capabilities.resolver import CapabilityResolver
    from assistant.core.capabilities.sandbox import PassthroughSandbox
    from assistant.core.capabilities.tools import DefaultToolPolicy

    resolver = CapabilityResolver()
    cs = resolver.resolve(_make_persona(), "sdk", _make_role())

    assert isinstance(cs.guardrails, AllowAllGuardrails)
    assert isinstance(cs.sandbox, PassthroughSandbox)
    assert isinstance(cs.memory, FileMemoryPolicy)
    assert isinstance(cs.tools, DefaultToolPolicy)


def test_host_marks_host_provided() -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    resolver = CapabilityResolver()
    persona = _make_persona()
    cs = resolver.resolve(persona, "host", _make_role())

    mem_cfg = cs.memory.resolve(persona, "claude_code")
    assert mem_cfg.backend_type == "host_provided"

    sandbox_ctx = cs.sandbox.create_context(
        __import__("assistant.core.capabilities.types", fromlist=["SandboxConfig"]).SandboxConfig()
    )
    assert sandbox_ctx.isolation_type == "host_provided"


def test_custom_guardrail_injected() -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver
    from assistant.core.capabilities.types import ActionDecision, ActionRequest, RiskLevel

    class CustomGuardrails:
        def check_action(self, action: ActionRequest) -> ActionDecision:
            return ActionDecision(allowed=False, reason="custom")

        def check_delegation(self, parent: str, sub: str, task: str) -> ActionDecision:
            return ActionDecision(allowed=False, reason="custom")

        def declare_risk(self, action: ActionRequest) -> RiskLevel:
            return RiskLevel.HIGH

    custom = CustomGuardrails()
    resolver = CapabilityResolver(guardrail_factory=lambda: custom)
    cs = resolver.resolve(_make_persona(), "sdk", _make_role())
    assert cs.guardrails is custom


def test_unset_overrides_use_defaults() -> None:
    from assistant.core.capabilities.guardrails import AllowAllGuardrails
    from assistant.core.capabilities.resolver import CapabilityResolver

    resolver = CapabilityResolver()
    cs = resolver.resolve(_make_persona(), "sdk", _make_role())
    assert isinstance(cs.guardrails, AllowAllGuardrails)
