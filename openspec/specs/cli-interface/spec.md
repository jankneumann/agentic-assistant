# cli-interface Specification

## Purpose
TBD - created by archiving change bootstrap-vertical-slice. Update Purpose after archive.
## Requirements
### Requirement: CLI Entry Point

The system SHALL provide an `assistant` CLI entry point (installed via
`[project.scripts]`) that accepts `-p/--persona`, `-r/--role`,
`-H/--harness`, `--list-personas`, and `--list-roles` options.
(Note: uppercase `-H` is used because Click reserves lowercase `-h` for
`--help` by convention; overriding that would regress against every other
Click-based CLI.)

#### Scenario: Entry point is installed

- **WHEN** `uv run assistant --help` is executed against the synced venv
- **THEN** the exit code MUST be `0`
- **AND** the output MUST contain the strings `--persona`, `--role`, and
  `--harness`

### Requirement: List Personas Lists Initialized Submodules

The `--list-personas` flag SHALL print each persona returned by
`PersonaRegistry.discover()`, one per line.

#### Scenario: Only initialized personas are listed

- **WHEN** only `personas/personal/persona.yaml` exists
- **AND** `assistant --list-personas` is executed
- **THEN** the output MUST contain the line `"personal"`
- **AND** the output MUST NOT contain the string `"work"`
- **AND** the output MUST NOT contain the string `"_template"`

### Requirement: List Roles Requires Persona

The `--list-roles` flag SHALL require `-p/--persona` and print each role
returned by `RoleRegistry.available_for_persona(persona)`, one per line.

#### Scenario: Listing roles without persona errors

- **WHEN** `assistant --list-roles` is executed without `-p`
- **THEN** the exit code MUST be non-zero

#### Scenario: Listing roles for personal persona

- **WHEN** `assistant -p personal --list-roles` is executed
- **AND** `roles/` contains `researcher`, `chief_of_staff`, `writer`
- **AND** the personal persona's `disabled_roles` is empty
- **THEN** the output MUST contain each of `researcher`, `chief_of_staff`,
  `writer`

### Requirement: Default Role Fallback

When `-r/--role` is not specified, the CLI SHALL use the persona's
`default_role`.

#### Scenario: Default role used when -r omitted

- **WHEN** `persona.default_role == "chief_of_staff"`
- **AND** the CLI is invoked with `-p personal` only
- **THEN** the loaded role MUST have `name == "chief_of_staff"`

### Requirement: Unknown Persona Produces Helpful Error

The CLI SHALL exit with non-zero status and a message listing available
personas when `-p/--persona` names a persona that does not exist.

#### Scenario: Unknown persona fails with hint

- **WHEN** `assistant -p nonexistent --list-roles` is executed
- **THEN** the exit code MUST be non-zero
- **AND** stderr or stdout MUST contain the string `"Available:"`

### Requirement: Harness Selection via -h Flag

The CLI SHALL accept `-H/--harness` to select the harness backend, dispatching
to the harness factory, and SHALL surface the MS Agent Framework harness's
`NotImplementedError` to the user as a clear error when selected before P5
lands.

#### Scenario: Default harness is deep_agents

- **WHEN** `-H/--harness` is omitted
- **THEN** the harness passed to the factory MUST equal `"deep_agents"`

#### Scenario: -h ms_agent_framework surfaces the stub error

- **WHEN** `assistant -p personal -h ms_agent_framework` is executed (with the
  MS AF harness enabled in config)
- **THEN** the CLI MUST exit non-zero
- **AND** stderr or stdout MUST contain a message indicating the MS Agent
  Framework harness is not yet implemented

### Requirement: Interactive REPL Loop

The CLI SHALL provide an interactive REPL when started without `--list-*`
flags, reading user input line by line, invoking the harness, and printing
the response prefixed with the active role's display name; typing `quit` or
`exit` SHALL terminate the loop.

#### Scenario: REPL echoes harness response

- **WHEN** a stub harness whose `invoke` returns `"hello back"` is injected
- **AND** the user types `"hi"` then `"quit"`
- **THEN** the output MUST contain `"hello back"`
- **AND** the CLI MUST exit with status `0`

#### Scenario: /role switches the active role mid-session

- **WHEN** the user types `/role writer` during the REPL
- **AND** the role `writer` is available for the active persona
- **THEN** the next response line MUST be prefixed with `"Writer"` (the
  writer role's `display_name`)

#### Scenario: /role with unknown role prints error, keeps current role

- **WHEN** the user types `/role nonexistent`
- **THEN** the current role MUST NOT change
- **AND** the output MUST contain the string `"Error"`

### Requirement: Delegation via /delegate Command

The CLI SHALL parse `/delegate <sub-role> <task text>` during the REPL, invoke
the `DelegationSpawner`, and print the sub-agent's response prefixed with the
sub-role name.

#### Scenario: Valid delegation returns sub-agent output

- **WHEN** parent role allows `writer` as a sub-role
- **AND** the user types `/delegate writer draft an email`
- **AND** the stub harness's `spawn_sub_agent` returns `"draft text"`
- **THEN** the output MUST contain `"draft text"`
- **AND** the output MUST contain the sub-role prefix `"[writer]"`

#### Scenario: Invalid /delegate usage prints usage hint

- **WHEN** the user types `/delegate` with fewer than two arguments
- **THEN** the output MUST contain the substring `"Usage:"`
- **AND** the REPL MUST remain active

