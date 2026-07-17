# guardrail-provider Specification

## Purpose
Governs the `GuardrailProvider` runtime-checkable protocol together with
its `ActionRequest`/`ActionDecision` types, the `RiskLevel` enumeration,
and the `AllowAllGuardrails` stub. It exists to give each persona a
pluggable pre-action approval point for risky operations (tool calls,
delegation) without hard-coding policy into core code. Consumers are the
delegation spawner and harness execution paths, which receive the provider
through the capability resolver; the stub keeps behavior permissive until a
persona supplies a real policy.
## Requirements
### Requirement: GuardrailProvider Protocol

The system SHALL define a `GuardrailProvider` runtime-checkable Protocol
with the methods `check_action(action: ActionRequest) → ActionDecision`,
`check_delegation(parent_role, sub_role, task) → ActionDecision`, and
`declare_risk(action: ActionRequest) → RiskLevel`.

#### Scenario: Stub implementation satisfies Protocol

- **WHEN** a class implements `check_action`, `check_delegation`, and
  `declare_risk` with the correct signatures
- **THEN** `isinstance(instance, GuardrailProvider)` MUST return `True`

#### Scenario: Non-conforming class rejected

- **WHEN** a class is missing the `check_delegation` method
- **THEN** `isinstance(instance, GuardrailProvider)` MUST return `False`

### Requirement: ActionRequest and ActionDecision Types

The system SHALL define an `ActionRequest` dataclass with fields
`action_type: str`, `resource: str`, `persona: str`, `role: str`, and
`metadata: dict[str, Any]`; and an `ActionDecision` dataclass with
fields `allowed: bool`, `reason: str`, and
`require_confirmation: bool`.

#### Scenario: ActionRequest captures action context

- **WHEN** an `ActionRequest` is created with `action_type="tool_call"`,
  `resource="gmail.send"`, `persona="personal"`, `role="chief_of_staff"`
- **THEN** all fields MUST be accessible as typed attributes

#### Scenario: ActionDecision defaults

- **WHEN** an `ActionDecision` is created with `allowed=True`
- **THEN** `reason` MUST default to `""`
- **AND** `require_confirmation` MUST default to `False`

### Requirement: AllowAllGuardrails Stub

The system SHALL provide an `AllowAllGuardrails` implementation that
returns `ActionDecision(allowed=True)` for all `check_action` and
`check_delegation` calls, and `RiskLevel.LOW` for all `declare_risk`
calls.

#### Scenario: Stub allows all actions

- **WHEN** `AllowAllGuardrails().check_action(any_request)` is called
- **THEN** the returned `ActionDecision.allowed` MUST be `True`

#### Scenario: Stub allows all delegations

- **WHEN** `AllowAllGuardrails().check_delegation(parent, sub, task)` is
  called
- **THEN** the returned `ActionDecision.allowed` MUST be `True`

#### Scenario: Stub declares low risk

- **WHEN** `AllowAllGuardrails().declare_risk(any_request)` is called
- **THEN** the returned value MUST equal `RiskLevel.LOW`

### Requirement: RiskLevel Enumeration

The system SHALL define a `RiskLevel` enumeration with values `LOW`,
`MEDIUM`, `HIGH`, and `CRITICAL`, ordered by severity.

#### Scenario: Ordering

- **WHEN** `RiskLevel.LOW` and `RiskLevel.HIGH` are compared
- **THEN** `RiskLevel.LOW < RiskLevel.HIGH` MUST be `True`

### Requirement: ApprovalRequest Type

The system SHALL define an `ApprovalRequest` dataclass — the
channel-agnostic shape in which a suspended run asks a human for a
decision — mirroring the MCP elicitation schema: `approval_id: str`
(unique, stable across suspend/resume), `message: str`
(human-readable explanation of what approval is being requested and
why), `requested_schema: dict[str, Any]` (a restricted JSON Schema
describing the decision payload; the default schema is an
approve/deny boolean plus an optional free-text justification),
`action: ActionRequest` (the blocked action), `risk: RiskLevel` (the
guardrail's declared risk tier), `thread_id: str` (the suspended
session), and `created_at` timestamp. Channels (AG-UI first; email
and messaging later; MCP elicitation and A2A `input-required` on
served surfaces) are transports that render an `ApprovalRequest` and
capture its decision — no channel defines its own approval shape.

#### Scenario: ApprovalRequest mirrors MCP elicitation

- **WHEN** an `ApprovalRequest` is constructed for a blocked
  `gmail.send` action at `RiskLevel.HIGH`
