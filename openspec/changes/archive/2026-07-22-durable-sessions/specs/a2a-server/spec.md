# a2a-server Specification (delta)

## MODIFIED Requirements

### Requirement: Approval Input-Required Bridge

The system SHALL surface guardrail approval outcomes on the A2A task
lifecycle in two modes keyed by the terminal `RunFinished.error` leaf
class name:

- **Durable suspension (P30)** — an error class in the pending set
  (which includes `PendingApprovalError`, raised when a guardrail
  `require_confirmation` decision suspends a run on a durable-session
  persona): the stream MUST emit exactly one `status-update` with
  state `input-required` and `final == true` carrying an agent
  message that points at the approvals CLI, and MUST NOT emit a
  `failed` update — the task genuinely awaits human input, and a
  follow-up message on the same `contextId` resumes the conversation
  after the decision.
- **Deny fallback (P13)** — an error class in the approval-denial set
  (which includes `ModelCallDeniedError`, raised when no durable
  approval store exists): the stream MUST emit a non-final
  `input-required` status-update carrying an agent message, followed
  by the final `failed` status-update — the observational bridge for
  personas without durable sessions.

#### Scenario: Durable suspension yields non-terminal input-required

- **WHEN** the harness terminates with
  `RunFinished(error="PendingApprovalError")`
- **THEN** the stream MUST end with a `status-update` whose state is
  `input-required` and `final == true`
- **AND** no `failed` status MUST appear anywhere in the stream
- **AND** the update's agent message MUST reference the approvals
  commands

#### Scenario: Approval denial produces input-required then failed

- **WHEN** the harness terminates with
  `RunFinished(error="ModelCallDeniedError")`
- **THEN** the stream MUST contain a `status-update` with state
  `input-required` and `final == false`
- **AND** the terminal event MUST be a `status-update` with state
  `failed` and `final == true`

#### Scenario: Ordinary failures skip input-required

- **WHEN** the harness terminates with
  `RunFinished(error="RuntimeError")`
- **THEN** no `input-required` status MUST appear in the stream

### Requirement: A2A Session Multiplexing

The system SHALL multiplex A2A tasks over the `SessionRegistry`
implementing the harness-adapter Session Registry contract (create /
lookup / expire by `thread_id`, idle-TTL expiry; relocated to
`assistant/harnesses/sessions.py`), with the A2A `contextId` equal to
the session `thread_id`. A message without a `contextId` MUST create
a fresh session (a new harness and agent built through the same
persona/role pipeline as the AG-UI lifespan, with its own
`thread_id`); a message with a known `contextId` MUST reuse that
session so consecutive tasks share conversation state. A message
whose `contextId` is not live in-process MUST be resolved through the
registry's durable re-bind path when the persona has durable sessions
configured — a known-active, un-lapsed session metadata row is
re-bound to a fresh harness with the same `thread_id` (the durable
checkpointer restores the conversation) — and MUST be rejected with
`InvalidParams` (`-32602`) only when the id is truly unknown, lapsed,
or the persona has no durable tier. Concurrent tasks on distinct
sessions MUST NOT observe each other's conversations, and runs on one
session MUST be serialized.

#### Scenario: Tasks without contextId get distinct sessions

- **WHEN** two `message/send` calls are made without `contextId`
- **THEN** the returned tasks MUST carry distinct `contextId` values
- **AND** each MUST have executed on its own harness instance

#### Scenario: Known contextId reuses the session

- **WHEN** a second message is sent with the `contextId` returned by a
  prior task
- **THEN** it MUST execute on the same harness instance as the first
- **AND** the two tasks MUST have distinct task `id` values

#### Scenario: Expired contextId is re-bound on a durable persona

- **WHEN** the durable tier is configured and a session is expired
  in-process
- **AND** a message references that session's `contextId`
- **THEN** the handler MUST re-bind a fresh harness to the same
  `thread_id` and run the task on it
- **AND** the task MUST complete normally

#### Scenario: Unknown contextId is rejected

- **WHEN** a message references a `contextId` that was never created
  (or has lapsed durably, or the persona has no durable tier)
- **THEN** the response MUST carry `error.code == -32602`
