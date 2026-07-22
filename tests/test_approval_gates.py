"""P30 approval flow through the P26 cleanroom and P28 learning gates.

``require_confirmation`` guardrail decisions on these paths now
suspend into the durable approval flow when an ApprovalStore is
supplied, and keep the P13 deny fallback otherwise. Stores are the
in-memory fake (semantics twin of the Postgres store).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assistant.core import cleanroom as cr
from assistant.core import learning as lrn
from assistant.core.capabilities.approvals import (
    ApprovalDeniedError,
    InMemoryApprovalStore,
    PendingApprovalError,
)
from assistant.core.capabilities.guardrails import (
    ActionPolicy,
    GuardrailConfig,
    PolicyGuardrails,
)
from tests.test_cleanroom import _seeded_manager
from tests.test_learning import FakeLearningStore, _gate, _persona


def _confirm_guardrails(action_type: str, persona: str) -> PolicyGuardrails:
    return PolicyGuardrails(
        GuardrailConfig(
            policies=[
                ActionPolicy(
                    action_type=action_type, effect="require_confirmation"
                )
            ]
        ),
        persona=persona,
    )


# ── Cleanroom export (P26 hook) ──────────────────────────────────────


class TestCleanroomApprovalPath:
    @pytest.fixture
    def alpha(self, personas_dir: Path):
        from assistant.core.persona import PersonaRegistry

        return PersonaRegistry(personas_dir).load("cleanroom_alpha")

    async def test_without_store_preserves_deny_fallback(
        self, alpha, tmp_path: Path
    ):
        with pytest.raises(cr.CleanRoomDenied, match="confirmation"):
            await cr.export_shared(
                alpha,
                "cleanroom_beta",
                _seeded_manager(),
                guardrails=_confirm_guardrails(
                    "cleanroom_export", "cleanroom_alpha"
                ),
                space_dir=tmp_path,
            )

    async def test_with_store_suspends_then_resumes_after_approval(
        self, alpha, tmp_path: Path
    ):
        store = InMemoryApprovalStore()
        guardrails = _confirm_guardrails(
            "cleanroom_export", "cleanroom_alpha"
        )
        with pytest.raises(PendingApprovalError) as exc:
            await cr.export_shared(
                alpha,
                "cleanroom_beta",
                _seeded_manager(),
                guardrails=guardrails,
                space_dir=tmp_path,
                approvals=store,
            )
        pending = store.get(exc.value.approval_id)
        assert pending is not None
        assert pending.action.action_type == "cleanroom_export"
        store.decide(exc.value.approval_id, approved=True, decided_by="human")
        result = await cr.export_shared(
            alpha,
            "cleanroom_beta",
            _seeded_manager(),
            guardrails=guardrails,
            space_dir=tmp_path,
            approvals=store,
        )
        assert result.item_count > 0
        record = store.get(exc.value.approval_id)
        assert record is not None and record.status == "consumed"

    async def test_with_store_human_deny_surfaces(self, alpha, tmp_path: Path):
        store = InMemoryApprovalStore()
        guardrails = _confirm_guardrails(
            "cleanroom_export", "cleanroom_alpha"
        )
        with pytest.raises(PendingApprovalError) as exc:
            await cr.export_shared(
                alpha,
                "cleanroom_beta",
                _seeded_manager(),
                guardrails=guardrails,
                space_dir=tmp_path,
                approvals=store,
            )
        store.decide(exc.value.approval_id, approved=False)
        with pytest.raises(ApprovalDeniedError):
            await cr.export_shared(
                alpha,
                "cleanroom_beta",
                _seeded_manager(),
                guardrails=guardrails,
                space_dir=tmp_path,
                approvals=store,
            )


# ── Learning apply (P28 hook) ────────────────────────────────────────


def _low_pref_proposal() -> lrn.ImprovementProposal:
    return lrn.ImprovementProposal(
        proposal_id="apprv1",
        kind="preference",
        target="preference:style/tone",
        content={"category": "style", "key": "tone", "value": "concise"},
        rationale="test",
        risk="LOW",
    )


class TestLearningApplyApprovalPath:
    async def test_without_store_preserves_deny_fallback(self, tmp_path: Path):
        pc = _persona(tmp_path)
        with pytest.raises(lrn.LearningDenied, match="confirmation"):
            await lrn.apply_proposal(
                pc,
                _low_pref_proposal(),
                FakeLearningStore(),
                guardrails=_confirm_guardrails("learning_apply", pc.name),
                gate_runner=_gate(passed=True),
            )

    async def test_with_store_suspends_then_resumes_after_approval(
        self, tmp_path: Path
    ):
        pc = _persona(tmp_path)
        store = InMemoryApprovalStore()
        manager = FakeLearningStore()
        guardrails = _confirm_guardrails("learning_apply", pc.name)
        proposal = _low_pref_proposal()
        with pytest.raises(PendingApprovalError) as exc:
            await lrn.apply_proposal(
                pc,
                proposal,
                manager,
                guardrails=guardrails,
                gate_runner=_gate(passed=True),
                approvals=store,
            )
        assert proposal.status != "applied"
        store.decide(exc.value.approval_id, approved=True, decided_by="human")
        description = await lrn.apply_proposal(
            pc,
            proposal,
            manager,
            guardrails=guardrails,
            gate_runner=_gate(passed=True),
            approvals=store,
        )
        assert "stored preference" in description
        assert proposal.status == "applied"
        record = store.get(exc.value.approval_id)
        assert record is not None and record.status == "consumed"

    async def test_with_store_human_deny_blocks_apply(self, tmp_path: Path):
        pc = _persona(tmp_path)
        store = InMemoryApprovalStore()
        guardrails = _confirm_guardrails("learning_apply", pc.name)
        proposal = _low_pref_proposal()
        with pytest.raises(PendingApprovalError) as exc:
            await lrn.apply_proposal(
                pc,
                proposal,
                FakeLearningStore(),
                guardrails=guardrails,
                gate_runner=_gate(passed=True),
                approvals=store,
            )
        store.decide(exc.value.approval_id, approved=False)
        with pytest.raises(ApprovalDeniedError):
            await lrn.apply_proposal(
                pc,
                proposal,
                FakeLearningStore(),
                guardrails=guardrails,
                gate_runner=_gate(passed=True),
                approvals=store,
            )
        assert proposal.status != "applied"
