# cli-interface Specification

## Purpose
Governs the `assistant` command-line entry point: the click group with its
`run`, list, `export`, `db`, `export-memory`, and `serve` subcommands,
persona/role/harness selection flags, and the interactive REPL including
`/delegate`, teacher-method flags, and tool listing. It exists as the
primary human interface for composing a persona with a role and running it
on a chosen harness. The CLI only wires together the core library
(registries, composition, harness factory) and delegates all agent behavior
to it.
## Requirements
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

### Requirement: Teacher Method Flag

The CLI SHALL accept an optional `--method <name>` / `-m <name>`
argument whose value names a skill file (without extension) under
`roles/teacher/skills/`. The flag is valid only when the effective role
is `teacher`; supplying it with any other role SHALL raise
`click.UsageError`. Supplying a method name that is not among the
discoverable skill files SHALL also raise `click.UsageError` and
MUST list the available methods.

#### Scenario: Teacher method flag accepted with teacher role

- **WHEN** the CLI is invoked with `-p personal -r teacher --method feynman`
- **AND** `roles/teacher/skills/feynman/SKILL.md` exists
- **THEN** CLI startup MUST succeed without raising `UsageError`
- **AND** the first user-turn MUST be prefixed with a system-level
  directive instructing the agent to use the Feynman method

#### Scenario: Teacher method flag rejected with non-teacher role

- **WHEN** the CLI is invoked with `-r coder --method feynman`
- **THEN** `click.UsageError` MUST be raised
- **AND** the error message MUST contain the substring
  `"--method"` and `"teacher"`

#### Scenario: Unknown method name rejected

- **WHEN** the CLI is invoked with `-r teacher --method nonexistent`
- **AND** `roles/teacher/skills/nonexistent/SKILL.md` does NOT exist
- **THEN** `click.UsageError` MUST be raised
- **AND** the error message MUST list the available methods
  (`feynman`, `socratic`)

### Requirement: Methods REPL Command

The interactive REPL SHALL accept a `/methods` command that, when the
active role is `teacher`, lists the discoverable skill files
(filename without extension) with the currently active method marked
with a trailing `←`. When the active role is not `teacher`, the
command SHALL print a guard message and continue the REPL without
error.

#### Scenario: Teacher methods REPL command lists available methods

- **WHEN** the REPL is running with the `teacher` role active
- **AND** the user enters `/methods`
- **THEN** the output MUST list `feynman` and `socratic` on separate
  lines
- **AND** exactly one of them MUST have a trailing `←` marker if an
  active method is set
- **AND** the REPL MUST continue without error

#### Scenario: Methods command rejected when role is not teacher

- **WHEN** the REPL is running with any role other than `teacher`
  active
- **AND** the user enters `/methods`
- **THEN** the output MUST include a guard message naming the
  `teacher` role requirement
- **AND** the REPL MUST continue without error

### Requirement: Method REPL Switch

The interactive REPL SHALL accept a `/method <name>` command that,
when the active role is `teacher` and `<name>` matches an existing
skill file, updates the REPL's active method state and injects a
system-level directive into the next agent invocation instructing the
agent to summarize current progress, announce the switch, and enter
Step 1 of the new method. The command MUST NOT rebuild the harness or
agent instance (contrast with `/role <name>`). When `<name>` does not
match any skill, the REPL SHALL print an error listing valid methods
and continue without changing the active method.

#### Scenario: Teacher method REPL switch updates active method

- **WHEN** the REPL is running with the `teacher` role active and an
  active method of `feynman`
- **AND** the user enters `/method socratic`
- **THEN** the REPL's recorded active method MUST become `socratic`
- **AND** the next agent invocation's input MUST be prefixed with a
  directive mentioning `socratic` and instructing the agent to
  summarize and switch
- **AND** the harness factory MUST NOT be called again as part of the
  switch (agent instance preserved)

#### Scenario: Teacher method REPL prompt prefix reflects active method

- **WHEN** the REPL is running with the `teacher` role active and an
  active method of `feynman`
- **THEN** the prompt prefix for assistant responses MUST be
  `[Teacher:feynman]>` (case-insensitive on the method portion)

#### Scenario: Method REPL switch rejects unknown method

- **WHEN** the REPL is running with the `teacher` role active
- **AND** the user enters `/method bogus`
- **AND** `roles/teacher/skills/bogus/SKILL.md` does NOT exist
- **THEN** the REPL MUST print an error message listing valid methods
- **AND** the REPL's recorded active method MUST be unchanged
- **AND** the REPL MUST continue without error

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

#### Scenario: serve rejects persona with no default_role when -r is omitted

- **WHEN** `assistant serve -p some-persona` is executed without
  `-r`
- **AND** the persona's `default_role` field is missing or empty
- **THEN** the exit code MUST be non-zero
- **AND** stderr or stdout MUST identify the persona name and the
  missing `default_role` field

#### Scenario: serve rejects unknown harness names

- **WHEN** `assistant serve -p personal -H nonexistent` is executed
- **THEN** the exit code MUST be non-zero
- **AND** the error MUST list the available harness names

#### Scenario: serve warns when binding to a non-loopback host

- **WHEN** `assistant serve -p personal --host 0.0.0.0` is executed
  (or any non-`127.0.0.1`, non-`localhost` address)
- **THEN** the CLI MUST emit a clearly-visible warning on stderr
  before uvicorn starts, identifying that the server will be
  network-accessible without authentication
- **AND** the server MUST still start (the warning is informational,
  not a refusal — single-user, local-trust-mode is the v1 contract)

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

