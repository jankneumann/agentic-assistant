"""CLI tests for the P30 `assistant approvals` command group.

The durable store resolution is patched at its source module (gotcha
G4) with the in-memory fakes; personas come from the public fixture
root.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from assistant.cli import main
from assistant.core import durable
from assistant.core.capabilities.approvals import (
    InMemoryApprovalStore,
    build_approval_request,
)
from assistant.core.capabilities.types import (
    ActionDecision,
    ActionRequest,
    RiskLevel,
)
from assistant.core.durable import (
    DurableStores,
    InMemoryAuditStore,
    InMemorySessionStore,
    SessionsConfig,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _clean_durable_state():
    durable._clear_durable_state()
    yield
    durable._clear_durable_state()


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> DurableStores:
    approval_store = InMemoryApprovalStore()
    fake = DurableStores(
        persona="learning_lab",
        config=SessionsConfig(durable=True),
        sessions=InMemorySessionStore(),
        approvals=approval_store,
        audit=InMemoryAuditStore(),
    )
    monkeypatch.setattr(
        "assistant.core.durable.durable_stores_for", lambda pc: fake
    )
    durable.register_audit_sink("learning_lab", fake.audit)
    return fake


def _pending(store: InMemoryApprovalStore, resource: str = "opus") -> str:
    request = build_approval_request(
        ActionRequest(
            action_type="model_call",
            resource=resource,
            persona="learning_lab",
            role="coder",
        ),
        ActionDecision(
            allowed=True, reason="confirm", require_confirmation=True
        ),
        risk=RiskLevel.HIGH,
        thread_id="t1",
    )
    store.create(request)
    return request.approval_id


class TestApprovalsList:
    def test_lists_pending_approvals(self, runner, stores):
        approval_id = _pending(stores.approvals)
        result = runner.invoke(main, ["approvals", "list", "-p", "learning_lab"])
        assert result.exit_code == 0, result.output
        assert approval_id in result.output
        assert "model_call" in result.output
        assert "pending" in result.output

    def test_empty_store_prints_notice(self, runner, stores):
        result = runner.invoke(main, ["approvals", "list", "-p", "learning_lab"])
        assert result.exit_code == 0
        assert "No pending approvals" in result.output

    def test_all_flag_includes_decided(self, runner, stores):
        approval_id = _pending(stores.approvals)
        stores.approvals.decide(approval_id, approved=True)
        result = runner.invoke(main, ["approvals", "list", "-p", "learning_lab"])
        assert approval_id not in result.output
        result = runner.invoke(
            main, ["approvals", "list", "-p", "learning_lab", "--all"]
        )
        assert approval_id in result.output
        assert "approved" in result.output

    def test_without_durable_sessions_exits_1(self, runner):
        # No patching: the fixture persona declares no sessions section.
        result = runner.invoke(main, ["approvals", "list", "-p", "learning_lab"])
        assert result.exit_code == 1
        assert "durable" in result.output


class TestApprovalsDecide:
    def test_approve_records_decision_and_audit(self, runner, stores):
        approval_id = _pending(stores.approvals)
        result = runner.invoke(
            main,
            [
                "approvals",
                "approve",
                approval_id,
                "-p",
                "learning_lab",
                "--justification",
                "fine",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "approved" in result.output
        record = stores.approvals.get(approval_id)
        assert record is not None
        assert record.status == "approved"
        assert record.decided_by == "cli:learning_lab"
        assert record.justification == "fine"
        events = stores.audit.events
        assert any(
            e["event"] == "approval.decision" and e["decision"] == "approved"
            for e in events
        )

    def test_deny_records_decision(self, runner, stores):
        approval_id = _pending(stores.approvals)
        result = runner.invoke(
            main, ["approvals", "deny", approval_id, "-p", "learning_lab"]
        )
        assert result.exit_code == 0, result.output
        record = stores.approvals.get(approval_id)
        assert record is not None and record.status == "denied"

    def test_second_decision_is_rejected(self, runner, stores):
        approval_id = _pending(stores.approvals)
        first = runner.invoke(
            main, ["approvals", "approve", approval_id, "-p", "learning_lab"]
        )
        assert first.exit_code == 0
        second = runner.invoke(
            main, ["approvals", "deny", approval_id, "-p", "learning_lab"]
        )
        assert second.exit_code == 1
        assert "already" in second.output

    def test_unknown_approval_exits_1(self, runner, stores):
        result = runner.invoke(
            main, ["approvals", "approve", "nope", "-p", "learning_lab"]
        )
        assert result.exit_code == 1
        assert "unknown approval" in result.output
