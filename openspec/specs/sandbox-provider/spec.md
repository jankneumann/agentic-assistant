# sandbox-provider Specification

## Purpose
TBD - created by archiving change capability-protocols. Update Purpose after archive.
## Requirements
### Requirement: SandboxProvider Protocol

The system SHALL define a `SandboxProvider` runtime-checkable Protocol
with the methods `create_context(config: SandboxConfig) →
ExecutionContext` and `cleanup(context: ExecutionContext) → None`.

#### Scenario: Stub implementation satisfies Protocol

- **WHEN** a class implements `create_context` and `cleanup` with the
  correct signatures
- **THEN** `isinstance(instance, SandboxProvider)` MUST return `True`

### Requirement: ExecutionContext Type

The system SHALL define an `ExecutionContext` dataclass with fields
`work_dir: Path`, `isolation_type: str` (one of `"none"`, `"worktree"`,
`"container"`, `"host_provided"`), and `metadata: dict[str, Any]`.

#### Scenario: ExecutionContext captures sandbox state

- **WHEN** an `ExecutionContext` is created with
  `work_dir=Path("/tmp/sandbox")`,
  `isolation_type="worktree"`
- **THEN** all fields MUST be accessible as typed attributes
- **AND** `metadata` MUST default to an empty dict

### Requirement: PassthroughSandbox Stub

The system SHALL provide a `PassthroughSandbox` implementation that
returns an `ExecutionContext` with `isolation_type="none"` and
`work_dir` set to the current working directory, and whose `cleanup`
is a no-op.

#### Scenario: Stub returns current directory

- **WHEN** `PassthroughSandbox().create_context(config)` is called
- **THEN** the returned `ExecutionContext.work_dir` MUST equal
  `Path.cwd()`
- **AND** `isolation_type` MUST equal `"none"`

#### Scenario: Stub cleanup is safe to call

- **WHEN** `PassthroughSandbox().cleanup(context)` is called
- **THEN** no exception MUST be raised

