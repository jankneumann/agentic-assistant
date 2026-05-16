## MODIFIED Requirements

### Requirement: CLI Entry Point

The CLI SHALL use a `click.Group` with `run` as the default subcommand
(preserving current REPL behavior), `export` as the existing
host-harness export subcommand, and `serve` as the new subcommand that
mounts a FastAPI ASGI application emitting AG-UI events over SSE. The
CLI SHALL additionally accept a `--list-tools` flag at the group level
that performs HTTP tool discovery and prints registered tools. Bare
`assistant -p personal` SHALL continue to work as equivalent to
`assistant run -p personal`.

#### Scenario: Bare invocation defaults to run

- **WHEN** `assistant -p personal` is executed (no subcommand)
- **THEN** the behavior MUST be identical to `assistant run -p personal`

#### Scenario: Explicit run subcommand

- **WHEN** `assistant run -p personal` is executed
- **THEN** the REPL MUST start with the personal persona

#### Scenario: List-tools flag short-circuits REPL

- **WHEN** `assistant -p personal --list-tools` is executed
- **THEN** the REPL MUST NOT start
- **AND** the process MUST exit after printing the tool catalog

#### Scenario: Serve subcommand is registered in the CLI group

- **WHEN** `assistant --help` is executed
- **THEN** the output MUST list `serve` as an available subcommand
- **AND** the description MUST mention SSE or AG-UI

## ADDED Requirements

### Requirement: CLI serve Subcommand

The CLI SHALL provide a `serve` subcommand that mounts a FastAPI ASGI
application binding a single persona and role for the lifetime of the
server process. The subcommand SHALL accept `-p/--persona` (required),
`-r/--role` (optional, defaulting to the persona's `default_role`),
`-H/--harness` (optional, defaulting to `deep_agents`), `--host`
(optional, defaulting to `127.0.0.1`), and `--port` (optional,
defaulting to `8765`). The server SHALL block until interrupted; the
exit code on `Ctrl-C` SHALL be 0.

#### Scenario: serve binds the supplied persona and role at startup

- **WHEN** `assistant serve -p personal -r teacher --port 8001` is
  executed
- **THEN** the FastAPI app's lifespan MUST construct a single harness
  instance with persona `personal` and role `teacher`
- **AND** the constructed harness MUST be stored on `app.state.harness`
  before the server accepts requests

#### Scenario: serve defaults host to 127.0.0.1

- **WHEN** `assistant serve -p personal` is executed without `--host`
- **THEN** the underlying uvicorn server MUST bind to `127.0.0.1`,
  not `0.0.0.0`

#### Scenario: serve uses persona default_role when -r is omitted

- **WHEN** `assistant serve -p personal` is executed without `-r`
- **AND** the personal persona's `default_role` is `assistant`
- **THEN** the constructed harness MUST be initialized with the
  `assistant` role

#### Scenario: serve rejects unknown personas with non-zero exit

- **WHEN** `assistant serve -p nonexistent` is executed
- **THEN** the exit code MUST be non-zero
- **AND** stderr or stdout MUST contain the string `"Available:"`

#### Scenario: serve rejects host harness names

- **WHEN** `assistant serve -p personal -H claude_code` is executed
- **THEN** the exit code MUST be non-zero
- **AND** the output MUST indicate that `claude_code` is a host
  harness and cannot serve over SSE

#### Scenario: Ctrl-C exits with status 0

- **WHEN** the running server receives SIGINT
- **THEN** the lifespan shutdown MUST run cleanly
- **AND** the process MUST exit with status 0
