"""AgentIdentity principal + guardrail audit trail (agent-iam / P25).

Spec: openspec/changes/agent-iam/specs/agent-identity/spec.md.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from assistant.core.capabilities.audit import (
    GUARDRAIL_AUDIT_SPAN,
    decision_outcome,
    emit_guardrail_audit,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.types import ActionDecision, ActionRequest
from assistant.telemetry import factory

# ── AgentIdentity value object ─────────────────────────────────────────


def test_identity_fields_and_defaults():
    identity = AgentIdentity(persona="fixture", role="chief_of_staff")
    assert identity.persona == "fixture"
    assert identity.role == "chief_of_staff"
    assert identity.delegation_chain == ()
    assert identity.session_id == ""
    assert identity.chain_depth == 0
    assert identity.issued_at.tzinfo is UTC


def test_identity_is_immutable():
    identity = AgentIdentity(persona="fixture", role="coder")
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.role = "writer"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.delegation_chain = ("x",)  # type: ignore[misc]


def test_delegate_to_extends_chain_and_preserves_persona_session():
    root = AgentIdentity(
        persona="fixture", role="chief_of_staff", session_id="thread-1"
    )
    child = root.delegate_to("researcher")
    grandchild = child.delegate_to("writer")

    assert child.persona == "fixture"
    assert child.role == "researcher"
    assert child.delegation_chain == ("chief_of_staff",)
    assert child.session_id == "thread-1"
    assert child.chain_depth == 1

    assert grandchild.delegation_chain == ("chief_of_staff", "researcher")
    assert grandchild.chain_depth == 2
    # The parent is untouched — extension always builds a new principal.
    assert root.delegation_chain == ()


def test_delegate_to_issues_fresh_timestamp():
    root = AgentIdentity(
        persona="fixture",
        role="root",
        issued_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    child = root.delegate_to("coder")
    assert child.issued_at > root.issued_at


def test_chain_display_is_root_first():
    identity = AgentIdentity(
        persona="p", role="writer", delegation_chain=("root", "coder")
    )
    assert identity.chain_display() == "root -> coder -> writer"


# ── ActionRequest attachment ───────────────────────────────────────────


def test_action_request_identity_defaults_to_none():
    request = ActionRequest(
        action_type="tool_call", resource="x", persona="p", role="r"
    )
    assert request.identity is None


def test_action_request_carries_identity():
    identity = AgentIdentity(persona="p", role="r")
    request = ActionRequest(
        action_type="tool_call",
        resource="x",
        persona="p",
        role="r",
        identity=identity,
    )
    assert request.identity is identity


# ── Audit records ──────────────────────────────────────────────────────


class _SpanSpy:
    def __init__(self) -> None:
        self.name = "spy"
        self.spans: list[tuple[str, dict]] = []

    def start_span(self, name, attributes=None):
        self.spans.append((name, dict(attributes or {})))
        from contextlib import nullcontext

        return nullcontext()


@pytest.fixture
def span_spy(monkeypatch: pytest.MonkeyPatch) -> _SpanSpy:
    spy = _SpanSpy()
    monkeypatch.setattr(factory, "_provider", spy)
    return spy


def _request_with_identity() -> ActionRequest:
    identity = AgentIdentity(
        persona="fixture",
        role="researcher",
        delegation_chain=("chief_of_staff",),
        session_id="thread-9",
        issued_at=datetime(2026, 7, 17, tzinfo=UTC),
    )
    return ActionRequest(
        action_type="delegation",
        resource="writer",
        persona="fixture",
        role="researcher",
        identity=identity,
    )


def test_decision_outcome_vocabulary():
    assert decision_outcome(ActionDecision(allowed=True)) == "allow"
    assert decision_outcome(ActionDecision(allowed=False)) == "deny"
    assert (
        decision_outcome(
            ActionDecision(allowed=True, require_confirmation=True)
        )
        == "require_confirmation"
    )


def test_audit_record_emitted_with_full_identity_attributes(span_spy):
    emit_guardrail_audit(
        _request_with_identity(),
        ActionDecision(allowed=False, reason="chain too deep"),
    )
    assert len(span_spy.spans) == 1
    name, attrs = span_spy.spans[0]
    assert name == GUARDRAIL_AUDIT_SPAN
    assert attrs["action_type"] == "delegation"
    assert attrs["resource"] == "writer"
    assert attrs["persona"] == "fixture"
    assert attrs["role"] == "researcher"
    assert attrs["delegation_chain"] == ["chief_of_staff"]
    assert attrs["chain_depth"] == 1
    assert attrs["session_id"] == "thread-9"
    assert attrs["issued_at"].startswith("2026-07-17")
    assert attrs["decision"] == "deny"
    assert attrs["reason"] == "chain too deep"


def test_audit_skipped_without_identity(span_spy):
    emit_guardrail_audit(
        ActionRequest(
            action_type="model_call", resource="m", persona="p", role="r"
        ),
        ActionDecision(allowed=True),
    )
    assert span_spy.spans == []


def test_check_model_call_synthesizes_identity_and_audits(span_spy):
    from assistant.core.capabilities.guardrails import AllowAllGuardrails
    from assistant.core.capabilities.model_bindings import check_model_call
    from assistant.core.capabilities.models import ModelRef

    ref = ModelRef(name="sonnet", dialect="anthropic", model_id="claude-x")
    check_model_call(
        AllowAllGuardrails(), ref, persona="fixture", role="coder"
    )
    assert len(span_spy.spans) == 1
    _, attrs = span_spy.spans[0]
    assert attrs["action_type"] == "model_call"
    assert attrs["resource"] == "sonnet"
    assert attrs["persona"] == "fixture"
    assert attrs["role"] == "coder"
    assert attrs["delegation_chain"] == []
    assert attrs["decision"] == "allow"


def test_check_model_call_prefers_injected_identity(span_spy):
    from assistant.core.capabilities.guardrails import AllowAllGuardrails
    from assistant.core.capabilities.model_bindings import check_model_call
    from assistant.core.capabilities.models import ModelRef

    identity = AgentIdentity(
        persona="fixture",
        role="writer",
        delegation_chain=("chief_of_staff",),
        session_id="t-1",
    )
    ref = ModelRef(name="sonnet", dialect="anthropic", model_id="claude-x")
    check_model_call(
        AllowAllGuardrails(),
        ref,
        persona="fixture",
        role="writer",
        identity=identity,
    )
    _, attrs = span_spy.spans[0]
    assert attrs["delegation_chain"] == ["chief_of_staff"]
    assert attrs["session_id"] == "t-1"


def test_audit_failure_never_breaks_the_caller(monkeypatch):
    class _Broken:
        def start_span(self, name, attributes=None):
            raise RuntimeError("telemetry down")

    monkeypatch.setattr(factory, "_provider", _Broken())
    # Must not raise.
    emit_guardrail_audit(
        _request_with_identity(), ActionDecision(allowed=True)
    )
