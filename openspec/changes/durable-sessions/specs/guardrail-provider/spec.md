# guardrail-provider Specification (delta)

## MODIFIED Requirements

### Requirement: Approval Interrupt and Resume

The system SHALL consume `ActionDecision.require_confirmation`: when a
`GuardrailProvider` returns a decision with
`require_confirmation=True` for a persona with durable sessions
(`sessions: {durable: true}` + a resolvable database url), the
operation MUST suspend instead of proceeding or failing: an
`ApprovalRequest` — risk-tiered from `declare_risk` — MUST be
persisted to the durable approvals store and a typed
`PendingApprovalError` carrying the approval id MUST propagate to the
serving layer (A2A: a real non-terminal `input-required` task state;
AG-UI: the error class on `RunErrorEvent`; CLI: printed resume
instructions). Because requests and decisions are durable rows, the
approval round-trip MUST survive process restarts.

Resume is retry-shaped (v1): a decision recorded via `assistant
approvals approve|deny <id>` marks the request resolved (first
decision wins), and the retried operation MUST consult resolved
approvals BEFORE re-checking — an approve decision executes the
blocked action exactly once (the approval is consumed), a deny
decision surfaces the denial (with any justification) to the caller
and is also consumed, and a retry while the request is still pending
MUST re-raise the SAME approval id rather than filing a duplicate.
Every request/decision pair (approval id, action, risk, decider,
justification, timestamps) MUST be recorded in the audit trail
(telemetry span + durable audit row). Checkpoint-level mid-run
resume — waking the exact suspended LangGraph run — is a recorded
follow-up; the durable checkpointer already preserves the suspended
thread's state for the retry.

Where durable sessions are NOT configured, every
`require_confirmation` site MUST preserve its pre-P30 deny behavior
(approvals need the persona DB).

#### Scenario: require_confirmation suspends instead of executing

- **WHEN** `check_action` returns
  `ActionDecision(allowed=True, require_confirmation=True)` for an
  action on a durable-session persona
- **THEN** the action MUST NOT execute
- **AND** a pending `ApprovalRequest` MUST be persisted
- **AND** a typed `PendingApprovalError` referencing the approval id
  MUST propagate to the caller

#### Scenario: Suspend survives a restart

- **WHEN** an operation is suspended awaiting approval
- **AND** the serving process restarts before the decision arrives
- **THEN** the pending request MUST still be listable and decidable
- **AND** delivering the decision afterwards MUST let the retried
  operation resolve against it

#### Scenario: Approved decision resumes and executes exactly once

- **WHEN** an approve decision is delivered for a pending
  `approval_id`
- **AND** the suspended operation is retried
- **THEN** the blocked action MUST execute
- **AND** the approval MUST be consumed so a further retry suspends
  with a FRESH request rather than reusing the decision

#### Scenario: Denied decision surfaces without executing

- **WHEN** a deny decision is delivered for a pending `approval_id`
- **AND** the operation is retried
- **THEN** the blocked action MUST NOT execute
- **AND** the retry MUST surface the denial (and any justification)
  to the caller

#### Scenario: Duplicate decisions are idempotent

- **WHEN** two decisions arrive for the same `approval_id`
- **THEN** only the first MUST take effect
- **AND** the second MUST be rejected and recorded, not replayed

#### Scenario: Pending retry reuses the same request

- **WHEN** a suspended operation is retried before any decision
- **THEN** the same `approval_id` MUST be re-raised
- **AND** no duplicate pending request MUST be created

#### Scenario: Without durable sessions the deny fallback holds

- **WHEN** `require_confirmation` fires for a persona without durable
  sessions
- **THEN** the operation MUST be refused with the pre-P30 denial
  error naming the confirmation requirement

### Requirement: Guardrail Action Policies

The system SHALL evaluate `guardrails.policies` in declaration order
with first-match-wins semantics: a policy matches when its
`action_type` equals the request's action type (or is `"*"`), its
`resource` glob matches the request's resource, and its optional
identity-aware dimensions (P25 agent-iam, additive) are satisfied:

- `role` (default `"*"`) — a glob matched against the acting role:
  the request's `identity.role` when an `AgentIdentity` is attached,
  else the plain `ActionRequest.role` field;
- `min_chain_depth` (default `0` = no constraint) — the policy only
  matches requests whose identity carries at least this many
  delegation hops; a non-zero value MUST NOT match a request without
  an identity (depth cannot be established, so evaluation skips to
  the next policy rather than matching or denying).

Unknown policy keys MUST fail parse with an actionable error.
Effects: `deny` returns `allowed=False` with the policy's reason;
`require_confirmation` returns `allowed=True,
require_confirmation=True`; `allow` matches without bypassing budget
ceilings. Consumption of a `require_confirmation` decision follows
the Approval Interrupt and Resume requirement: on a durable-session
persona the consuming hook (model binding, clean-room gateway,
learning apply) suspends into the approval flow; on any other persona
it refuses (P13 fallback semantics).

