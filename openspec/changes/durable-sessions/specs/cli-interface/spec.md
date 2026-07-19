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
