# simulation Specification

## Purpose
TBD - created by archiving change eval-simulation-loop. Update Purpose after archive.
## Requirements
### Requirement: Fixture-Backed Simulator Server

The system SHALL provide a simulator app factory in
`src/assistant/simulation/server.py` that builds a FastAPI application
from a fixtures root directory. The fixtures root SHALL contain either
a single source (a `routes.yaml` manifest in the root itself) or one
immediate subdirectory per simulated source, each with its own
`routes.yaml`. Each manifest SHALL declare a non-empty `routes` list
whose entries carry `operation_id` (valid identifier, unique within
the source), `method` (one of get/post/put/patch/delete,
case-insensitive), `path` (leading `/`), and `response_file`
(resolving inside the source directory), with optional `status_code`,
`summary`, `description`, and query `parameters` (name, description,
required). Manifest violations and unparseable response files SHALL
raise `ValueError` naming the offending manifest or file at app-build
time, never at request time.

#### Scenario: Multi-source root builds one mount per source

- **WHEN** `make_simulator_app(root)` is called on a root whose
  subdirectories `alpha/` and `beta/` each contain a valid
  `routes.yaml`
- **THEN** the app MUST serve `GET /health` returning HTTP 200 with a
  JSON body whose `sources` mapping contains keys `alpha` and `beta`
- **AND** each source MUST be mounted at `/<source_name>`

#### Scenario: Missing response file fails at build time

- **WHEN** a manifest route references a `response_file` that does not
  exist
- **THEN** loading the source MUST raise `ValueError` naming the file

#### Scenario: Response file escaping the source directory is rejected

- **WHEN** a manifest route's `response_file` resolves outside its
  source directory (e.g. `../outside.json`)
- **THEN** loading the source MUST raise `ValueError`

#### Scenario: Sentinel comment lines are stripped from responses

- **WHEN** a response file begins with one or more `//`-prefixed lines
  (the `FIXTURE_GRAPH_RESPONSE_v1` convention from
  `tests/fixtures/graph_responses/`)
- **THEN** the served payload MUST be the JSON document with those
  leading comment lines removed

### Requirement: Simulator Discovery Compatibility

Each simulated source SHALL expose an OpenAPI 3.x document at
`/<source_name>/openapi.json` in which every declared route appears
with its manifest `operation_id` as the OpenAPI `operationId` and its
declared query parameters as OpenAPI parameters, such that the
existing `assistant.http_tools.discovery.discover_tools` consumes the
source unchanged with `base_url` set to the source mount URL. Routes
SHALL return their canned JSON payload with the declared status code
regardless of query parameter values; a declared `required` parameter
that is missing SHALL yield HTTP 422.

#### Scenario: Existing discovery registers simulated tools

- **WHEN** `discover_tools({"ms_graph": {"base_url":
  "<simulator>/ms_graph", ...}}, client=...)` runs against a running
  simulator built from the seed corpus
- **THEN** the registry MUST contain a tool named
  `ms_graph:get_my_profile`
- **AND** invoking that tool MUST return the canned fixture payload

#### Scenario: Declared parameters surface in the tool args schema

- **WHEN** a simulated route declares a query parameter named `query`
- **THEN** the discovered tool's args schema MUST expose a `query`
  field

#### Scenario: Canned response is parameter-independent

- **WHEN** the same simulated route is requested twice with different
  query parameter values
- **THEN** both responses MUST carry the identical canned payload

### Requirement: Simulation Persona

The system SHALL ship a public simulation persona at
`evaluation/simulation/personas/sim/persona.yaml` — loaded via
`ASSISTANT_PERSONAS_DIR=evaluation/simulation/personas` with no
persona-registry code changes — whose `tool_sources` resolve base URLs
from `SIM_<SOURCE_NAME_UPPERCASED>_URL` environment variables, one per
directory in the seed corpus `evaluation/simulation/sources/`. The
persona SHALL declare no database, no auth provider config, and no
extensions, and its declared tool sources SHALL stay in lockstep with
the seed corpus source directories. The seed corpus SHALL simulate
every `content_analyzer:*` and `coding_tools:*` tool name that any
public role under `roles/` declares in `preferred_tools`.

