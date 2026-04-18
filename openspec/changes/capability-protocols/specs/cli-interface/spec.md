# cli-interface — spec delta

## ADDED Requirements

### Requirement: CLI Export Subcommand

The CLI SHALL provide an `export` subcommand that generates host-harness
integration artifacts for a given persona, role, and host harness type.
The command SHALL accept `-p/--persona` (required), `-r/--role`
(optional, defaults to persona's `default_role`), and
`-H/--harness` (required, restricted to registered host harness names).

#### Scenario: Export generates context artifacts

- **WHEN** `assistant export -p personal -H claude_code` is executed
- **THEN** the exit code MUST be `0`
- **AND** the output MUST contain the composed system prompt for the
  personal persona with its default role

#### Scenario: Export requires persona

- **WHEN** `assistant export -H claude_code` is executed without `-p`
- **THEN** the exit code MUST be non-zero

#### Scenario: Export rejects SDK harness names

- **WHEN** `assistant export -p personal -H deep_agents` is executed
- **THEN** the exit code MUST be non-zero
- **AND** the output MUST indicate that `deep_agents` is an SDK harness,
  not a host harness

## MODIFIED Requirements

### Requirement: CLI Entry Point

The CLI SHALL use a `click.Group` with `run` as the default subcommand
(preserving current REPL behavior) and `export` as the new subcommand.
Bare `assistant -p personal` SHALL continue to work as equivalent to
`assistant run -p personal`.

#### Scenario: Bare invocation defaults to run

- **WHEN** `assistant -p personal` is executed (no subcommand)
- **THEN** the behavior MUST be identical to `assistant run -p personal`

#### Scenario: Explicit run subcommand

- **WHEN** `assistant run -p personal` is executed
- **THEN** the REPL MUST start with the personal persona