- **THEN** all fields MUST be accessible as typed attributes
- **AND** the (`message`, `requested_schema`) pair MUST be directly
  representable as an MCP elicitation request without translation

#### Scenario: Default decision schema is approve/deny

- **WHEN** an `ApprovalRequest` is constructed without an explicit
  `requested_schema`
- **THEN** its schema MUST describe an approve/deny boolean and an
  optional justification string

### Requirement: Approval Interrupt and Resume

The system SHALL consume `ActionDecision.require_confirmation`: when a
`GuardrailProvider` returns a decision with
`require_confirmation=True`, the run MUST suspend via the
durable-session checkpoint (harness-adapter durable-session contract)
rather than proceeding or failing, and an `ApprovalRequest` — risk-
tiered from `declare_risk` — MUST be emitted to the active channel.
The suspended state MUST survive process restarts, so approval
round-trips spanning hours (e.g., decision by email reply or signed
link) resolve against the same checkpoint. On receipt of a decision
the run MUST resume from the checkpoint exactly once: an approve
decision executes the blocked action, a deny decision resumes with
the denial surfaced to the agent, and every request/decision pair
(approval id, action, risk, decider channel, decision payload,
timestamps) MUST be recorded in an audit trail.

#### Scenario: require_confirmation suspends instead of executing

- **WHEN** `check_action` returns
  `ActionDecision(allowed=True, require_confirmation=True)` for a tool
  call
- **THEN** the action MUST NOT execute
- **AND** the run MUST be checkpointed in a suspended state
- **AND** an `ApprovalRequest` referencing the run's `thread_id` MUST
  be emitted

#### Scenario: Suspend survives a restart

- **WHEN** a run is suspended awaiting approval
- **AND** the serving process restarts before the decision arrives
- **THEN** delivering the decision afterwards MUST still resume the
  original run from its checkpoint

#### Scenario: Approved decision resumes and executes

- **WHEN** an approve decision is delivered for a pending
  `approval_id`
- **THEN** the suspended run MUST resume and execute the blocked
  action exactly once
- **AND** the audit trail MUST record the request and the decision

#### Scenario: Denied decision resumes without executing

- **WHEN** a deny decision is delivered for a pending `approval_id`
- **THEN** the blocked action MUST NOT execute
- **AND** the run MUST resume with the denial (and any justification)
  visible to the agent
- **AND** the audit trail MUST record the outcome

#### Scenario: Duplicate decisions are idempotent

- **WHEN** two decisions arrive for the same `approval_id`
- **THEN** only the first MUST take effect
- **AND** the second MUST be rejected and recorded, not replayed

### Requirement: Escalation With Justification

The system SHALL support Codex-style escalation-with-justification: an
action denied by policy (`allowed=False`) MAY carry a
machine-readable escalation — the original `ActionRequest` plus a
justification produced by the requesting agent — which re-enters the
approval interrupt flow as an `ApprovalRequest` at a risk tier no
lower than the guardrail's `declare_risk` for that action. Escalation
is a request for human override, never a bypass: without an explicit
approve decision the action remains denied, and escalation attempts
MUST appear in the same audit trail as ordinary approvals.

#### Scenario: Denied action escalates to a human

- **WHEN** `check_action` returns `ActionDecision(allowed=False)` for
  an action
- **AND** the agent submits an escalation with a justification string
- **THEN** an `ApprovalRequest` MUST be emitted carrying the original
  action and the justification
- **AND** the run MUST suspend awaiting the decision

#### Scenario: Unanswered escalation stays denied

- **WHEN** an escalation is emitted and no approve decision is ever
  delivered
- **THEN** the action MUST NOT execute
- **AND** the audit trail MUST record the escalation as unresolved or
  denied

### Requirement: PolicyGuardrails Implementation

The system SHALL provide a `PolicyGuardrails` implementation of the
`GuardrailProvider` protocol, configured from a persona `guardrails:`
section with three parts: `policies:` (ordered action rules),
`budgets.model_call:` (USD ceilings), and `delegation:` (sub-role
constraints). The section SHALL be parsed and validated at persona
load into a typed `GuardrailConfig`; unknown keys, unknown policy
effects, and malformed numbers MUST fail persona load with an
actionable error naming the offender. A persona that declares no
`guardrails:` section (or an empty one) keeps `AllowAllGuardrails`
behavior unchanged.

#### Scenario: PolicyGuardrails satisfies the protocol

- **WHEN** a `PolicyGuardrails` instance is constructed from any
  valid `GuardrailConfig`
- **THEN** `isinstance(instance, GuardrailProvider)` MUST return
  `True`

#### Scenario: Invalid guardrails section fails persona load

