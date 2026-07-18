"""Continual-learning pipeline tests (P28 continual-learning).

Exercised against hand-built ``PersonaConfig`` objects and the public
fixture persona ``learning_lab``; the DB-bound memory surface is a
lightweight in-memory fake satisfying the ``LearningMemoryStore``
protocol (P26 precedent). No harness, no database, no network.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from assistant.core import learning as lrn
from assistant.core.capabilities.guardrails import (
    ActionPolicy,
    AllowAllGuardrails,
    GuardrailConfig,
    ModelCallBudget,
    PolicyGuardrails,
    _clear_budget_ledgers,
    budget_ledger_for,
)
from assistant.core.capabilities.types import RiskLevel
from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.telemetry import factory

# ── Shared helpers ─────────────────────────────────────────────────────


class FakeLearningStore:
    """In-memory LearningMemoryStore fake (the real one is DB-bound)."""

    def __init__(
        self,
        interactions: list[dict[str, Any]] | None = None,
        facts: list[dict[str, Any]] | None = None,
    ) -> None:
        self.interactions = interactions or []
        self.facts = facts or []
        self.stored_facts: dict[str, Any] = {}
        self.stored_interactions: list[dict[str, Any]] = []
        self.stored_preferences: list[dict[str, Any]] = []
        self.episodes: list[tuple[str, str]] = []

    async def list_interactions(
        self, persona: str, role: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = list(self.interactions)
        rows.extend(self.stored_interactions)
        return rows[:limit]

    async def list_facts(
        self, persona: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = list(self.facts)
        rows.extend(
            {"id": None, "key": k, "value": v, "updated_at": None}
            for k, v in self.stored_facts.items()
        )
        return rows[:limit]

    async def store_fact(self, persona: str, key: str, value: Any) -> None:
        self.stored_facts[key] = value

    async def store_interaction(
        self,
        persona: str,
        role: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.stored_interactions.append(
            {
                "id": len(self.stored_interactions) + 1,
                "role": role,
                "summary": summary,
                "created_at": datetime.now(UTC).isoformat(),
                "metadata": metadata or {},
            }
        )

    async def store_preference(
        self,
        persona: str,
        category: str,
        key: str,
        value: Any,
        confidence: float = 0.5,
    ) -> None:
        self.stored_preferences.append(
            {
                "category": category,
                "key": key,
                "value": value,
                "confidence": confidence,
            }
        )

    async def store_episode(
        self, persona: str, content: str, source: str
    ) -> None:
        self.episodes.append((source, content))


class _SpanSpy:
    def __init__(self) -> None:
        self.name = "spy"
        self.spans: list[tuple[str, dict]] = []

    def start_span(self, name, attributes=None):
        self.spans.append((name, dict(attributes or {})))
        return nullcontext()


@pytest.fixture
def span_spy(monkeypatch: pytest.MonkeyPatch) -> _SpanSpy:
    spy = _SpanSpy()
    monkeypatch.setattr(factory, "_provider", spy)
    return spy


def _persona(
    tmp_path: Path,
    name: str = "learner",
    *,
    learning: lrn.LearningConfig | None = None,
    guardrails: GuardrailConfig | None = None,
    **overrides: Any,
) -> PersonaConfig:
    if learning is None:
        learning = lrn.LearningConfig(
            enabled=True, proposals_dir=tmp_path / name / "proposals"
        )
    return PersonaConfig(
        name=name,
        display_name=name,
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={},
        tool_sources={},
        extensions=[],
        extensions_dir=tmp_path / name / "extensions",
        learning=learning,
        guardrails=guardrails or GuardrailConfig(),
        **overrides,
    )


def _gate(passed: bool = True, skipped: bool = False) -> Any:
    return lambda: lrn.GateResult(passed=passed, skipped=skipped, output="")


def _preference_event(**overrides: Any) -> lrn.FeedbackEvent:
    kwargs: dict[str, Any] = {
        "source": "human",
        "subject": "role:coder",
        "signal": "prefer concise answers",
        "data": {
            "preference": {
                "category": "style",
                "key": "tone",
                "value": "concise",
            }
        },
    }
    kwargs.update(overrides)
    return lrn.FeedbackEvent(**kwargs)


# ── Config parsing ─────────────────────────────────────────────────────


class TestParseLearningConfig:
    def test_none_and_empty_yield_falsy_config(self):
        assert not lrn.parse_learning_config(None)
        assert not lrn.parse_learning_config({})

    def test_present_section_defaults_enabled(self, tmp_path: Path):
        config = lrn.parse_learning_config({}, persona_dir=tmp_path)
        assert not config  # empty mapping is falsy…
        config = lrn.parse_learning_config(
            {"auto_apply_low_risk": True}, persona_dir=tmp_path
        )
        assert config.enabled is True
        assert config.auto_apply_low_risk is True
        assert config.proposals_dir == tmp_path / "proposals"
        assert config.reflection_consumer == "memory"

    def test_enabled_false_stays_dormant(self):
        config = lrn.parse_learning_config({"enabled": False})
        assert not config

    def test_unknown_key_fails_actionably(self):
        with pytest.raises(lrn.LearningConfigError, match="self_merge"):
            lrn.parse_learning_config({"self_merge": True})

    def test_reflection_consumer_override(self):
        config = lrn.parse_learning_config(
            {"reflection": {"consumer": "scheduler"}}
        )
        assert config.reflection_consumer == "scheduler"

    def test_reflection_unknown_key_fails(self):
        with pytest.raises(lrn.LearningConfigError, match="model"):
            lrn.parse_learning_config({"reflection": {"model": "x"}})

    def test_explicit_proposals_dir_wins(self, tmp_path: Path):
        config = lrn.parse_learning_config(
            {"proposals_dir": "custom/props"}, persona_dir=tmp_path
        )
        assert config.proposals_dir == Path("custom/props")

    def test_non_bool_enabled_fails(self):
        with pytest.raises(lrn.LearningConfigError, match="enabled"):
            lrn.parse_learning_config({"enabled": "yes"})


class TestPersonaLoad:
    def test_fixture_persona_parses_learning_section(
        self, personas_dir: Path
    ):
        pc = PersonaRegistry(personas_dir).load("learning_lab")
        assert pc.learning
        assert pc.learning.auto_apply_low_risk is False
        assert pc.learning.proposals_dir == Path(".learning-proposals")

    def test_persona_without_section_is_dormant(self, personas_dir: Path):
        pc = PersonaRegistry(personas_dir).load("personal")
        assert not pc.learning
        with pytest.raises(lrn.LearningDenied, match="dormant"):
            lrn.require_learning(pc)

    def test_invalid_section_fails_persona_load(self, tmp_path: Path):
        persona_dir = tmp_path / "badlearner"
        persona_dir.mkdir()
        (persona_dir / "persona.yaml").write_text(
            "name: badlearner\nlearning:\n  bogus_key: 1\n"
        )
        with pytest.raises(ValueError, match="learning: unknown keys"):
            PersonaRegistry(tmp_path).load("badlearner")


# ── Feedback capture ───────────────────────────────────────────────────


class TestFeedback:
    def test_event_rejects_unknown_source(self):
        with pytest.raises(ValueError, match="telepathy"):
            lrn.FeedbackEvent(source="telepathy", subject="x", signal="y")

    def test_record_feedback_stores_labeled_interaction(
        self, tmp_path: Path, span_spy: _SpanSpy
    ):
        pc = _persona(tmp_path)
        store = FakeLearningStore()
        event = lrn.FeedbackEvent(
            source="human", subject="role:coder", signal="too verbose"
        )
        asyncio.run(lrn.record_feedback(pc, store, event))
        assert len(store.stored_interactions) == 1
        row = store.stored_interactions[0]
        assert row["metadata"]["source"] == "feedback"
        assert row["metadata"]["feedback"]["event_id"] == event.event_id
        assert "[feedback:human]" in row["summary"]
        assert any(
            name == lrn.LEARNING_FEEDBACK_SPAN for name, _ in span_spy.spans
        )

    def test_record_feedback_refuses_dormant_persona(self, tmp_path: Path):
        pc = _persona(tmp_path, learning=lrn.LearningConfig())
        with pytest.raises(lrn.LearningDenied, match="dormant"):
            asyncio.run(
                lrn.record_feedback(
                    pc,
                    FakeLearningStore(),
                    lrn.FeedbackEvent(source="human", subject="s", signal="t"),
                )
            )

    def test_list_feedback_round_trips_events(self, tmp_path: Path):
        pc = _persona(tmp_path)
        store = FakeLearningStore(
            interactions=[
                {
                    "id": 1,
                    "role": "coder",
                    "summary": "ordinary turn",
                    "created_at": "2026-07-18T00:00:00+00:00",
                    "metadata": {"source": "post_turn_capture"},
                }
            ]
        )
        event = _preference_event()
        asyncio.run(lrn.record_feedback(pc, store, event))
        events = asyncio.run(lrn.list_feedback(pc, store))
        assert len(events) == 1
        assert events[0].event_id == event.event_id
        assert events[0].data["preference"]["key"] == "tone"


# ── Machine collectors ─────────────────────────────────────────────────


class TestCollectors:
    def test_eval_collector_parses_gate_output(self):
        output = (
            "eval-gate: running triage.yaml\n"
            "eval-gate: FAIL — triage.yaml\n"
            "eval-gate: FAIL — 1 scenario file(s) failed.\n"
        )
        events = lrn.collect_eval_feedback(output)
        assert all(e.source == "eval" for e in events)
        assert events[0].subject == "triage.yaml"
        assert events[0].signal == "fail"

    def test_eval_collector_classifies_skip_and_pass(self):
        skip = lrn.collect_eval_feedback(
            "eval-gate: SKIP — gen-eval project not found at /x.\n"
        )
        assert skip[0].signal == "skip"
        ok = lrn.collect_eval_feedback(
            "eval-gate: PASS — all simulation scenarios green.\n"
        )
        assert ok[0].signal == "pass"

    def test_guardrail_collector_flags_budget_pressure(self, tmp_path: Path):
        _clear_budget_ledgers()
        config = GuardrailConfig(
            model_call_budget=ModelCallBudget(daily_usd=1.0)
        )
        pc = _persona(tmp_path, name="budgeted", guardrails=config)
        ledger = budget_ledger_for("budgeted", config)
        ledger.record(0.9, datetime.now(UTC))
        events = lrn.collect_guardrail_feedback(pc)
        assert len(events) == 1
        assert events[0].source == "guardrail"
        assert "daily" in events[0].subject
        _clear_budget_ledgers()

    def test_guardrail_collector_quiet_under_threshold(self, tmp_path: Path):
        _clear_budget_ledgers()
        config = GuardrailConfig(
            model_call_budget=ModelCallBudget(daily_usd=100.0)
        )
        pc = _persona(tmp_path, name="calm", guardrails=config)
        budget_ledger_for("calm", config).record(1.0, datetime.now(UTC))
        assert lrn.collect_guardrail_feedback(pc) == []
        _clear_budget_ledgers()

    def test_resilience_collector_reports_unhealthy_breakers(self):
        from assistant.core.resilience import get_circuit_breaker_registry

        registry = get_circuit_breaker_registry()
        breaker = registry.get_breaker("http:learning-test-source")
        try:
            asyncio.run(breaker.record_failure("boom"))
            events = lrn.collect_resilience_feedback()
            assert any(
                e.subject == "http:learning-test-source"
                and e.source == "resilience"
                for e in events
            )
        finally:
            registry._breakers.pop("http:learning-test-source", None)

    def test_cost_collector_flags_unpriced_cloud_entries(
        self, tmp_path: Path
    ):
        from assistant.core.capabilities.models import parse_model_registry

        registry = parse_model_registry(
            {
                "entries": {
                    "cloudy": {"dialect": "anthropic", "id": "claude-x"},
                    "local": {
                        "dialect": "openai-compatible",
                        "id": "llama",
                        "endpoint": "http://gx10.local:8000/v1",
                    },
                }
            }
        )
        pc = _persona(
            tmp_path,
            name="cost",
            guardrails=GuardrailConfig(
                model_call_budget=ModelCallBudget(daily_usd=5.0)
            ),
            models=registry,
        )
        events = lrn.collect_cost_feedback(pc)
        assert [e.subject for e in events] == ["models.entries.cloudy"]

    def test_machine_aggregate_refuses_dormant_persona(self, tmp_path: Path):
        pc = _persona(tmp_path, learning=lrn.LearningConfig())
        with pytest.raises(lrn.LearningDenied):
            lrn.collect_machine_feedback(pc)


# ── Reflection ─────────────────────────────────────────────────────────


def _interaction(i: int, summary: str, created: str) -> dict[str, Any]:
    return {
        "id": i,
        "role": "coder",
        "summary": summary,
        "created_at": created,
        "metadata": {},
    }


class TestReflection:
    def test_reflection_stores_provenance_stamped_fact(
        self, tmp_path: Path, span_spy: _SpanSpy
    ):
        pc = _persona(tmp_path)
        store = FakeLearningStore(
            interactions=[
                _interaction(1, "fixed the build", "2026-07-18T01:00:00+00:00"),
                _interaction(2, "wrote the tests", "2026-07-18T02:00:00+00:00"),
            ]
        )

        async def summarizer(lines: list[str]) -> str:
            return "user is shipping the P28 pipeline"

        result = asyncio.run(
            lrn.run_reflection(
                pc,
                store,
                guardrails=AllowAllGuardrails(),
                summarizer=summarizer,
            )
        )
        assert result is not None
        assert result.interaction_count == 2
        assert result.used_model is True
        fact = store.stored_facts[result.fact_key]
        assert fact["provenance"]["source"] == "reflection"
        assert fact["provenance"]["interaction_ids"] == [1, 2]
        # Graphiti episode write-back rides MemoryManager.store_episode.
        assert store.episodes == [
            ("reflection", "user is shipping the P28 pipeline")
        ]
        # Consolidation window advanced.
        assert (
            store.stored_facts[lrn.LAST_REFLECTION_KEY]["until"]
            == "2026-07-18T02:00:00+00:00"
        )
        assert any(
            name == lrn.LEARNING_REFLECT_SPAN for name, _ in span_spy.spans
        )

    def test_second_reflection_skips_consolidated_interactions(
        self, tmp_path: Path
    ):
        pc = _persona(tmp_path)
        store = FakeLearningStore(
            interactions=[
                _interaction(1, "old news", "2026-07-18T01:00:00+00:00")
            ]
        )

        async def summarizer(lines: list[str]) -> str:
            return "digest"

        first = asyncio.run(
            lrn.run_reflection(
                pc, store, guardrails=AllowAllGuardrails(), summarizer=summarizer
            )
        )
        assert first is not None
        second = asyncio.run(
            lrn.run_reflection(
                pc, store, guardrails=AllowAllGuardrails(), summarizer=summarizer
            )
        )
        assert second is None

    def test_reflection_degrades_to_heuristic_digest(self, tmp_path: Path):
        pc = _persona(tmp_path)
        store = FakeLearningStore(
            interactions=[
                _interaction(5, "note to self", "2026-07-18T01:00:00+00:00")
            ]
        )
        # Default summarizer path: no openai-compatible endpoint in the
        # synthesized default registry → deterministic digest.
        result = asyncio.run(
            lrn.run_reflection(pc, store, guardrails=AllowAllGuardrails())
        )
        assert result is not None
        assert result.used_model is False
        assert "note to self" in result.summary

    def test_reflection_refuses_dormant_persona(self, tmp_path: Path):
        pc = _persona(tmp_path, learning=lrn.LearningConfig())
        with pytest.raises(lrn.LearningDenied):
            asyncio.run(
                lrn.run_reflection(
                    pc, FakeLearningStore(), guardrails=AllowAllGuardrails()
                )
            )

    def test_run_reflection_for_persona_uses_manager_seam(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        pc = _persona(tmp_path)
        store = FakeLearningStore(
            interactions=[
                _interaction(9, "scheduled run", "2026-07-18T03:00:00+00:00")
            ]
        )
        monkeypatch.setattr(
            "assistant.core.learning._learning_memory_manager",
            lambda persona: store,
        )
        result = asyncio.run(lrn.run_reflection_for_persona(pc))
        assert "consolidated 1 interaction(s)" in result

    def test_reflection_manager_requires_database_url(self, tmp_path: Path):
        pc = _persona(tmp_path)
        with pytest.raises(lrn.LearningError, match="database_url"):
            lrn._learning_memory_manager(pc)


# ── Proposals ──────────────────────────────────────────────────────────


class TestDeriveProposals:
    def test_preference_feedback_distills_low_risk_proposal(
        self, tmp_path: Path
    ):
        pc = _persona(tmp_path)
        proposals = lrn.derive_proposals(pc, [_preference_event()])
        assert len(proposals) == 1
        p = proposals[0]
        assert p.kind == "preference"
        assert p.risk == "LOW"
        assert p.content["category"] == "style"
        assert p.content["key"] == "tone"

    def test_human_role_feedback_becomes_prompt_layer_suggestion(
        self, tmp_path: Path
    ):
        pc = _persona(tmp_path)
        event = lrn.FeedbackEvent(
            source="human", subject="role:coder", signal="stop apologising"
        )
        (p,) = lrn.derive_proposals(pc, [event])
        assert p.kind == "prompt_layer"
        assert p.risk == "MEDIUM"
        assert p.target == "roles/coder.md"

    def test_eval_failure_becomes_prompt_layer_suggestion(
        self, tmp_path: Path
    ):
        pc = _persona(tmp_path)
        event = lrn.FeedbackEvent(
            source="eval", subject="triage.yaml", signal="fail"
        )
        (p,) = lrn.derive_proposals(pc, [event])
        assert p.kind == "prompt_layer"
        assert p.target == "prompt.md"
        assert "triage.yaml" in p.rationale

    def test_machine_signals_become_high_risk_routing_config(
        self, tmp_path: Path
    ):
        pc = _persona(tmp_path)
        events = [
            lrn.FeedbackEvent(
                source="cost", subject="models.entries.x", signal="unpriced"
            ),
            lrn.FeedbackEvent(
                source="guardrail",
                subject="guardrails.budgets.model_call.daily",
                signal="90%",
            ),
        ]
        (p,) = lrn.derive_proposals(pc, events)
        assert p.kind == "routing_config"
        assert p.risk == "HIGH"
        # Same (kind, target) merges provenance.
        assert len(p.provenance) == 2

    def test_risk_tiering_matches_kind_map(self):
        assert lrn.RISK_BY_KIND["preference"] is RiskLevel.LOW
        assert lrn.RISK_BY_KIND["prompt_layer"] is RiskLevel.MEDIUM
        assert lrn.RISK_BY_KIND["routing_config"] is RiskLevel.HIGH

    def test_proposal_file_round_trip(self, tmp_path: Path):
        proposal = lrn.ImprovementProposal(
            proposal_id="abc123",
            kind="preference",
            target="preference:style/tone",
            content={"category": "style", "key": "tone", "value": "concise"},
            rationale="test",
            risk="LOW",
            provenance=["ev1"],
        )
        path = lrn.write_proposal(tmp_path / "props", proposal)
        loaded = lrn.load_proposal(path)
        assert loaded.to_payload() == proposal.to_payload()
        assert lrn.list_proposals(tmp_path / "props")[0].proposal_id == "abc123"

    def test_malformed_proposal_file_is_rejected(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"format": "not-a-proposal"}))
        with pytest.raises(lrn.ProposalError, match="format"):
            lrn.load_proposal(bad)


# ── Apply ──────────────────────────────────────────────────────────────


def _low_pref_proposal() -> lrn.ImprovementProposal:
    return lrn.ImprovementProposal(
        proposal_id="pref1",
        kind="preference",
        target="preference:style/tone",
        content={
            "category": "style",
            "key": "tone",
            "value": "concise",
            "confidence": 0.7,
        },
        rationale="distilled",
        risk="LOW",
    )


class TestApply:
    def test_low_preference_applies_through_store(
        self, tmp_path: Path, span_spy: _SpanSpy
    ):
        pc = _persona(tmp_path)
        store = FakeLearningStore()
        proposal = _low_pref_proposal()
        description = asyncio.run(
            lrn.apply_proposal(
                pc,
                proposal,
                store,
                guardrails=AllowAllGuardrails(),
                gate_runner=_gate(),
            )
        )
        assert "style" in description
        assert store.stored_preferences == [
            {
                "category": "style",
                "key": "tone",
                "value": "concise",
                "confidence": 0.7,
            }
        ]
        assert proposal.status == "applied"
        assert proposal.applied_at is not None
        assert any(
            name == lrn.LEARNING_APPLY_SPAN for name, _ in span_spy.spans
        )

    def test_medium_risk_requires_approved_flag(self, tmp_path: Path):
        pc = _persona(tmp_path)
        proposal = lrn.ImprovementProposal(
            proposal_id="pl1",
            kind="prompt_layer",
            target="prompt.md",
            content="be brief",
            rationale="test",
            risk="MEDIUM",
        )
        with pytest.raises(lrn.LearningDenied, match="--approved"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    proposal,
                    None,
                    guardrails=AllowAllGuardrails(),
                    gate_runner=_gate(),
                )
            )
        # With approval, the suggestion block lands inside the persona dir.
        description = asyncio.run(
            lrn.apply_proposal(
                pc,
                proposal,
                None,
                guardrails=AllowAllGuardrails(),
                approved=True,
                gate_runner=_gate(),
            )
        )
        target = tmp_path / "learner" / "prompt.md"
        assert "appended" in description
        assert "be brief" in target.read_text()
        assert proposal.proposal_id in target.read_text()

    def test_prompt_layer_target_cannot_escape_persona_dir(
        self, tmp_path: Path
    ):
        pc = _persona(tmp_path)
        proposal = lrn.ImprovementProposal(
            proposal_id="evil",
            kind="prompt_layer",
            target="../../etc/passwd",
            content="x",
            rationale="",
            risk="MEDIUM",
        )
        with pytest.raises(lrn.LearningDenied, match="escapes"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    proposal,
                    None,
                    guardrails=AllowAllGuardrails(),
                    approved=True,
                    gate_runner=_gate(),
                )
            )

    def test_routing_config_is_review_only(self, tmp_path: Path):
        pc = _persona(tmp_path)
        proposal = lrn.ImprovementProposal(
            proposal_id="rc1",
            kind="routing_config",
            target="persona.yaml",
            content="bind scheduler to gx10-chat",
            rationale="",
            risk="HIGH",
        )
        with pytest.raises(lrn.LearningDenied, match="review-only"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    proposal,
                    None,
                    guardrails=AllowAllGuardrails(),
                    approved=True,
                    gate_runner=_gate(),
                )
            )

    def test_apply_refuses_when_eval_gate_fails(self, tmp_path: Path):
        pc = _persona(tmp_path)
        with pytest.raises(lrn.LearningDenied, match="eval gate"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    _low_pref_proposal(),
                    FakeLearningStore(),
                    guardrails=AllowAllGuardrails(),
                    gate_runner=_gate(passed=False),
                )
            )

    def test_gate_skip_counts_as_pass_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        pc = _persona(tmp_path)
        store = FakeLearningStore()
        with caplog.at_level("WARNING", logger="assistant.core.learning"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    _low_pref_proposal(),
                    store,
                    guardrails=AllowAllGuardrails(),
                    gate_runner=_gate(skipped=True),
                )
            )
        assert store.stored_preferences
        assert any("SKIP" in rec.message for rec in caplog.records)

    def test_guardrail_deny_refuses_apply(self, tmp_path: Path):
        config = GuardrailConfig(
            policies=[
                ActionPolicy(
                    action_type="learning_apply",
                    effect="deny",
                    reason="no self-modification here",
                )
            ]
        )
        pc = _persona(tmp_path, guardrails=config)
        with pytest.raises(lrn.LearningDenied, match="no self-modification"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    _low_pref_proposal(),
                    FakeLearningStore(),
                    guardrails=PolicyGuardrails(config, persona="learner"),
                    gate_runner=_gate(),
                )
            )

    def test_require_confirmation_denies_until_p30(self, tmp_path: Path):
        config = GuardrailConfig(
            policies=[
                ActionPolicy(
                    action_type="learning_apply",
                    effect="require_confirmation",
                )
            ]
        )
        pc = _persona(tmp_path, guardrails=config)
        with pytest.raises(lrn.LearningDenied, match="confirmation"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    _low_pref_proposal(),
                    FakeLearningStore(),
                    guardrails=PolicyGuardrails(config, persona="learner"),
                    gate_runner=_gate(),
                )
            )

    def test_already_applied_proposal_refuses(self, tmp_path: Path):
        pc = _persona(tmp_path)
        proposal = _low_pref_proposal()
        proposal.status = "applied"
        proposal.applied_at = "2026-07-18T00:00:00+00:00"
        with pytest.raises(lrn.LearningDenied, match="already applied"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    proposal,
                    FakeLearningStore(),
                    guardrails=AllowAllGuardrails(),
                    gate_runner=_gate(),
                )
            )

    def test_apply_refuses_dormant_persona(self, tmp_path: Path):
        pc = _persona(tmp_path, learning=lrn.LearningConfig())
        with pytest.raises(lrn.LearningDenied, match="dormant"):
            asyncio.run(
                lrn.apply_proposal(
                    pc,
                    _low_pref_proposal(),
                    FakeLearningStore(),
                    guardrails=AllowAllGuardrails(),
                    gate_runner=_gate(),
                )
            )


class TestAutoApply:
    def test_auto_apply_requires_opt_in(self, tmp_path: Path):
        pc = _persona(tmp_path)  # auto_apply_low_risk defaults False
        applied = asyncio.run(
            lrn.maybe_auto_apply(
                pc,
                [_low_pref_proposal()],
                FakeLearningStore(),
                guardrails=AllowAllGuardrails(),
                gate_runner=_gate(),
            )
        )
        assert applied == []

    def test_auto_apply_only_low_risk_preferences(self, tmp_path: Path):
        pc = _persona(
            tmp_path,
            learning=lrn.LearningConfig(
                enabled=True,
                auto_apply_low_risk=True,
                proposals_dir=tmp_path / "learner" / "proposals",
            ),
        )
        store = FakeLearningStore()
        pref = _low_pref_proposal()
        prompt = lrn.ImprovementProposal(
            proposal_id="pl2",
            kind="prompt_layer",
            target="prompt.md",
            content="x",
            rationale="",
            risk="MEDIUM",
        )
        applied = asyncio.run(
            lrn.maybe_auto_apply(
                pc,
                [pref, prompt],
                store,
                guardrails=AllowAllGuardrails(),
                gate_runner=_gate(),
            )
        )
        assert applied == [pref.proposal_id]
        assert pref.status == "applied"
        assert prompt.status == "proposed"

    def test_auto_apply_swallows_guardrail_refusal(self, tmp_path: Path):
        config = GuardrailConfig(
            policies=[
                ActionPolicy(action_type="learning_apply", effect="deny")
            ]
        )
        pc = _persona(
            tmp_path,
            learning=lrn.LearningConfig(
                enabled=True,
                auto_apply_low_risk=True,
                proposals_dir=tmp_path / "learner" / "proposals",
            ),
            guardrails=config,
        )
        applied = asyncio.run(
            lrn.maybe_auto_apply(
                pc,
                [_low_pref_proposal()],
                FakeLearningStore(),
                guardrails=PolicyGuardrails(config, persona="learner"),
                gate_runner=_gate(),
            )
        )
        assert applied == []


# ── Eval gate runner ───────────────────────────────────────────────────


class TestRunEvalGate:
    def test_missing_script_is_a_skip(self, tmp_path: Path):
        result = lrn.run_eval_gate(tmp_path / "no-such-gate.sh")
        assert result.passed is True
        assert result.skipped is True

    def test_failing_script_fails_the_gate(self, tmp_path: Path):
        script = tmp_path / "gate.sh"
        script.write_text("#!/bin/bash\necho 'eval-gate: FAIL — x.yaml' >&2\nexit 1\n")
        result = lrn.run_eval_gate(script)
        assert result.passed is False

    def test_skip_output_classifies_as_skipped(self, tmp_path: Path):
        script = tmp_path / "gate.sh"
        script.write_text(
            "#!/bin/bash\necho 'eval-gate: SKIP — gen-eval not found.'\nexit 0\n"
        )
        result = lrn.run_eval_gate(script)
        assert result.passed is True
        assert result.skipped is True

    def test_passing_script_passes(self, tmp_path: Path):
        script = tmp_path / "gate.sh"
        script.write_text("#!/bin/bash\necho 'eval-gate: PASS'\nexit 0\n")
        result = lrn.run_eval_gate(script)
        assert result.passed is True
        assert result.skipped is False


# ── Scheduler integration (kind: reflect) ──────────────────────────────


class TestSchedulerReflectJobs:
    def test_parse_reflect_job_without_role_or_prompt(self):
        from assistant.core.scheduler import parse_schedule_config

        config = parse_schedule_config(
            {"nightly": {"trigger": {"cron": "0 3 * * *"}, "kind": "reflect"}}
        )
        job = config.jobs["nightly"]
        assert job.kind == "reflect"
        assert job.role == ""
        assert job.prompt == ""

    def test_agent_jobs_still_require_role_and_prompt(self):
        from assistant.core.scheduler import (
            ScheduleConfigError,
            parse_schedule_config,
        )

        with pytest.raises(ScheduleConfigError, match="role"):
            parse_schedule_config(
                {"bad": {"trigger": {"interval": 60}, "prompt": "hi"}}
            )

    def test_unknown_kind_fails_actionably(self):
        from assistant.core.scheduler import (
            ScheduleConfigError,
            parse_schedule_config,
        )

        with pytest.raises(ScheduleConfigError, match="kind"):
            parse_schedule_config(
                {"bad": {"trigger": {"interval": 60}, "kind": "dream"}}
            )

    def test_runner_dispatches_reflect_jobs_to_learning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from assistant.core.scheduler import (
            HarnessJobRunner,
            ScheduledJob,
            ScheduleTrigger,
        )

        pc = _persona(tmp_path)
        seen: list[str] = []

        async def fake_reflect(persona) -> str:
            seen.append(persona.name)
            return "reflection: consolidated 3 interaction(s) into k"

        monkeypatch.setattr(
            "assistant.core.learning.run_reflection_for_persona",
            fake_reflect,
        )
        runner = HarnessJobRunner(pc)
        job = ScheduledJob(
            name="nightly",
            trigger=ScheduleTrigger(kind="cron", cron="0 3 * * *"),
            role="",
            prompt="",
            kind="reflect",
        )
        result = asyncio.run(runner.run(job))
        assert seen == ["learner"]
        assert "consolidated" in result
