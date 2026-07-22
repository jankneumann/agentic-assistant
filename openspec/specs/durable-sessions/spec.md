# durable-sessions Specification

## Purpose
TBD - created by archiving change durable-sessions. Update Purpose after archive.
## Requirements
### Requirement: Sessions Configuration Section

The system SHALL parse a persona `sessions:` section at persona load
into a typed `SessionsConfig`: `durable` (boolean, default false),
`session_ttl_seconds` (durable-session validity window measured from
last use; 0 = never lapses), and `approval_ttl_seconds`
(pending-approval validity window; 0 = never lapses). Unknown keys
and mis-typed values MUST fail persona load with an actionable error
naming the offender. A persona without the section (or with
`durable: false`) MUST keep every in-memory default: `InMemorySaver`
conversations, in-process-only session registries, P13
deny-on-`require_confirmation` guardrail behavior, and no durable
audit sink. `durable: true` without a resolvable persona database url
MUST fail actionably wherever the durable tier is constructed
(checkpointer resolution, store resolution, CLI) — declared
durability never silently degrades.

#### Scenario: Absent section keeps every in-memory default

- **WHEN** a persona declares no `sessions:` section
- **THEN** the parsed config MUST be falsy
- **AND** durable store resolution MUST return the no-tier signal

#### Scenario: Valid section parses

- **WHEN** `sessions: {durable: true, session_ttl_seconds: 120}` is
  declared
- **THEN** persona load MUST produce a truthy `SessionsConfig` with
  the TTL parsed

#### Scenario: Invalid section fails persona load actionably

- **WHEN** `sessions: {bogus: 1}` is declared
- **THEN** persona load MUST raise an error naming the unknown key

#### Scenario: Durable without a database url fails actionably

- **WHEN** `sessions: {durable: true}` is declared and no database
  url resolves
- **THEN** durable store resolution MUST raise an error naming the
  missing database configuration

### Requirement: Durable Store Tier

The system SHALL provide a per-persona durable store tier on the
persona DB, built lazily and cached per persona: a session-metadata
store (`sessions` table: thread_id, persona, role, harness,
created_at, last_used, expires_at, status), an approvals store
(`approvals` table persisting the guardrail-provider
`ApprovalRequest` shape including the acting identity, risk tier, and
lifecycle fields), a DB spend ledger (`guardrail_spend` table), and a
durable audit log (`audit_log` table). The four tables SHALL be owned
by alembic migration 002 (applied via `assistant db upgrade`); the
LangGraph checkpointer's own tables are package-owned via its
`setup()` and MUST NOT be managed by the assistant's migrations
(separate concerns). Store implementations are synchronous (short
queries over a sync engine; urls normalized to the psycopg dialect)
because their consumers — the `BudgetLedger` protocol and the
guardrail confirmation hooks — are synchronous, and each Postgres
store SHALL have an in-memory twin with identical semantics for tests
and fakes.

#### Scenario: Approvals round-trip through the store

- **WHEN** a pending `ApprovalRequest` with an attached identity is
  created, decided, and consumed through the Postgres store
  implementation
- **THEN** each read MUST reproduce the request's action, metadata,
  identity, risk, and lifecycle fields
- **AND** the lifecycle MUST enforce first-decision-wins and
  consume-exactly-once

#### Scenario: Session metadata rows are re-bind evidence

- **WHEN** a session row is recorded and later touched with a TTL
  window
- **THEN** reads MUST reflect the refreshed `last_used` and slid
  `expires_at`
- **AND** `mark_expired` MUST flip the row's status so resolution
  rejects it

#### Scenario: Store resolution is cached per persona

- **WHEN** the durable tier is resolved twice for the same durable
  persona
- **THEN** the same store instances MUST be returned
- **AND** resolution MUST register the persona's durable audit sink

### Requirement: Durable Audit Trail

The system SHALL append guardrail decision records to the persona's
durable audit log when durable sessions are configured: every
identity-carrying guardrail decision emitted through the audit seam
MUST also be appended to the registered sink (persona, event, action
type, resource, acting role, decision outcome, reason, attributes),
and every CLI approval decision MUST append an `approval.decision`
record. Telemetry spans continue unchanged regardless of durability.
Appends are best-effort: a missing sink is a no-op and a failing sink
logs a WARNING — the audit trail never changes enforcement outcomes.

#### Scenario: Identity-carrying decision is appended

- **WHEN** a guardrail decision for an identity-carrying request is
  audited on a persona with a registered durable sink
- **THEN** one audit record with the decision outcome and resource
  MUST be appended

#### Scenario: Identity-less requests are not appended

- **WHEN** a decision for a request without an identity is audited
- **THEN** no durable audit record MUST be appended (parity with the
  span rule)

#### Scenario: Sink failure never changes enforcement

- **WHEN** the durable sink raises on append
- **THEN** the guardrail decision outcome MUST be unaffected
- **AND** a WARNING MUST be logged

