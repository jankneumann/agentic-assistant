# cli-interface Specification

## Purpose
TBD - created by archiving change bootstrap-vertical-slice. Update Purpose after archive.
## Requirements
### Requirement: CLI Entry Point

The CLI SHALL use a `click.Group` with `run` as the default subcommand
(preserving current REPL behavior) and `export` as the existing
host-harness export subcommand. The CLI SHALL additionally accept a
`--list-tools` flag at the group level that performs HTTP tool
discovery and prints registered tools. Bare `assistant -p personal`
SHALL continue to work as equivalent to `assistant run -p personal`.

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

### Requirement: CLI db Command Group

The system SHALL add a `db` command group to the CLI with `upgrade`
and `downgrade` subcommands for Alembic migration management.

#### Scenario: db upgrade runs migrations to head

- **WHEN** `assistant db upgrade` is invoked
- **THEN** Alembic MUST run all pending migrations to head
- **AND** the command MUST exit with code 0 on success

#### Scenario: db upgrade fails gracefully on unreachable database

- **WHEN** `assistant db upgrade` is invoked and the database is
  unreachable
- **THEN** the command MUST exit non-zero with an error message
  identifying the failure cause

#### Scenario: db downgrade rolls back to revision

- **WHEN** `assistant db downgrade <revision>` is invoked with a valid
  revision identifier
- **THEN** Alembic MUST roll back to the specified revision

#### Scenario: db downgrade fails gracefully on unreachable database

- **WHEN** `assistant db downgrade <revision>` is invoked and the
  database is unreachable
- **THEN** the command MUST exit non-zero with an error message
  identifying the failure cause

### Requirement: CLI export-memory Command

The system SHALL add an `export-memory` command that generates
structured Markdown from the persona's memory backends.

#### Scenario: export-memory generates memory content

- **WHEN** `assistant export-memory -p personal` is invoked
- **THEN** it MUST output structured Markdown to stdout
- **AND** the output MUST be UTF-8 encoded ending with a single
  trailing newline

#### Scenario: export-memory requires persona flag

- **WHEN** `assistant export-memory` is invoked without `-p`
- **THEN** it MUST exit non-zero with an error indicating persona
  is required

#### Scenario: export-memory fails when persona has no database

- **WHEN** `assistant export-memory -p personal` is invoked and the
  persona has `database_url=""` (empty)
- **THEN** it MUST exit non-zero with an informative error indicating
  no database is configured for the persona

### Requirement: List Tools Prints Discovered HTTP Tools

The `--list-tools` flag SHALL print each tool registered by
`discover_tools(persona.tool_sources)`, grouped by source, with the
tool name, description, and input schema field names. Exit code SHALL
be `0` when all sources succeed, `1` when at least one source fails
discovery.

#### Scenario: Lists tools grouped by source

- **WHEN** `assistant -p <persona> --list-tools` is executed with two
  configured sources each exposing two operations
- **THEN** stdout MUST contain one header line per source
- **AND** four tool entries total (two under each source header)

#### Scenario: Exit code 1 when a source fails

- **WHEN** one configured source's OpenAPI endpoint returns HTTP 500
- **AND** `--list-tools` is executed
- **THEN** the exit code MUST be 1
- **AND** stdout or stderr MUST name the failing source and reason

#### Scenario: No tool sources configured

- **WHEN** the persona has `tool_sources: {}`
- **AND** `--list-tools` is executed
- **THEN** stdout MUST contain `"No tool_sources configured."`
- **AND** the exit code MUST be 0

