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
(optional, defaulting to `127.0.0.1`), `--port` (optional,
defaulting to `8765`), `--a2a` (optional flag, default off), and
`--mcp` (optional flag, default off). The server SHALL block until
interrupted; the exit code on `Ctrl-C` SHALL be 0. When `--a2a` is
passed, the app factory MUST be invoked with `enable_a2a=True` and
`a2a_base_url="http://<host>:<port>"` so the A2A protocol surface
(agent card + `POST /a2a/v1`) is mounted alongside the AG-UI routes
on the same server. When `--mcp` is passed, the app factory MUST be
invoked with `enable_mcp=True` so the MCP streamable-HTTP surface is
mounted at `/mcp` on the same server, and the startup output MUST
name the `/mcp` endpoint. The two flags SHALL compose. When neither
flag is present the app factory MUST be called with the legacy
`make_app(persona, role, harness)` shape and no A2A or MCP routes
registered.

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

#### Scenario: serve --a2a mounts the A2A surface

- **WHEN** `assistant serve -p personal --a2a --port 9001` is executed
- **THEN** the app factory MUST receive `enable_a2a=True` and
  `a2a_base_url="http://127.0.0.1:9001"`
- **AND** the startup output MUST name the agent-card URL

#### Scenario: serve --mcp mounts the MCP surface

- **WHEN** `assistant serve -p personal --mcp --port 9002` is executed
- **THEN** the app factory MUST receive `enable_mcp=True`
- **AND** the startup output MUST name the `/mcp` endpoint

#### Scenario: serve --a2a --mcp composes both surfaces

- **WHEN** `assistant serve -p personal --a2a --mcp` is executed
- **THEN** the app factory MUST receive `enable_a2a=True`,
  `a2a_base_url`, and `enable_mcp=True` in the same call

#### Scenario: serve without flags keeps the legacy surface

- **WHEN** `assistant serve -p personal -r coder` is executed without
  `--a2a` or `--mcp`
- **THEN** the app factory MUST be called without A2A or MCP keyword
  arguments
- **AND** requests to `/.well-known/agent-card.json`, `/a2a/v1`, and
  `/mcp` MUST return 404

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

### Requirement: Persona Hash-Extensions Subcommand

The CLI SHALL provide `assistant persona hash-extensions -p
<persona>` that hashes every `*.py` file in the persona's extensions
directory (SHA-256) and writes/overwrites the `manifest.yaml`
integrity manifest next to them, printing each written filename and
digest. When the extensions directory does not exist the command MUST
exit non-zero with an error naming the missing path. Regenerating the
manifest after an intentional extension edit is the documented
operator flow for the persona registry's verify-before-execute check.

#### Scenario: Manifest is generated for a persona

- **WHEN** `assistant persona hash-extensions -p personal` is
  executed for a persona whose extensions directory contains
  `gmail.py`
- **THEN** `manifest.yaml` MUST be written in that directory with a
  `hashes:` entry for `gmail.py`
- **AND** the output MUST list `gmail.py` with its digest

#### Scenario: Missing extensions directory fails

- **WHEN** the persona has no extensions directory on disk
- **THEN** the command MUST exit with a non-zero status
- **AND** the error output MUST name the missing directory

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

### Requirement: CLI models Command Group

The CLI SHALL provide a `models` command group with two subcommands.
`assistant models sync-catalog -p <persona> [--url <base>]` SHALL
fetch the OpenRouter `/models` catalog (default URL
`https://openrouter.ai/api/v1/models`, overridable) using the
persona-scoped credential `OPENROUTER_API_KEY` when present, write the
persona-local catalog cache file, and print the model count and cache
path; any fetch failure (network unreachable, redirect, oversize
response, HTTP error) SHALL exit non-zero with an error naming the
cause. `assistant models check-health -p <persona>` SHALL probe every
registry entry that declares a `health:` block, print one line per
entry with its healthy/unhealthy verdict and probe URL, warm the
process's shared health cache, and exit `0` when all probed entries
are healthy (or none declare health checks, with a message saying so)
and `1` when any entry is unhealthy.

#### Scenario: models group is registered

