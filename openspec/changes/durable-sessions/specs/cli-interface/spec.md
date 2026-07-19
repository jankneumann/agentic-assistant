# cli-interface Specification (delta)

## ADDED Requirements

### Requirement: CLI approvals Command Group

The system SHALL provide an `assistant approvals` command group
driving the P30 approval interrupt/resume flow, available only for
personas with durable sessions (`sessions: {durable: true}` + a
resolvable database url — otherwise every subcommand exits 1 with an
actionable message naming the required configuration):

- `approvals list -p <persona> [--all]` — lists pending approval
  requests (id, status, risk, action, resource, request message);
  `--all` includes decided/consumed/expired records.
- `approvals approve <id> -p <persona> [--justification TEXT]` —
  records an approve decision.
- `approvals deny <id> -p <persona> [--justification TEXT]` —
  records a deny decision.

Decisions are first-decision-wins (a second decision for the same id
exits 1 naming the existing status), stamp the decider and
justification on the record, and MUST be audited: an
`approval.decision` telemetry span plus a durable `audit_log` row.
The command output MUST tell the operator to retry the suspended
operation (the decision is consumed exactly once by the retry).

#### Scenario: Pending approvals are listed

- **WHEN** a pending approval exists for the persona
- **AND** `assistant approvals list -p <persona>` runs
- **THEN** the output MUST include the approval id, its action type,
  and the pending status

#### Scenario: Approve records the decision and audit trail

- **WHEN** `assistant approvals approve <id> -p <persona>
  --justification ok` runs against a pending approval
- **THEN** the stored record MUST become `approved` with the decider
  and justification stamped
- **AND** an `approval.decision` audit record MUST be appended

#### Scenario: Duplicate decision is rejected

- **WHEN** an already-approved id is denied via the CLI
- **THEN** the command MUST exit 1 naming the existing decision
- **AND** the stored record MUST be unchanged

#### Scenario: Non-durable persona gets an actionable refusal

- **WHEN** `assistant approvals list -p <persona>` runs for a persona
  without durable sessions
- **THEN** the command MUST exit 1 naming the `sessions: {durable:
  true}` requirement

### Requirement: db upgrade Provisions the Durable Checkpointer Schema

The system SHALL extend `assistant db upgrade` with an optional
`--persona/-p` option: after alembic migrations succeed, when the
named persona declares `sessions: {durable: true}`, the command SHALL
run the langgraph-checkpoint-postgres `setup()` against the persona's
database so one idempotent operator command provisions both schema
owners (alembic owns the assistant's tables; the checkpointer package
owns and versions its own — ownership is deliberately NOT merged into
alembic; owner review 2026-07-19). A non-durable persona SHALL be
reported as not requiring the checkpointer schema; a durable persona
without a resolvable database url SHALL fail with an actionable error.

#### Scenario: Durable persona provisions both schema owners

- **WHEN** `assistant db upgrade -p <persona>` runs for a persona with
  `sessions: {durable: true}` and a resolved database url
- **THEN** alembic migrations run to head
- **AND** the checkpointer package's `setup()` is invoked against the
  persona database exactly once for the command

#### Scenario: Non-durable persona skips checkpointer provisioning

- **WHEN** `assistant db upgrade -p <persona>` runs for a persona
  without a truthy `sessions:` section
- **THEN** alembic migrations still run
- **AND** the command reports the checkpointer schema is not required
  without contacting the database for it

#### Scenario: Durable persona without database url fails actionably

- **WHEN** `assistant db upgrade -p <persona>` runs for a persona
  declaring `sessions.durable` with no resolvable database url
- **THEN** the command exits nonzero naming the persona and the
  missing database url
