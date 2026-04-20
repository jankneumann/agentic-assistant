# delegation-spawner — spec delta

## MODIFIED Requirements

### Requirement: Delegation Respects allowed_sub_roles

The `DelegationSpawner.delegate()` method SHALL consult the
`GuardrailProvider.check_delegation(parent_role, sub_role, task)` before
spawning, in addition to the existing `allowed_sub_roles` ACL check.
If the guardrail check returns `ActionDecision(allowed=False)`, the
spawner SHALL raise `PermissionError` with the decision's `reason`.

#### Scenario: Guardrail denies delegation

- **WHEN** `GuardrailProvider.check_delegation()` returns
  `ActionDecision(allowed=False, reason="policy violation")`
- **AND** the sub-role is in `allowed_sub_roles`
- **THEN** `PermissionError` MUST be raised
- **AND** the message MUST contain `"policy violation"`

#### Scenario: Guardrail allows delegation

- **WHEN** `GuardrailProvider.check_delegation()` returns
  `ActionDecision(allowed=True)`
- **AND** the sub-role is in `allowed_sub_roles`
- **THEN** the delegation MUST proceed to `harness.spawn_sub_agent()`

#### Scenario: Role ACL checked before guardrail

- **WHEN** the sub-role is NOT in `allowed_sub_roles`
- **THEN** `ValueError` MUST be raised (existing behavior)
- **AND** `GuardrailProvider.check_delegation()` MUST NOT be called

## ADDED Requirements

### Requirement: DelegationSpawner Receives GuardrailProvider

The `DelegationSpawner.__init__()` SHALL accept an optional
`guardrails: GuardrailProvider` parameter, defaulting to
`AllowAllGuardrails()` when not provided.

#### Scenario: Default guardrails allow everything

- **WHEN** `DelegationSpawner` is created without a `guardrails`
  parameter
- **THEN** all delegations that pass role ACL checks MUST succeed
  (backward compatible)

#### Scenario: Custom guardrails injected

- **WHEN** `DelegationSpawner(guardrails=custom_provider)` is created
- **THEN** `delegate()` MUST call `custom_provider.check_delegation()`
