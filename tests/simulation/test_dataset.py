"""Tests for interaction → scenario-stub conversion (spec: simulation / Eval Dataset Export)."""

from __future__ import annotations

import yaml

from assistant.simulation.dataset import (
    dump_scenario_yaml,
    interactions_to_scenarios,
    scenario_filename,
)


def _interaction(**overrides) -> dict:
    base = {
        "id": 7,
        "role": "researcher",
        "summary": "Summarized three papers on eval loops",
        "created_at": "2026-07-16T12:00:00+00:00",
        "metadata": {"harness": "deep_agents"},
    }
    base.update(overrides)
    return base


class TestInteractionsToScenarios:
    def test_one_scenario_per_interaction(self) -> None:
        scenarios = interactions_to_scenarios(
            "personal", [_interaction(id=1), _interaction(id=2)]
        )
        assert len(scenarios) == 2
        assert scenarios[0]["id"] != scenarios[1]["id"]

    def test_scenario_carries_provenance_and_regression_shape(self) -> None:
        (scenario,) = interactions_to_scenarios("personal", [_interaction()])
        assert scenario["category"] == "regression"
        assert "exported" in scenario["tags"]
        assert "researcher" in scenario["tags"]
        src = scenario["source"]
        assert src["exported_from"] == "interactions"
        assert src["persona"] == "personal"
        assert src["interaction_id"] == 7
        assert src["recorded_at"] == "2026-07-16T12:00:00+00:00"

    def test_replay_step_is_a_todo_stub(self) -> None:
        (scenario,) = interactions_to_scenarios("personal", [_interaction()])
        assert "todo" in scenario
        (step,) = scenario["steps"]
        assert step["transport"] == "http"
        assert step["method"] == "POST"
        assert step["endpoint"] == "/chat"
        assert step["body"]["message"].startswith("TODO:")
        assert "eval loops" in step["body"]["message"]
        assert step["expect"] == {"status": 200}

    def test_empty_summary_still_produces_valid_stub(self) -> None:
        (scenario,) = interactions_to_scenarios(
            "personal", [_interaction(summary="", id=3)]
        )
        assert scenario["id"].startswith("exported-personal-3")
        assert scenario["name"]


class TestScenarioSerialization:
    def test_filename_is_filesystem_safe(self) -> None:
        (scenario,) = interactions_to_scenarios(
            "personal", [_interaction(summary="Weird / summary: with*chars?")]
        )
        name = scenario_filename(scenario)
        assert name.endswith(".yaml")
        assert "/" not in name.removesuffix(".yaml")
        assert " " not in name

    def test_yaml_round_trips_with_header_comment(self) -> None:
        (scenario,) = interactions_to_scenarios("personal", [_interaction()])
        text = dump_scenario_yaml(scenario)
        assert text.startswith("# Exported eval-dataset stub")
        parsed = yaml.safe_load(text)
        assert parsed == scenario
