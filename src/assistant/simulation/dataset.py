"""Interaction → gen-eval scenario-stub conversion (P27 ``eval-simulation-loop``).

Offline-first trace→eval-dataset export: the source of truth is the
persona database's ``interactions`` table (written by the harnesses'
post-turn ``record_interaction`` capture, P21), read via
``MemoryManager.list_interactions``. Each interaction becomes a
gen-eval-compatible scenario YAML **stub**: provenance and a replay
step are filled in; the human completes the user message and the
expectations before promoting the stub into a scenario suite.

Langfuse-API-based export (pulling full traces instead of one-line
summaries) is a recorded follow-up — see
openspec/changes/eval-simulation-loop/design.md D5.

Everything here is pure (no I/O) so it is unit-testable without a
database; the CLI command owns file writing.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

_SLUG_RE = re.compile(r"[^a-z0-9]+")

#: Comment header prepended to every exported stub file.
_STUB_HEADER = (
    "# Exported eval-dataset stub (assistant export-eval-dataset).\n"
    "# Source: persona DB `interactions` table — a one-line post-turn\n"
    "# summary, NOT a full transcript. Before promoting this stub into a\n"
    "# scenario suite (e.g. evaluation/simulation/scenarios/):\n"
    "#   1. reconstruct the user message in steps[0].body.message\n"
    "#   2. replace the placeholder expectations with real ones\n"
    "#   3. drop the `todo` marker\n"
)


def _slug(text: str, max_len: int = 40) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "interaction"


def interactions_to_scenarios(
    persona: str, interactions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Convert interaction records into gen-eval scenario stub dicts.

    ``interactions`` items are the dict shape returned by
    ``MemoryManager.list_interactions``: keys ``id``, ``role``,
    ``summary``, ``created_at`` (ISO string or ``None``), ``metadata``.
    """
    scenarios: list[dict[str, Any]] = []
    for item in interactions:
        interaction_id = item.get("id")
        role = str(item.get("role") or "unknown")
        summary = str(item.get("summary") or "").strip()
        created_at = item.get("created_at")

        scenario_id = f"exported-{persona}-{interaction_id}-{_slug(summary)}"
        scenarios.append(
            {
                "id": scenario_id,
                "name": f"Regression: {summary[:70]}" if summary else (
                    f"Regression: interaction {interaction_id}"
                ),
                "description": (
                    f"Exported from persona '{persona}' interaction "
                    f"#{interaction_id} (role: {role}). Recorded summary: "
                    f"{summary or '(empty)'}"
                ),
                "category": "regression",
                "priority": 2,
                "tags": ["regression", "exported", role],
                "todo": (
                    "Stub — reconstruct the user message and replace the "
                    "placeholder expectations before use."
                ),
                "source": {
                    "exported_from": "interactions",
                    "persona": persona,
                    "interaction_id": interaction_id,
                    "role": role,
                    "recorded_at": created_at,
                    "metadata": item.get("metadata") or {},
                },
                "steps": [
                    {
                        "id": "replay_turn",
                        "transport": "http",
                        "method": "POST",
                        "endpoint": "/chat",
                        "body": {
                            "message": (
                                "TODO: reconstruct the user message that "
                                f"produced: {summary or '(no summary)'}"
                            ),
                        },
                        "expect": {"status": 200},
                    }
                ],
            }
        )
    return scenarios


def scenario_filename(scenario: dict[str, Any]) -> str:
    """Filesystem-safe file name for an exported scenario stub."""
    return f"{_slug(str(scenario['id']), max_len=80)}.yaml"


def dump_scenario_yaml(scenario: dict[str, Any]) -> str:
    """Render one scenario stub as YAML with the stub header comment."""
    body = yaml.safe_dump(
        scenario, sort_keys=False, allow_unicode=True, width=78
    )
    return _STUB_HEADER + body