#### Scenario: Sim persona loads through the standard registry

- **WHEN** `PersonaRegistry(personas_dir="evaluation/simulation/personas").load("sim")`
  is called with the `SIM_*_URL` env vars set
- **THEN** the persona MUST load with every tool source's `base_url`
  resolved from its env var
- **AND** `database_url` MUST be empty and `extensions` MUST be `[]`

#### Scenario: Role preferred tools are simulated

- **WHEN** any `roles/*/role.yaml` lists a `preferred_tools` entry for
  a source that the seed corpus simulates
- **THEN** the seed corpus MUST declare a route whose
  `source:operation_id` name equals that entry

### Requirement: Eval Gate Script

The system SHALL provide `evaluation/run-gate.sh`, which runs the
simulation scenario suites (`evaluation/simulation/scenarios/`)
through an EXTERNAL gen-eval installation (per ADR 0006 gen-eval is a
consumer of this repo, never a dependency) located via the
`GEN_EVAL_PROJECT` environment variable with a sibling-checkout
default, and exits nonzero when any scenario fails. When gen-eval is
unavailable — the project directory missing, or present but not
runnable (verified by an invocation probe, so offline stub checkouts
count as unavailable rather than as scenario failures) — the script
SHALL exit 0 with a clear SKIP message unless
`EVAL_GATE_REQUIRE=1` is set, in which case it SHALL exit nonzero.
Before invoking gen-eval the script SHALL export
`ASSISTANT_PERSONAS_DIR` and one `SIM_<SOURCE>_URL` per seed-corpus
source directory.

#### Scenario: Advisory skip without the tools-repo checkout

- **WHEN** `run-gate.sh` runs with `GEN_EVAL_PROJECT` pointing at a
  nonexistent directory and `EVAL_GATE_REQUIRE` unset
- **THEN** the exit code MUST be 0
- **AND** stdout MUST contain `SKIP`

#### Scenario: Non-runnable checkout counts as unavailable

- **WHEN** `run-gate.sh` runs with `GEN_EVAL_PROJECT` pointing at a
  directory where gen-eval cannot be invoked and `EVAL_GATE_REQUIRE`
  unset
- **THEN** the exit code MUST be 0
- **AND** stdout MUST contain `SKIP`

#### Scenario: Required mode fails hard

- **WHEN** `run-gate.sh` runs with gen-eval unavailable and
  `EVAL_GATE_REQUIRE=1`
- **THEN** the exit code MUST be nonzero

### Requirement: Eval Dataset Export Conversion

The system SHALL provide pure conversion functions in
`src/assistant/simulation/dataset.py` that turn interaction records
(the dict shape returned by `MemoryManager.list_interactions`) into
gen-eval-compatible scenario YAML **stubs**: one scenario per
interaction with `category: regression`, a provenance `source` block
(persona, interaction id, role, recorded_at, metadata), a `todo`
marker, and a single placeholder `/chat` replay step whose message
begins with `TODO:`. Serialization helpers SHALL produce a
filesystem-safe file name per scenario and YAML output prefixed with a
comment header describing the human completion steps.

#### Scenario: One regression stub per interaction with provenance

- **WHEN** `interactions_to_scenarios("personal", records)` is called
  with two interaction records
- **THEN** it MUST return two scenarios with distinct ids
- **AND** each scenario's `source.exported_from` MUST equal
  `"interactions"` and `source.persona` MUST equal `"personal"`

#### Scenario: Stub YAML round-trips

- **WHEN** `dump_scenario_yaml(scenario)` output is parsed with a YAML
  loader
- **THEN** the parsed document MUST equal the input scenario dict

