# cli-interface Specification Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
