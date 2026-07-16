# cli-interface Specification (delta)

## ADDED Requirements

### Requirement: Simulate Subcommand

The CLI SHALL provide a `simulate` subcommand that builds the
fixture-backed simulator app from a fixtures root (option
`--fixtures`/`-f`, default `evaluation/simulation/sources`) and serves
it with uvicorn on a configurable host/port (defaults `127.0.0.1` /
`8901`). Before serving it SHALL print, for every discovered source,
an `export SIM_<SOURCE>_URL=<base>/<source_name>` line matching the
simulation persona's `base_url_env` convention, plus an
`export ASSISTANT_PERSONAS_DIR=...` line when a sibling `personas/`
directory exists next to the fixtures root. An invalid or empty
fixtures root SHALL be a usage error; binding a non-loopback host
SHALL emit a warning (mirroring `serve`).

#### Scenario: Simulate is registered in the CLI group

- **WHEN** the CLI group's command map is inspected
- **THEN** it MUST contain `simulate`
- **AND** `assistant simulate --help` MUST exit 0

#### Scenario: Simulate prints the env contract before serving

- **WHEN** `assistant simulate --port 8955` runs against the seed
  corpus (with the server loop stubbed)
- **THEN** stdout MUST contain one `export SIM_<SOURCE>_URL=` line per
  seed source pointing at `http://127.0.0.1:8955/<source_name>`
- **AND** the server MUST be started on host `127.0.0.1` port `8955`

#### Scenario: Missing fixtures root is a usage error

- **WHEN** `assistant simulate --fixtures /nonexistent` is executed
- **THEN** the exit code MUST be non-zero
- **AND** the output MUST name the missing directory

### Requirement: Export Eval Dataset Subcommand

The CLI SHALL provide an `export-eval-dataset` subcommand that reads
stored interactions for a required persona (`-p`) through
`MemoryManager.list_interactions` — honoring `--role` and `--limit`
filters — and writes one gen-eval scenario stub YAML file per
interaction into `--output-dir` (default
`evaluation/datasets/exported`, created if missing). A persona without
a configured `database_url` SHALL exit 1 with an error naming the
persona; zero matching interactions SHALL print a message and exit 0
without writing files; on success the command SHALL remind the
operator that stubs require human completion before promotion into a
scenario suite.

#### Scenario: Persona without database errors

- **WHEN** `assistant export-eval-dataset -p personal` is executed and
  the persona resolves no `database_url`
- **THEN** the exit code MUST be 1
- **AND** the output MUST mention the missing `database_url`

#### Scenario: One stub file per interaction

- **WHEN** the persona database yields two interactions
- **THEN** exactly two `.yaml` stub files MUST be written to the
  output directory
- **AND** each MUST parse as a scenario with `category: regression`

#### Scenario: Role and limit filters are forwarded

- **WHEN** `assistant export-eval-dataset -p personal -r coder
  --limit 5` is executed
- **THEN** `list_interactions` MUST be called with `role="coder"` and
  `limit=5`
