"""CLI tests for the P28 continual-learning commands.

`assistant feedback`, `assistant reflect`, and the `assistant learning`
group, exercised against the public fixture persona ``learning_lab``
(learning enabled, relative proposals dir) and ``personal`` (dormant).
The memory manager seam is patched at its source module (gotcha G4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from assistant.cli import main
from assistant.core import learning as lrn
from tests.test_learning import FakeLearningStore, _gate


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeLearningStore:
    fake = FakeLearningStore()
    monkeypatch.setattr(
        "assistant.core.learning._learning_memory_manager",
        lambda persona: fake,
    )
    return fake


@pytest.fixture
def gate_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "assistant.core.learning.run_eval_gate", _gate(passed=True)
    )


def _write_low_pref_proposal(proposals_dir: Path) -> lrn.ImprovementProposal:
    proposal = lrn.ImprovementProposal(
        proposal_id="clipref1",
        kind="preference",
        target="preference:style/tone",
        content={"category": "style", "key": "tone", "value": "concise"},
        rationale="test",
        risk="LOW",
    )
    lrn.write_proposal(proposals_dir, proposal)
    return proposal


class TestFeedbackCommand:
    def test_feedback_records_event(
        self, runner: CliRunner, store: FakeLearningStore
    ):
        result = runner.invoke(
            main,
            ["feedback", "-p", "learning_lab", "-r", "coder", "too wordy"],
        )
        assert result.exit_code == 0, result.output
        assert "Recorded feedback event" in result.output
        assert len(store.stored_interactions) == 1
        payload = store.stored_interactions[0]["metadata"]["feedback"]
        assert payload["source"] == "human"
        assert payload["subject"] == "role:coder"

    def test_feedback_prefer_carries_preference_payload(
        self, runner: CliRunner, store: FakeLearningStore
    ):
        result = runner.invoke(
            main,
            ["feedback", "-p", "learning_lab", "--prefer", "style:tone=brief"],
        )
        assert result.exit_code == 0, result.output
        payload = store.stored_interactions[0]["metadata"]["feedback"]
        assert payload["data"]["preference"] == {
            "category": "style",
            "key": "tone",
            "value": "brief",
        }

    def test_feedback_refuses_dormant_persona(
        self, runner: CliRunner, store: FakeLearningStore
    ):
        result = runner.invoke(
            main, ["feedback", "-p", "personal", "nice work"]
        )
        assert result.exit_code == 1
        assert "dormant" in result.output

    def test_feedback_requires_text_or_prefer(self, runner: CliRunner):
        result = runner.invoke(main, ["feedback", "-p", "learning_lab"])
        assert result.exit_code != 0
        assert "--prefer" in result.output


class TestReflectCommand:
    def test_reflect_consolidates(
        self, runner: CliRunner, store: FakeLearningStore
    ):
        store.interactions.append(
            {
                "id": 1,
                "role": "coder",
                "summary": "shipped P28",
                "created_at": "2026-07-18T01:00:00+00:00",
                "metadata": {},
            }
        )
        result = runner.invoke(main, ["reflect", "-p", "learning_lab"])
        assert result.exit_code == 0, result.output
        assert "Consolidated 1 interaction(s)" in result.output
        assert any(
            key.startswith(lrn.REFLECTION_KEY_PREFIX)
            for key in store.stored_facts
        )

    def test_reflect_reports_nothing_new(
        self, runner: CliRunner, store: FakeLearningStore
    ):
        result = runner.invoke(main, ["reflect", "-p", "learning_lab"])
        assert result.exit_code == 0, result.output
        assert "Nothing new" in result.output

    def test_reflect_refuses_dormant_persona(
        self, runner: CliRunner, store: FakeLearningStore
    ):
        result = runner.invoke(main, ["reflect", "-p", "personal"])
        assert result.exit_code == 1
        assert "dormant" in result.output


class TestLearningCollect:
    def test_collect_reports_gate_log_findings(
        self, runner: CliRunner, tmp_path: Path
    ):
        log = tmp_path / "gate.log"
        log.write_text("eval-gate: FAIL — triage.yaml\n")
        result = runner.invoke(
            main,
            ["learning", "collect", "-p", "learning_lab", "--gate-log", str(log)],
        )
        assert result.exit_code == 0, result.output
        assert "[eval] triage.yaml: fail" in result.output

    def test_collect_store_records_feedback(
        self,
        runner: CliRunner,
        store: FakeLearningStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(
            "assistant.core.learning.collect_resilience_feedback",
            lambda: [],
        )
        log = tmp_path / "gate.log"
        log.write_text("eval-gate: FAIL — triage.yaml\n")
        result = runner.invoke(
            main,
            [
                "learning",
                "collect",
                "-p",
                "learning_lab",
                "--gate-log",
                str(log),
                "--store",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Stored 1 feedback event(s)." in result.output
        assert len(store.stored_interactions) == 1

    def test_collect_refuses_dormant_persona(self, runner: CliRunner):
        result = runner.invoke(main, ["learning", "collect", "-p", "personal"])
        assert result.exit_code == 1
        assert "dormant" in result.output


class TestLearningProposeAndApply:
    def test_propose_writes_proposal_files(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        log = tmp_path / "gate.log"
        log.write_text("eval-gate: FAIL — triage.yaml\n")
        # The breaker registry is process-wide; keep this test hermetic
        # against breakers other test modules may have left behind.
        monkeypatch.setattr(
            "assistant.core.learning.collect_resilience_feedback",
            lambda: [],
        )
        with runner.isolated_filesystem():
            result = runner.invoke(
                main,
                [
                    "learning",
                    "propose",
                    "-p",
                    "learning_lab",
                    "--gate-log",
                    str(log),
                ],
            )
            assert result.exit_code == 0, result.output
            files = list(Path(".learning-proposals").glob("*.json"))
            assert len(files) == 1
            payload = json.loads(files[0].read_text())
            assert payload["kind"] == "prompt_layer"
            assert payload["risk"] == "MEDIUM"
            assert "no database_url" in result.output  # machine-only warning

    def test_apply_low_preference_proposal(
        self,
        runner: CliRunner,
        store: FakeLearningStore,
        gate_pass: None,
    ):
        with runner.isolated_filesystem():
            proposals_dir = Path(".learning-proposals")
            proposal = _write_low_pref_proposal(proposals_dir)
            result = runner.invoke(
                main,
                ["learning", "apply", "-p", "learning_lab", proposal.proposal_id],
            )
            assert result.exit_code == 0, result.output
            assert "Applied proposal clipref1" in result.output
            assert store.stored_preferences[0]["key"] == "tone"
            # Status persisted back to the proposal file.
            payload = json.loads(
                (proposals_dir / "clipref1.json").read_text()
            )
            assert payload["status"] == "applied"

    def test_apply_medium_risk_requires_approved(
        self, runner: CliRunner, gate_pass: None
    ):
        with runner.isolated_filesystem():
            proposals_dir = Path(".learning-proposals")
            proposal = lrn.ImprovementProposal(
                proposal_id="clipl1",
                kind="prompt_layer",
                target="prompt.md",
                content="be brief",
                rationale="test",
                risk="MEDIUM",
            )
            lrn.write_proposal(proposals_dir, proposal)
            result = runner.invoke(
                main,
                ["learning", "apply", "-p", "learning_lab", "clipl1"],
            )
            assert result.exit_code == 1
            assert "--approved" in result.output

    def test_apply_refuses_when_gate_fails(
        self,
        runner: CliRunner,
        store: FakeLearningStore,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(
            "assistant.core.learning.run_eval_gate", _gate(passed=False)
        )
        with runner.isolated_filesystem():
            proposal = _write_low_pref_proposal(Path(".learning-proposals"))
            result = runner.invoke(
                main,
                ["learning", "apply", "-p", "learning_lab", proposal.proposal_id],
            )
            assert result.exit_code == 1
            assert "eval gate" in result.output
            assert store.stored_preferences == []

    def test_apply_unknown_proposal_fails(self, runner: CliRunner):
        with runner.isolated_filesystem():
            result = runner.invoke(
                main, ["learning", "apply", "-p", "learning_lab", "nope"]
            )
            assert result.exit_code == 1
            assert "no proposal" in result.output

    def test_list_shows_proposals(self, runner: CliRunner):
        with runner.isolated_filesystem():
            _write_low_pref_proposal(Path(".learning-proposals"))
            result = runner.invoke(
                main, ["learning", "list", "-p", "learning_lab"]
            )
            assert result.exit_code == 0, result.output
            assert "clipref1" in result.output
            assert "[preference, LOW, proposed]" in result.output

    def test_list_refuses_dormant_persona(self, runner: CliRunner):
        result = runner.invoke(main, ["learning", "list", "-p", "personal"])
        assert result.exit_code == 1
        assert "dormant" in result.output
