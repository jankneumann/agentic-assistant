# cli-interface Specification (delta)

## MODIFIED Requirements

### Requirement: Harness Selection via -h Flag

The CLI SHALL accept `-H/--harness` to select the harness backend and
SHALL default it to the `auto` sentinel on the `run`, `serve`, and
`daemon` subcommands. `auto` SHALL be resolved through
`select_harness(persona, role)` after the persona and role are
loaded (explicit `-H` names bypass routing and dispatch directly to
the harness factory), and the resolved concrete name SHALL be what
reaches `create_harness` — the factory never receives `auto`. The
CLI SHALL surface factory validation failures (unknown harness,
harness not enabled, no enabled SDK harness under `auto`) as usage
errors.

#### Scenario: Default harness resolves via auto routing

- **WHEN** `-H/--harness` is omitted on `assistant run`
- **AND** the persona enables only `deep_agents` among SDK harnesses
  and declares no routing rules
- **THEN** the harness passed to the factory MUST equal
  `"deep_agents"` (the `auto` resolution result)

#### Scenario: Explicit harness bypasses routing

- **WHEN** `assistant run -p personal -H deep_agents` is executed
- **THEN** the harness passed to the factory MUST equal
  `"deep_agents"` regardless of any `harnesses.routing:` rules

#### Scenario: -h ms_agent_framework surfaces the enablement error

- **WHEN** `assistant -p personal -H ms_agent_framework` is executed
  with the MS AF harness disabled in the persona config
- **THEN** the CLI MUST exit non-zero
- **AND** stderr or stdout MUST contain a message indicating the
  harness is not enabled for the persona

### Requirement: CLI daemon Subcommand

The CLI SHALL provide a `daemon` subcommand that runs the persona's
`schedules:` jobs until interrupted. It SHALL accept `-p/--persona`
(required), `-H/--harness` (optional, default `auto`, SDK harnesses
only — `auto` resolves per job through `select_harness` against the
job's role, and a job's `harness:` override takes precedence over the
`-H` value), and `--serve` with `--host`/`--port` (defaults
`127.0.0.1`/`8765`) to co-host the AG-UI SSE server in the same
process (under `auto`, the served app's harness resolves against the
persona's `default_role`). Before starting, the command SHALL
validate that the persona declares at least one enabled scheduled
job, that every enabled job's `role` loads, and that every enabled
job's effective harness resolves to an enabled SDK harness — each
failure exiting non-zero with an actionable message naming the job.
The daemon SHALL load extensions via `load_extensions_async`, perform
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

#### Scenario: Per-job harness override is validated at startup

- **WHEN** an enabled job declares `harness: claude_code`
- **AND** `assistant daemon -p <persona>` is executed
- **THEN** the exit code MUST be non-zero
- **AND** the error MUST name the offending job

#### Scenario: In-memory budget ledger triggers a warning

- **WHEN** the persona declares a `model_call` budget without
  `persist: file`
- **THEN** the daemon MUST emit a warning recommending `persist: file`
  before starting
- **AND** the daemon MUST still start