- **WHEN** `assistant models --help` is executed
- **THEN** the exit code MUST be 0
- **AND** the output MUST list `sync-catalog` and `check-health`

#### Scenario: sync-catalog writes the persona cache

- **WHEN** `assistant models sync-catalog -p <persona>` runs against
  a catalog endpoint returning two models
- **THEN** the persona's `.cache/models/catalog.json` MUST be written
  containing both model ids
- **AND** the output MUST name the cache path

#### Scenario: sync-catalog without network errors clearly

- **WHEN** the catalog URL is unreachable
- **THEN** the exit code MUST be non-zero
- **AND** the error output MUST name the transport failure

#### Scenario: check-health reports per-entry verdicts

- **WHEN** `assistant models check-health -p <persona>` runs for a
  persona with one healthy and one unhealthy health-declaring entry
- **THEN** the output MUST contain one verdict line per entry
- **AND** the exit code MUST be 1

#### Scenario: check-health with no health-declaring entries

- **WHEN** the persona's registry declares no `health:` blocks
- **THEN** the command MUST print that no entries declare health
  checks
- **AND** exit 0 without issuing any probe

### Requirement: CLI export-omnigent-agent Command

The system SHALL provide an `assistant export-omnigent-agent`
command (joining the flat export family) that renders the
Omnigent-shaped agent-definition YAML for a required `-p/--persona`,
deriving endpoint URLs from `--base-url` (default
`http://127.0.0.1:8765`), printing to stdout by default and writing
to a file when `-o/--output` is given.

#### Scenario: Definition prints to stdout

- **WHEN** `assistant export-omnigent-agent -p personal --base-url
  http://h:1` runs
- **THEN** stdout MUST be parseable YAML whose A2A RPC endpoint is
  `http://h:1/a2a/v1`

#### Scenario: Output flag writes a file

- **WHEN** the command runs with `-o agent.yaml`
- **THEN** the file MUST be written containing the unverified-schema
  header

#### Scenario: Persona is required

- **WHEN** the command runs without `-p`
- **THEN** it MUST exit nonzero with a usage error naming the persona
  option

### Requirement: CLI cleanroom Command Group

The system SHALL provide an `assistant cleanroom` command group with
four subcommands driving the P26 declassification gateway:

- `cleanroom export -p <persona> --to <audience>` — runs
  `export_shared` and prints the bundle path, id, item count, and
  profile.
- `cleanroom import -p <persona> <bundle>` — runs `import_shared` on
  a bundle file path and prints the imported/skipped counts and
  source persona.
- `cleanroom revoke -p <persona> <bundle-id>` — runs `revoke`
  (source persona only) and prints the revocation record path.
- `cleanroom sync -p <persona>` — runs `purge_revoked` and prints the
  number of purged items.

Commands needing the persona's memory database (`export`, `import`,
`sync`) MUST fail with exit code 1 and an actionable message when the
persona has no `database_url`. Guardrail selection MUST mirror the
capability resolver (truthy `guardrails:` config selects
`PolicyGuardrails`, else `AllowAllGuardrails`), and each command MUST
act under a synthesized `AgentIdentity(persona, default_role)`. Every
clean-room refusal (`CleanRoomError` and subclasses) MUST surface as
an `Error:` message with exit code 1, never a traceback.

#### Scenario: Export writes a bundle into the shared space

- **WHEN** `assistant cleanroom export -p alpha --to beta` runs for a
  persona with a matching share rule
- **THEN** the command exits 0, prints the exported item count, and a
  bundle file exists under the shared space's `beta/` directory

#### Scenario: Import and sync complete the revocation loop

- **WHEN** a consumer imports a bundle, the source persona revokes
  it, and the consumer runs `cleanroom sync`
- **THEN** the sync exits 0 and reports the purged item count
- **AND** a subsequent import of the same bundle exits 1 naming the
  revocation

#### Scenario: Missing database_url fails actionably

- **WHEN** `cleanroom export` runs for a persona without a
  `database_url`
- **THEN** the command exits 1 with a message naming the missing
  configuration

### Requirement: CLI feedback Command