#### Scenario: Deny policy blocks a matching resource

- **WHEN** a policy `{action_type: model_call, resource:
  "expensive-*", effect: deny}` is declared
- **AND** `check_action` is called for resource `expensive-opus`
- **THEN** the decision MUST have `allowed=False`
- **AND** a request for resource `cheap-model` MUST be allowed

#### Scenario: First matching policy wins

- **WHEN** an allow policy for resource `special` precedes a deny
  policy for resource `*`
- **THEN** `check_action` for `special` MUST allow
- **AND** `check_action` for any other resource MUST deny

#### Scenario: require_confirmation on model_call denies without durable sessions

- **WHEN** a `require_confirmation` policy matches a `model_call`
  request
- **AND** the model binding's `check_model_call` hook consumes the
  decision with NO approval store supplied
- **THEN** the dispatch MUST be refused with an error naming the
  confirmation requirement

#### Scenario: require_confirmation on model_call suspends with durable sessions

- **WHEN** a `require_confirmation` policy matches a `model_call`
  request
- **AND** `check_model_call` consumes the decision with the persona's
  durable approval store supplied
- **THEN** the dispatch MUST suspend per the Approval Interrupt and
  Resume requirement (pending request persisted, typed error raised)

#### Scenario: Role dimension matches the acting identity

- **WHEN** a policy `{action_type: model_call, role: "research*",
  effect: deny}` is declared
- **AND** `check_action` is called with an identity whose role is
  `researcher`
- **THEN** the decision MUST have `allowed=False`
- **AND** the same request with an identity role of `coder` MUST be
  allowed

#### Scenario: Depth-scoped policy skips identity-less requests

- **WHEN** a policy with `min_chain_depth: 2` and `effect: deny` is
  declared
- **AND** `check_action` is called with an identity at chain depth 2,
  one at depth 1, and one with no identity
- **THEN** only the depth-2 request MUST be denied
- **AND** the depth-1 and identity-less requests MUST be allowed

### Requirement: Model Call Budget Ceilings

The system SHALL enforce per-persona daily and monthly USD ceilings
on `model_call` actions when `guardrails.budgets.model_call` declares
them (a ceiling of `0` means unlimited). Windows are UTC
calendar-day and calendar-month. Per-call cost resolves in order:
`metadata["estimated_cost_usd"]`; `compute_cost` over
`metadata["pricing"]` (the P19 cost metadata placed on the request by
the model-binding hook) with the configured
`estimate_input_tokens`/`estimate_output_tokens`; else
`default_call_cost_usd` (default `0.0` — cost is never guessed, so
unpriced calls pass without consuming budget unless a default is
configured). A call whose projected spend exceeds a ceiling MUST be
denied with a reason naming the window, ceiling, and spend, and MUST
NOT be recorded; an allowed call records its estimate. Spend state
SHALL be process-wide per persona (surviving resolver rebuilds), with
an in-memory ledger by default, an optional JSON-file ledger under
the persona's git-ignored `.cache/` directory when
`budgets.model_call.persist: file` is set, and a persona-DB ledger
(the `guardrail_spend` table, migration 002) when `persist: db` is
set — the DB ledger requires a resolvable persona database url and
MUST fail actionably without one rather than silently degrading to a
process-local ledger.

#### Scenario: Ceiling allows then denies across calls

- **WHEN** `daily_usd: 1.0` is configured
- **AND** three `model_call` requests each carry
  `estimated_cost_usd: 0.4`
- **THEN** the first two MUST be allowed
- **AND** the third MUST be denied with a reason naming the daily
  ceiling

#### Scenario: Budget state survives resolver rebuilds

- **WHEN** two `PolicyGuardrails` instances are resolved for the same
  persona from independent `CapabilityResolver` calls
- **AND** the first instance's allowed calls consume the ceiling
- **THEN** the second instance MUST deny a call that would exceed it

#### Scenario: Daily window resets on the next UTC day

- **WHEN** the daily ceiling is exhausted
- **AND** the clock advances past UTC midnight
- **THEN** a new `model_call` request MUST be allowed again

#### Scenario: File-persisted ledger survives reload

- **WHEN** `persist: file` is configured and spend was recorded
- **AND** the ledger is re-created from the same spend file
- **THEN** previously recorded spend MUST still count against the
  ceilings

#### Scenario: DB-persisted ledger selects the persona-DB backend

- **WHEN** `persist: db` is configured and a database url resolves
- **THEN** the resolved ledger MUST read and write the
  `guardrail_spend` table scoped to the persona
- **AND** spend recorded through one ledger instance MUST be visible
  to a freshly constructed instance over the same database

#### Scenario: DB persist without a database url fails actionably

- **WHEN** `persist: db` is configured and no database url resolves
- **THEN** ledger resolution MUST raise an error naming the missing
  database configuration
