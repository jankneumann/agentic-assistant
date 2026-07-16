# evaluation/simulation/

Runtime simulation assets for the P27 `eval-simulation-loop` phase.

- `personas/sim/` — the **simulation persona**: a public, fixture-style
  persona whose `tool_sources` base URLs resolve from `SIM_<SOURCE>_URL`
  env vars pointing at the fixture-backed simulator. Load it with
  `ASSISTANT_PERSONAS_DIR=evaluation/simulation/personas`.
- `sources/` — the simulator's seed corpus: one directory per simulated
  source, each with a `routes.yaml` manifest and canned JSON responses
  (`ms_graph/` is promoted verbatim from
  `tests/fixtures/graph_responses/ms_graph/`; `content_analyzer/` and
  `coding_tools/` match the operation ids the public roles declare in
  `preferred_tools`).
- `scenarios/` — gen-eval scenario suites that run against the
  simulation persona (credential-free CLI plumbing floor: tool
  discovery + per-role prompt composition). Kept separate from
  `evaluation/scenarios/` because these require the simulator
  environment that `evaluation/run-gate.sh` sets up.

## Quick start

```bash
# shell 1 — start the simulator (prints the export lines below)
uv run assistant simulate                     # 127.0.0.1:8901

# shell 2 — run the assistant against it
export ASSISTANT_PERSONAS_DIR=evaluation/simulation/personas
export SIM_CONTENT_ANALYZER_URL=http://127.0.0.1:8901/content_analyzer
export SIM_CODING_TOOLS_URL=http://127.0.0.1:8901/coding_tools
export SIM_MS_GRAPH_URL=http://127.0.0.1:8901/ms_graph
uv run assistant -p sim --list-tools          # discovery smoke
uv run assistant -p sim -r researcher         # full REPL (needs model creds)
```

## Eval gate

`evaluation/run-gate.sh` runs the `scenarios/` suites through gen-eval
(descriptor: `evaluation/descriptors/agentic-assistant-simulation.yaml`)
and exits nonzero on failure. gen-eval stays external per ADR 0006 —
the gate SKIPs (exit 0) when the `agentic-coding-tools` checkout is
absent; set `EVAL_GATE_REQUIRE=1` to make that fatal.

## Trace → dataset export

`assistant export-eval-dataset -p <persona>` converts stored
interactions (persona DB `interactions` table) into scenario **stubs**
under `evaluation/datasets/exported/` — deliberately outside any
`scenario_dirs`. Complete a stub's message + expectations, drop its
`todo` marker, then move it into `scenarios/` to make the regression
permanent.
