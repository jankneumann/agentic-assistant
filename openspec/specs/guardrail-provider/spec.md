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