- **WHEN** a persona declares a policy with `effect: not-an-effect`
- **THEN** persona load MUST raise an error naming the invalid effect

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
ceilings. For `model_call` actions, a `require_confirmation` decision
is treated as a denial by the model-binding budget hook until the
approval interrupt flow exists (the "Confirmation Requests Deny Until
Interrupt Flow Exists" requirement of the model-provider capability
is preserved unchanged — this change does NOT build interrupt or
resume).

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

#### Scenario: require_confirmation on model_call denies at the binding

- **WHEN** a `require_confirmation` policy matches a `model_call`
  request
- **AND** the model binding's `check_model_call` hook consumes the
  decision
- **THEN** the dispatch MUST be refused with an error naming the
  confirmation requirement

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
an in-memory ledger by default and an optional JSON-file ledger under
the persona's git-ignored `.cache/` directory when
`budgets.model_call.persist: file` is set. A persona-DB-backed ledger
is explicitly deferred.

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

### Requirement: Delegation Constraints

The system SHALL enforce `guardrails.delegation` in
`check_delegation`, preserving the existing consumer contract (the
delegation spawner raises `PermissionError` when `allowed=False`):
a sub-role matching any `denied_sub_roles` glob is denied with a
reason naming the pattern, and a task longer than a non-zero
`max_task_chars` is denied. All other delegations are allowed. The
section SHALL additionally carry `max_chain_depth` (P25 agent-iam;
default `5`, `0` = unlimited, validated as a non-negative number) —
the delegation-chain depth ceiling consumed by the delegation
spawner (chain enforcement is a property of the spawner's
`AgentIdentity`, not of the `check_delegation` signature, which is
unchanged). The `max_chain_depth` default MUST NOT make an otherwise
empty `GuardrailConfig` truthy — resolver guardrail selection is
unchanged.

#### Scenario: Denied sub-role glob blocks delegation

- **WHEN** `denied_sub_roles: ["cod*"]` is configured
- **AND** `check_delegation("chief_of_staff", "coder", task)` is
  called
- **THEN** the decision MUST have `allowed=False`
- **AND** delegation to `writer` MUST be allowed

#### Scenario: Spawner surfaces the denial

- **WHEN** the delegation spawner consumes a denied decision
- **THEN** it MUST raise `PermissionError` before loading the
  sub-role

#### Scenario: max_chain_depth parses with a safe default

- **WHEN** a persona declares no `guardrails:` section (or one
  without `delegation.max_chain_depth`)
- **THEN** the parsed constraint MUST default to `5`
- **AND** the parsed `GuardrailConfig` MUST remain falsy so the
  resolver still selects `AllowAllGuardrails`

#### Scenario: Negative max_chain_depth fails parse

- **WHEN** `delegation: {max_chain_depth: -3}` is declared
- **THEN** parsing MUST raise an error naming `max_chain_depth`

### Requirement: Guardrail Risk Declaration

The system SHALL derive `declare_risk` from the configured policy for
the action: an action matched by a `deny` or `require_confirmation`
policy declares `RiskLevel.HIGH`; a `model_call` under configured
budget ceilings declares `RiskLevel.MEDIUM`; everything else declares
`RiskLevel.LOW`.

#### Scenario: Denied action declares HIGH

- **WHEN** a deny policy matches the action
- **THEN** `declare_risk` MUST return `RiskLevel.HIGH`

#### Scenario: Budgeted model call declares MEDIUM

- **WHEN** no policy matches a `model_call` action
- **AND** a model-call budget is configured
- **THEN** `declare_risk` MUST return `RiskLevel.MEDIUM`

### Requirement: Resolver Guardrail Selection

The capability resolver SHALL select the guardrail slot identically
on the host and sdk branches: an injected `guardrail_factory` wins
(unchanged); otherwise a persona whose parsed `GuardrailConfig` is
non-empty receives `PolicyGuardrails`; every other persona receives
`AllowAllGuardrails`, preserving pre-P13 behavior.

#### Scenario: Persona with guardrails gets PolicyGuardrails

- **WHEN** a persona declares a non-empty `guardrails:` section
- **AND** the resolver resolves either harness type
- **THEN** `CapabilitySet.guardrails` MUST be a `PolicyGuardrails`
  instance

#### Scenario: Persona without guardrails keeps AllowAll

- **WHEN** a persona declares no `guardrails:` section
- **THEN** `CapabilitySet.guardrails` MUST be `AllowAllGuardrails`

#### Scenario: Factory override preserved

- **WHEN** a `guardrail_factory` is injected into the resolver
- **THEN** the factory's instance MUST be used even when the persona
  declares `guardrails:`