The system SHALL provide an `assistant feedback -p <persona> [-r
<role>] [--prefer [category:]key=value] [TEXT]` command recording one
human `FeedbackEvent` through the persona's memory (interactions
table, `metadata.source=feedback`). At least one of `TEXT` or
`--prefer` MUST be supplied; `--prefer` attaches a structured
preference payload (`category` defaults to `general`) that later
distills into a LOW-risk `preference` proposal. The command MUST fail
with exit code 1 and an actionable message for a persona whose
learning config is falsy (dormant) or that has no `database_url`.

#### Scenario: Feedback records a labeled event

- **WHEN** `assistant feedback -p learning_lab -r coder "too wordy"`
  runs
- **THEN** the command exits 0 and one interaction row is stored with
  `metadata.source="feedback"` and subject `role:coder`

#### Scenario: Dormant persona refuses feedback

- **WHEN** `assistant feedback -p personal "nice"` runs for a persona
  without a `learning:` section
- **THEN** the command exits 1 naming the dormant learning config

### Requirement: CLI reflect Command

The system SHALL provide an `assistant reflect -p <persona>` command
running one reflection/consolidation pass and printing either the
consolidated fact key and interaction count or a nothing-new notice.
It MUST refuse (exit 1, actionable message) for dormant personas and
personas without a `database_url`.

#### Scenario: Reflect consolidates new interactions

- **WHEN** `assistant reflect -p learning_lab` runs with stored
  interactions present
- **THEN** the command exits 0 and reports the consolidated count and
  the `learning/reflection/*` fact key

### Requirement: CLI learning Command Group

The system SHALL provide an `assistant learning` command group with
four subcommands driving the P28 pipeline:

- `learning collect -p <persona> [--gate-log <file>] [--store]` —
  runs the machine collectors on demand, printing one line per event;
  `--store` additionally records them as stored feedback.
- `learning propose -p <persona> [--gate-log <file>] [--limit N]` —
  derives proposals from stored + machine feedback and writes one
  JSON file per proposal into the persona's proposals directory,
  then runs the opt-in LOW-preference auto-apply path (persisting any
  status change). Without a `database_url` it proceeds machine-only
  with a warning.
- `learning apply -p <persona> <proposal-ref> [--approved]` —
  resolves a proposal file path or id, runs the fully gated
  `apply_proposal`, and persists the applied status back to the
  proposal file.
- `learning list -p <persona>` — lists proposals with kind, risk,
  status, and target.

Every learning refusal (`LearningError` and subclasses) MUST surface
as an `Error:` message with exit code 1, never a traceback; all
subcommands MUST refuse dormant personas.

#### Scenario: Propose writes reviewable proposal files

- **WHEN** `assistant learning propose -p learning_lab --gate-log
  <log with a FAIL line>` runs
- **THEN** the command exits 0 and a `prompt_layer` proposal JSON
  file exists in the persona's proposals directory

#### Scenario: Apply is gated

- **WHEN** `assistant learning apply -p learning_lab <low-pref-id>`
  runs with a passing eval gate
- **THEN** the command exits 0, stores the preference, and the
  proposal file's status becomes `applied`
- **AND** with a failing gate the command exits 1 naming the gate

#### Scenario: MEDIUM risk needs --approved

- **WHEN** a `prompt_layer` proposal is applied without `--approved`
- **THEN** the command exits 1 naming the approval flag

### Requirement: Feedback REPL Command

The interactive REPL SHALL accept a `/feedback <text>` command
recording one human feedback event about the active role (subject
`role:<active-role>`, context `repl`) through the same pipeline as
`assistant feedback`. A missing argument prints usage; a dormant
persona or missing database prints an `Error:` line without leaving
the REPL. The commands help line MUST advertise `/feedback <text>`.

#### Scenario: REPL feedback records and continues

- **WHEN** the user enters `/feedback stop apologising`
- **THEN** one feedback event is recorded and the REPL prints a
  confirmation and keeps running

#### Scenario: Dormant persona keeps the REPL alive

- **WHEN** `/feedback x` is entered for a persona without learning
  config
- **THEN** the REPL prints an `Error:` line and continues

