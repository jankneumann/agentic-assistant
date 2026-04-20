# guardrail-provider Specification

## Purpose
TBD - created by archiving change capability-protocols. Update Purpose after archive.
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

