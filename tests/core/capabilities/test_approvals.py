"""Approval interrupt/resume semantics (P30 durable-sessions).

Covers the guardrail-provider ApprovalRequest contract: the
elicitation-shaped record, the InMemoryApprovalStore lifecycle
(first-decision-wins, consume-exactly-once, lazy expiry), the
``consume_or_suspend`` consult-resolved-then-recheck helper, and the
``check_model_call`` suspend-vs-deny-fallback split.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from assistant.core.capabilities.approvals import (
    DEFAULT_APPROVAL_SCHEMA,
    ApprovalAlreadyDecidedError,
    ApprovalDeniedError,
    ApprovalStore,
    InMemoryApprovalStore,
    PendingApprovalError,
    UnknownApprovalError,
    build_approval_request,
    consume_or_suspend,
)
from assistant.core.capabilities.guardrails import AllowAllGuardrails
from assistant.core.capabilities.model_bindings import (
    ModelCallDeniedError,
    check_model_call,
)
from assistant.core.capabilities.models import ModelRef
from assistant.core.capabilities.types import (
    ActionDecision,
    ActionRequest,
    RiskLevel,
)


def _action(
    action_type: str = "model_call",
    resource: str = "expensive-opus",
    persona: str = "fixture",
) -> ActionRequest:
    return ActionRequest(
        action_type=action_type,
        resource=resource,
        persona=persona,
        role="coder",
    )


def _decision() -> ActionDecision:
    return ActionDecision(
        allowed=True, reason="policy wants a human", require_confirmation=True
    )


class TestApprovalRequestShape:
    def test_all_fields_accessible(self):
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.HIGH, thread_id="t1"
        )
        assert request.approval_id
        assert "expensive-opus" in request.message
        assert request.action.action_type == "model_call"
        assert request.risk is RiskLevel.HIGH
        assert request.thread_id == "t1"
        assert request.status == "pending"
        assert request.created_at.tzinfo is not None

    def test_default_schema_is_approve_deny_plus_justification(self):
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.LOW
        )
        schema = request.requested_schema
        assert schema == DEFAULT_APPROVAL_SCHEMA
        assert schema is not DEFAULT_APPROVAL_SCHEMA  # deep-copied
        assert schema["properties"]["approve"]["type"] == "boolean"
        assert schema["properties"]["justification"]["type"] == "string"
        assert schema["required"] == ["approve"]

    def test_expiry_window(self):
        request = build_approval_request(
            _action(),
            _decision(),
            risk=RiskLevel.LOW,
            expiry_seconds=60,
            now=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )
        assert request.expires_at == datetime(2026, 7, 19, 12, 1, tzinfo=UTC)


class TestInMemoryApprovalStore:
    def test_satisfies_protocol(self):
        assert isinstance(InMemoryApprovalStore(), ApprovalStore)

    def test_create_get_roundtrip(self):
        store = InMemoryApprovalStore()
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.HIGH
        )
        store.create(request)
        loaded = store.get(request.approval_id)
        assert loaded is not None
        assert loaded.approval_id == request.approval_id
        assert loaded.status == "pending"

    def test_first_decision_wins(self):
        store = InMemoryApprovalStore()
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.HIGH
        )
        store.create(request)
        decided = store.decide(
            request.approval_id, approved=True, decided_by="human"
        )
        assert decided.status == "approved"
        assert decided.decided_by == "human"
        with pytest.raises(ApprovalAlreadyDecidedError):
            store.decide(request.approval_id, approved=False)

    def test_unknown_approval_raises(self):
        with pytest.raises(UnknownApprovalError):
            InMemoryApprovalStore().decide("nope", approved=True)

    def test_consume_exactly_once(self):
        store = InMemoryApprovalStore()
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.HIGH
        )
        store.create(request)
        store.decide(request.approval_id, approved=True)
        assert store.consume(request.approval_id) is True
        assert store.consume(request.approval_id) is False

    def test_pending_cannot_be_consumed(self):
        store = InMemoryApprovalStore()
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.LOW
        )
        store.create(request)
        assert store.consume(request.approval_id) is False

    def test_pending_expires_lazily(self):
        now = [datetime(2026, 7, 19, 12, 0, tzinfo=UTC)]
        store = InMemoryApprovalStore(now=lambda: now[0])
        request = build_approval_request(
            _action(),
            _decision(),
            risk=RiskLevel.LOW,
            expiry_seconds=30,
            now=now[0],
        )
        store.create(request)
        now[0] += timedelta(seconds=60)
        loaded = store.get(request.approval_id)
        assert loaded is not None and loaded.status == "expired"
        assert store.find_pending("fixture", "model_call", "expensive-opus") is None

    def test_list_filters_by_persona_and_status(self):
        store = InMemoryApprovalStore()
        a = build_approval_request(_action(), _decision(), risk=RiskLevel.LOW)
        b = build_approval_request(
            _action(persona="other"), _decision(), risk=RiskLevel.LOW
        )
        store.create(a)
        store.create(b)
        assert [r.approval_id for r in store.list_requests("fixture")] == [
            a.approval_id
        ]
        store.decide(a.approval_id, approved=False)
        assert store.list_requests("fixture", status="pending") == []
        assert (
            store.list_requests("fixture", status="denied")[0].approval_id
            == a.approval_id
        )


class TestConsumeOrSuspend:
    def test_first_call_creates_pending_and_suspends(self):
        store = InMemoryApprovalStore()
        with pytest.raises(PendingApprovalError) as exc:
            consume_or_suspend(
                store, _action(), _decision(), risk=RiskLevel.HIGH,
                thread_id="t9",
            )
        assert "assistant approvals approve" in str(exc.value)
        pending = store.find_pending("fixture", "model_call", "expensive-opus")
        assert pending is not None
        assert pending.approval_id == exc.value.approval_id
        assert pending.thread_id == "t9"

    def test_retry_reuses_the_same_pending_request(self):
        store = InMemoryApprovalStore()
        with pytest.raises(PendingApprovalError) as first:
            consume_or_suspend(
                store, _action(), _decision(), risk=RiskLevel.HIGH
            )
        with pytest.raises(PendingApprovalError) as second:
            consume_or_suspend(
                store, _action(), _decision(), risk=RiskLevel.HIGH
            )
        assert first.value.approval_id == second.value.approval_id
        assert len(store.list_requests("fixture")) == 1

    def test_approved_decision_is_consumed_exactly_once(self):
        store = InMemoryApprovalStore()
        with pytest.raises(PendingApprovalError) as exc:
            consume_or_suspend(
                store, _action(), _decision(), risk=RiskLevel.HIGH
            )
        store.decide(exc.value.approval_id, approved=True)
        # Retry proceeds (returns the consumed record).
        consumed = consume_or_suspend(
            store, _action(), _decision(), risk=RiskLevel.HIGH
        )
        assert consumed is not None
        assert consumed.approval_id == exc.value.approval_id
        record = store.get(exc.value.approval_id)
        assert record is not None and record.status == "consumed"
        # A THIRD attempt re-suspends with a FRESH request — the
        # approval was consumed, not left open.
        with pytest.raises(PendingApprovalError) as again:
            consume_or_suspend(
                store, _action(), _decision(), risk=RiskLevel.HIGH
            )
        assert again.value.approval_id != exc.value.approval_id

    def test_denied_decision_surfaces_and_is_consumed(self):
        store = InMemoryApprovalStore()
        with pytest.raises(PendingApprovalError) as exc:
            consume_or_suspend(
                store, _action(), _decision(), risk=RiskLevel.HIGH
            )
        store.decide(
            exc.value.approval_id, approved=False, justification="too costly"
        )
        with pytest.raises(ApprovalDeniedError) as denied:
            consume_or_suspend(
                store, _action(), _decision(), risk=RiskLevel.HIGH
            )
        assert "too costly" in str(denied.value)
        record = store.get(exc.value.approval_id)
        assert record is not None and record.status == "consumed"


class _ConfirmGuardrails(AllowAllGuardrails):
    """require_confirmation for every action; HIGH risk."""

    def check_action(self, action: ActionRequest) -> ActionDecision:
        return ActionDecision(
            allowed=True, reason="confirm", require_confirmation=True
        )

    def declare_risk(self, action: ActionRequest) -> RiskLevel:
        return RiskLevel.HIGH


class TestCheckModelCallApprovalPath:
    def _ref(self) -> ModelRef:
        return ModelRef(name="expensive-opus", dialect="anthropic", model_id="opus")

    def test_without_store_preserves_deny_fallback(self):
        with pytest.raises(ModelCallDeniedError) as exc:
            check_model_call(
                _ConfirmGuardrails(), self._ref(), persona="fixture",
                role="coder",
            )
        assert "requires confirmation" in str(exc.value)

    def test_with_store_suspends_then_resumes_after_approval(self):
        store = InMemoryApprovalStore()
        with pytest.raises(PendingApprovalError) as exc:
            check_model_call(
                _ConfirmGuardrails(),
                self._ref(),
                persona="fixture",
                role="coder",
                approvals=store,
                thread_id="t1",
            )
        pending = store.get(exc.value.approval_id)
        assert pending is not None
        assert pending.risk is RiskLevel.HIGH
        assert pending.thread_id == "t1"
        store.decide(exc.value.approval_id, approved=True, decided_by="human")
        # Retry proceeds without raising; the approval is consumed once.
        check_model_call(
            _ConfirmGuardrails(),
            self._ref(),
            persona="fixture",
            role="coder",
            approvals=store,
            thread_id="t1",
        )
        record = store.get(exc.value.approval_id)
        assert record is not None and record.status == "consumed"

    def test_with_store_human_deny_surfaces(self):
        store = InMemoryApprovalStore()
        with pytest.raises(PendingApprovalError) as exc:
            check_model_call(
                _ConfirmGuardrails(),
                self._ref(),
                persona="fixture",
                role="coder",
                approvals=store,
            )
        store.decide(exc.value.approval_id, approved=False)
        with pytest.raises(ApprovalDeniedError):
            check_model_call(
                _ConfirmGuardrails(),
                self._ref(),
                persona="fixture",
                role="coder",
                approvals=store,
            )
