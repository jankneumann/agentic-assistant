# delegation-spawner Specification

## Purpose
TBD - created by archiving change bootstrap-vertical-slice. Update Purpose after archive.
## Requirements
### Requirement: Delegation Respects allowed_sub_roles

The `DelegationSpawner.delegate(sub_role, task)` method SHALL reject any
`sub_role` not present in the parent role's
`delegation.allowed_sub_roles` list.

#### Scenario: Disallowed sub-role raises ValueError

- **WHEN** parent role has `delegation.allowed_sub_roles == ["researcher"]`
- **AND** `spawner.delegate("coder", "task")` is called
- **THEN** `ValueError` MUST be raised
- **AND** the message MUST reference the allowed roles list

#### Scenario: Allowed sub-role proceeds to harness

- **WHEN** parent role allows `["writer"]`
- **AND** `spawner.delegate("writer", "draft an email")` is called
- **THEN** `HarnessAdapter.spawn_sub_agent` MUST be invoked once with a
  `RoleConfig` whose `name == "writer"`

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

