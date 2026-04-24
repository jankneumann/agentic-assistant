# delegation-spawner Specification Delta

## ADDED Requirements

### Requirement: Delegation Emits Observability Span

The system SHALL emit a `trace_delegation` observability span for every call to `DelegationSpawner.delegate(...)` by invoking `get_observability_provider().trace_delegation(...)`. The emitted span MUST include `parent_role` (the calling role name), `sub_role` (the delegated role name), `task` (the task string, hashed to `"sha256:<16-char hex>"` when longer than 256 characters), `persona` (the active persona name), `duration_ms`, and `outcome` (`"success"` or `"error"`).

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
