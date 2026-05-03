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

### Requirement: Delegation Emits Observability Span

The system SHALL emit a `trace_delegation` observability span for every call to `DelegationSpawner.delegate(...)` by invoking `get_observability_provider().trace_delegation(...)`. The emitted span MUST include `parent_role` (the calling role name), `sub_role` (the delegated role name), `task` (the task string), `persona` (the active persona name), `duration_ms`, and `outcome` (`"success"` or `"error"`).

The hashing threshold for the `task` argument SHALL be exactly 256 characters: any `task` string whose length is greater than 256 MUST be replaced with the literal string `"sha256:" + hashlib.sha256(task.encode("utf-8")).hexdigest()[:16]` before the emitted span leaves the decorator. Tasks of 256 characters or fewer SHALL be passed through unchanged. Implementations MUST NOT choose a different threshold.

The integration SHALL be implemented via a `@traced_delegation` decorator applied to `delegate` in `src/assistant/delegation/spawner.py`. When the sub-agent invocation raises, `outcome` MUST equal `"error"` and the span MUST be emitted before the exception propagates to the caller.

#### Scenario: Successful delegation emits trace_delegation

- **WHEN** `DelegationSpawner.delegate("researcher", "find X")` is awaited with parent role `assistant` and persona `personal`
- **THEN** `trace_delegation` MUST be called once with `parent_role="assistant"`, `sub_role="researcher"`, `task="find X"`, `persona="personal"`, and `outcome="success"`

#### Scenario: Failed delegation emits trace with outcome=error

- **WHEN** the sub-agent invocation raises `ValueError("unknown role")`
- **THEN** `trace_delegation` MUST be called once with `outcome="error"` and `metadata={"error": "ValueError"}`
- **AND** the `ValueError` MUST propagate to the caller

#### Scenario: Long task string is hashed

- **WHEN** `delegate("researcher", task)` is called with a `task` string of length 512
- **THEN** the emitted `task` attribute MUST match the regex `^sha256:[0-9a-f]{16}$`
- **AND** MUST NOT contain any of the original task's content

