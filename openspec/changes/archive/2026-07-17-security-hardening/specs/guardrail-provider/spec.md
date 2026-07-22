# guardrail-provider Specification (delta)

## ADDED Requirements

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
`action_type` equals the request's action type (or is `"*"`) and its
`resource` glob matches the request's resource. Effects: `deny`
returns `allowed=False` with the policy's reason;
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
`max_task_chars` is denied. All other delegations are allowed.

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
