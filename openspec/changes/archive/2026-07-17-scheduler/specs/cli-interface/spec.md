# cli-interface Specification (delta)

## ADDED Requirements

### Requirement: CLI daemon Subcommand

The CLI SHALL provide a `daemon` subcommand that runs the persona's
`schedules:` jobs until interrupted. It SHALL accept `-p/--persona`
(required), `-H/--harness` (optional, default `deep_agents`, SDK
harnesses only), and `--serve` with `--host`/`--port` (defaults
`127.0.0.1`/`8765`) to co-host the AG-UI SSE server in the same
process. Before starting, the command SHALL validate that the persona
declares at least one enabled scheduled job, that every enabled job's
`role` loads, and that the selected harness is an enabled SDK harness
— each failure exiting non-zero with an actionable message. The
daemon SHALL load extensions via `load_extensions_async`, perform
HTTP-tool discovery once, warn when a `model_call` budget uses the
in-memory ledger (recommending `persist: file`), stop gracefully on
SIGINT/SIGTERM, and run extension `shutdown()` hooks on teardown.

#### Scenario: Daemon is registered in the CLI group

- **WHEN** `assistant daemon --help` is executed
- **THEN** the exit code MUST be 0
- **AND** the help text MUST mention scheduled jobs

#### Scenario: Persona without schedules is a usage error

- **WHEN** `assistant daemon -p <persona>` is executed for a persona
  with no `schedules:` section
- **THEN** the exit code MUST be non-zero
- **AND** the output MUST mention the missing `schedules:` section

#### Scenario: Unknown job role fails at startup

- **WHEN** an enabled job names a role that does not exist
- **THEN** the exit code MUST be non-zero
- **AND** the error MUST name the offending job

#### Scenario: Host harness is rejected

- **WHEN** `assistant daemon -p <persona> -H claude_code` is executed
- **THEN** the exit code MUST be non-zero
- **AND** the output MUST indicate that scheduled jobs require an SDK
  harness

#### Scenario: In-memory budget ledger triggers a warning

- **WHEN** the persona declares a `model_call` budget without
  `persist: file`
- **THEN** the daemon MUST emit a warning recommending `persist: file`
  before starting
- **AND** the daemon MUST still start
