# eval-simulation-loop — Tasks

## 1. Simulator core

- [x] 1.1 `src/assistant/simulation/server.py` — manifest types
  (`SimParameter`/`SimRoute`/`SimSource`), `load_response_json`
  (sentinel-comment stripping), `load_source` validation,
  `discover_sources`, per-source FastAPI apps with explicit
  operationIds + dynamic query-param signatures, root app with
  `/health` and per-source mounts, `env_var_for_source` convention
- [x] 1.2 Seed corpus `evaluation/simulation/sources/` —
  `content_analyzer` + `coding_tools` (operation ids matching
  `roles/*/role.yaml` preferred_tools) and `ms_graph` (promoted
  verbatim from `tests/fixtures/graph_responses/ms_graph/`)
- [x] 1.3 Tests `tests/simulation/test_server.py` — manifest loading
  errors, seed-corpus serving (/health, per-source /openapi.json 3.x
  with operationIds, canned payloads, 422 on missing required param,
  POST route), preferred-tools coverage lockstep check
- [x] 1.4 Tests `tests/simulation/test_discovery_integration.py` —
  real `discover_tools` against the simulator over ASGITransport
  (registry contents, args schema fields, tool `ainvoke` roundtrip)

## 2. Simulation persona + eval assets

- [x] 2.1 `evaluation/simulation/personas/sim/` — public persona
  (`SIM_<SOURCE>_URL` base_url_env indirection, no DB/auth/extensions)
  + prompt layer; home-choice rationale documented (design D2)
- [x] 2.2 Scenario suites `evaluation/simulation/scenarios/` —
  `sim-tool-discovery.yaml`, `sim-role-compose-sweep.yaml` (per public
  role)
- [x] 2.3 Descriptor
  `evaluation/descriptors/agentic-assistant-simulation.yaml` —
  CLI service + simulator startup/health/teardown lifecycle
- [x] 2.4 `evaluation/run-gate.sh` — external gen-eval shell-out,
  advisory SKIP (exit 0) without the tools-repo checkout,
  `EVAL_GATE_REQUIRE=1` hard-fail, nonzero on scenario failure
- [x] 2.5 `evaluation/simulation/README.md` + `evaluation/datasets/`
  gitignore (raw exports stay uncommitted)
- [x] 2.6 Persona ↔ seed-corpus lockstep test
  (`tests/cli/test_simulate.py::TestSimulationPersonaLoads`)

## 3. CLI + dataset export

- [x] 3.1 `assistant simulate` — fixtures root option, loopback
  bind + warning, env-export printout, `uvicorn.run`
- [x] 3.2 `MemoryManager.list_interactions` (JSON-safe dicts, role
  filter, newest-first, limit guard) + `interaction_list` op in
  `telemetry/providers/base._VALID_OPS`
- [x] 3.3 `src/assistant/simulation/dataset.py` — pure
  interaction→scenario-stub conversion, filename slugging, YAML dump
  with stub header
- [x] 3.4 `assistant export-eval-dataset` — persona DB via
  MemoryManager, `--role`/`--limit`/`--output-dir`, no-database error
  path, stub files + completion reminder
- [x] 3.5 Tests — `tests/simulation/test_dataset.py`,
  `tests/test_memory_manager.py::TestListInteractions`,
  `tests/cli/test_simulate.py` (registration, env printout, mocked
  uvicorn, mocked MemoryManager export, gate-script skip/require
  contract), `tests/telemetry/test_protocol.py` vocabulary update

## 4. Spec + docs

- [x] 4.1 Spec deltas — ADDED `simulation`; MODIFIED `cli-interface`
  (new subcommand requirements), `observability` (op vocabulary),
  ADDED requirement in `memory-policy` (`list_interactions`)
- [x] 4.2 `openspec validate eval-simulation-loop --strict` passes
- [x] 4.3 CLAUDE.md — simulation/eval-gate section
- [x] 4.4 Quality gates in worktree — `uv run pytest tests/`,
  `uv run ruff check src tests`, `uv run mypy src tests`
