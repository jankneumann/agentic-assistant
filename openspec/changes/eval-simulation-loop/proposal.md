# eval-simulation-loop — Simulation Personas, Eval Gate, Trace→Dataset Export (P27)

## Why

The eval/observability assets don't form a loop (ecosystem pillar 5,
`docs/architecture-analysis/2026-07-16-ecosystem-pillars.md`): Langfuse
tracing captures production behavior but nothing turns regressions into
tests; gen-eval scenarios exist (`evaluation/`) but only cover
credential-free plumbing against the *personal* persona's serve
surface; and the rich API-mock corpus
(`tests/mocks/graph_client.py`, `tests/fixtures/graph_responses/`,
pytest-httpserver suites) is test-only — there is no runtime API
simulation, so no behavioral eval can exercise real tool discovery,
selection, and invocation without live services and credentials.

P28 `continual-learning` depends on an eval gate: learned changes must
be propose → eval → human-approved diff, never self-merge. That gate
has to exist first, and it has to run on machines without external
service credentials — which requires simulation.

## What Changes

- **Simulator server** (`src/assistant/simulation/server.py`): a small
  FastAPI app serving OpenAPI-described mock tool endpoints seeded from
  fixture directories (`routes.yaml` manifest + canned JSON responses;
  leading `//` sentinel comment lines tolerated so the existing
  `graph_responses` corpus serves verbatim). Each source is mounted at
  `/<source_name>` with its own `/openapi.json`, so the EXISTING
  `http_tools` discovery consumes it unchanged — zero new agent code
  paths.
- **Simulation persona** (`evaluation/simulation/personas/sim/`): a
  public fixture-style persona whose `tool_sources` resolve base URLs
  from `SIM_<SOURCE>_URL` env vars; loaded via
  `ASSISTANT_PERSONAS_DIR=evaluation/simulation/personas`. Seed corpus
  under `evaluation/simulation/sources/` covers `content_analyzer`,
  `coding_tools` (operation ids match the roles' `preferred_tools`)
  and `ms_graph` (promoted from `tests/fixtures/graph_responses/`).
- **CLI**: `assistant simulate` (starts the simulator on loopback and
  prints the env/persona invocation) and `assistant
  export-eval-dataset` (offline trace→dataset export: persona DB
  `interactions` table → gen-eval scenario YAML stubs).
- **`MemoryManager.list_interactions`** — JSON-safe interaction
  listing backing the export; traced as the new
  `trace_memory_op(op="interaction_list")` (observability vocabulary
  extended accordingly).
- **Per-role scenario suites** (`evaluation/simulation/scenarios/`):
  credential-free floor — tool discovery through the simulator +
  per-role prompt-composition sweep — with a dedicated descriptor
  (`evaluation/descriptors/agentic-assistant-simulation.yaml`).
- **Eval gate** (`evaluation/run-gate.sh`): runs the simulation suites
  through gen-eval and exits nonzero on failure; SKIPs (exit 0) with a
  clear message when the external gen-eval checkout is absent
  (ADR 0006 — gen-eval is a consumer, never a dependency);
  `EVAL_GATE_REQUIRE=1` makes absence fatal. Consumed by P28 and by
  prompt/routing config changes.

## Impact

- Affected specs: **ADDED** `simulation`; **MODIFIED** `cli-interface`
  (two new subcommands, additive), `observability` (op vocabulary),
  `memory-policy` (added `list_interactions` requirement).
- Affected code: `src/assistant/simulation/` (new),
  `src/assistant/cli.py`, `src/assistant/core/memory.py`,
  `src/assistant/telemetry/providers/base.py`, `evaluation/`
  (simulation assets, descriptor, gate script), tests.
- No behavior change for existing personas/harnesses: simulation is
  opt-in via env vars; discovery, tool policy, and harness paths are
  untouched.
- Deferred (recorded in design.md): Langfuse-API trace export,
  LLM-driven behavioral scenarios per role, scheduled runs (P7),
  CI wiring of the gate on machines with the tools-repo checkout.
