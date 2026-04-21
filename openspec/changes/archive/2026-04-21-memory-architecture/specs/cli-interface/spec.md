# cli-interface Specification Delta — memory-architecture

## ADDED Requirements

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
