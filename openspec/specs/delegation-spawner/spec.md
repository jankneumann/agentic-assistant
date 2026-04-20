# delegation-spawner Specification

## Purpose
TBD - created by archiving change bootstrap-vertical-slice. Update Purpose after archive.
## Requirements
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

### Requirement: Concurrent Delegation Limit Enforced

The spawner SHALL enforce the parent role's `delegation.max_concurrent` limit,
raising `RuntimeError` when a new delegation would exceed it.

#### Scenario: Exceeding max_concurrent raises

- **WHEN** parent role's `max_concurrent == 1`
- **AND** a delegation is already in flight
- **AND** a second `delegate()` is invoked concurrently
- **THEN** the second call MUST raise `RuntimeError` referencing the limit

#### Scenario: Count is decremented after delegation completes

- **WHEN** a delegation completes (successfully or with exception)
- **THEN** the internal active counter MUST decrement to permit subsequent
  delegations up to the limit

### Requirement: Persona Availability Check

Before spawning, the spawner SHALL verify the requested sub-role is available
for the current persona (i.e., not in `persona.disabled_roles`).

#### Scenario: Disabled role for persona raises

- **WHEN** `persona.disabled_roles` contains `"writer"`
- **AND** parent role allows `"writer"` as sub-role
- **AND** `spawner.delegate("writer", "task")` is called
- **THEN** `ValueError` MUST be raised referencing the persona name

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

