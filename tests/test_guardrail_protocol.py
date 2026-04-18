"""Tests for GuardrailProvider protocol — Task 1.3.

Covers: protocol conformance, AllowAllGuardrails stub behavior.
"""

from __future__ import annotations


def test_stub_satisfies_protocol() -> None:
    from assistant.core.capabilities.guardrails import AllowAllGuardrails, GuardrailProvider

    assert isinstance(AllowAllGuardrails(), GuardrailProvider)


def test_non_conforming_class_rejected() -> None:
    from assistant.core.capabilities.guardrails import GuardrailProvider

    class Incomplete:
        def check_action(self, action):  # type: ignore[no-untyped-def]
            pass

    assert not isinstance(Incomplete(), GuardrailProvider)


def test_stub_allows_all_actions() -> None:
    from assistant.core.capabilities.guardrails import AllowAllGuardrails
    from assistant.core.capabilities.types import ActionRequest

    stub = AllowAllGuardrails()
    req = ActionRequest(
        action_type="tool_call",
        resource="gmail.send",
        persona="personal",
        role="chief_of_staff",
    )
    decision = stub.check_action(req)
    assert decision.allowed is True


def test_stub_allows_all_delegations() -> None:
    from assistant.core.capabilities.guardrails import AllowAllGuardrails

    stub = AllowAllGuardrails()
    decision = stub.check_delegation("chief_of_staff", "writer", "draft email")
    assert decision.allowed is True


def test_stub_declares_low_risk() -> None:
    from assistant.core.capabilities.guardrails import AllowAllGuardrails
    from assistant.core.capabilities.types import ActionRequest, RiskLevel

    stub = AllowAllGuardrails()
    req = ActionRequest(
        action_type="tool_call",
        resource="anything",
        persona="personal",
        role="researcher",
    )
    assert stub.declare_risk(req) == RiskLevel.LOW
