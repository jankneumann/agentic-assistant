# sandbox-provider Specification

## Purpose
Governs the `SandboxProvider` runtime-checkable protocol, the
`ExecutionContext` type, and the `PassthroughSandbox` stub. It exists to
reserve a pluggable isolation point for tool and code execution so that
real sandboxing can be introduced later without changing harness or
capability-resolver interfaces. Consumers are the capability resolver,
which selects a provider per persona, and harness execution paths; the
passthrough stub executes without isolation until a real provider lands.
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
is a no-op. `PassthroughSandbox` remains the default sandbox
implementation selected by the capability resolver. It SHALL accept
any `SandboxConfig` v2 — including configs declaring filesystem,
network, or credentials planes — without error and without
enforcement: the planes are carried on the returned
`ExecutionContext` (via its `metadata`) for observability, but no
isolation is applied until a real provider (P22) implements the
enforcement seam.

#### Scenario: Stub returns current directory

- **WHEN** `PassthroughSandbox().create_context(config)` is called
- **THEN** the returned `ExecutionContext.work_dir` MUST equal
  `Path.cwd()`
- **AND** `isolation_type` MUST equal `"none"`

#### Scenario: Stub cleanup is safe to call

- **WHEN** `PassthroughSandbox().cleanup(context)` is called
- **THEN** no exception MUST be raised

#### Scenario: Stub accepts v2 planes without enforcing them

- **WHEN** `PassthroughSandbox().create_context(config)` is called
  with a config declaring filesystem level `"read-only"` and an empty
  network allow-list
- **THEN** the call MUST succeed with `isolation_type="none"`
- **AND** the declared planes MUST be recorded on the returned
  context's `metadata`
- **AND** no filesystem or network restriction may actually be applied

### Requirement: SandboxConfig v2 Three Planes

The system SHALL extend `SandboxConfig` with three typed planes, each
independently declarable:

- **Filesystem plane** — a named access level, one of `"read-only"`,
  `"workspace-write"`, or `"full-access"` (the Codex policy
  vocabulary), plus an explicit list of mounts (host path, sandbox
  path, writable flag). `workspace-write` grants writes only inside
  the execution context's `work_dir` and declared writable mounts.
- **Network plane** — deny-by-default egress with an explicit
  allow-list of hosts/CIDRs and an optional proxy endpoint through
  which allowed egress is routed. An empty allow-list means no
  network.
- **Credentials plane** — an explicit secret visibility set: the list
  of `CredentialProvider` refs visible inside the sandbox. Secrets not
  in the set MUST NOT be observable (no ambient environment
  inheritance).

The legacy `isolation_type` and `metadata` fields are retained;
omitted planes default to the permissive legacy behavior so existing
configurations remain valid.

#### Scenario: Filesystem plane names a Codex-style level

- **WHEN** a `SandboxConfig` declares the filesystem plane with level
  `"workspace-write"` and one read-only mount
- **THEN** both the level and the mount list MUST be accessible as
  typed attributes
- **AND** a level outside the three-name vocabulary MUST fail
  validation

#### Scenario: Network plane is deny-by-default

- **WHEN** a `SandboxConfig` declares a network plane with an empty
  allow-list
- **THEN** the declared posture MUST be no egress at all
- **AND** adding `"api.anthropic.com"` to the allow-list MUST permit
  egress to that host only

#### Scenario: Credentials plane is an explicit visibility set

- **WHEN** a `SandboxConfig` declares a credentials plane listing only
  `"GMAIL_TOKEN"`
- **THEN** the declared posture MUST expose exactly that credential
  ref inside the sandbox
- **AND** all other secrets MUST be declared invisible

#### Scenario: Omitted planes preserve legacy behavior

- **WHEN** a `SandboxConfig` is created with only the legacy
  `isolation_type="none"` and no planes
- **THEN** construction MUST succeed
- **AND** the effective posture MUST be the current permissive
  behavior

### Requirement: Named Sandbox Enforcement Seam

The system SHALL define the sandbox enforcement seam at exactly two
named boundaries: **tool invocation** (every `ToolSpec.handler`
execution passes through the active `SandboxProvider`'s execution
context) and the **extension subprocess boundary** (any subprocess an
extension spawns inherits the sandbox posture of its execution
context). Real providers (P22) enforce the three planes at these
boundaries; no other code path is a sanctioned enforcement point, and
harness or extension code MUST NOT implement ad-hoc isolation outside
the seam.

#### Scenario: Tool invocation flows through the seam

- **WHEN** a harness executes a tool under a `SandboxProvider` whose
  config declares filesystem level `"read-only"`
- **THEN** the tool execution MUST be associated with the provider's
  `ExecutionContext`
- **AND** a real (enforcing) provider MUST be able to deny a write
  attempt at this boundary without harness code changes

#### Scenario: Extension subprocess inherits the posture

- **WHEN** an extension spawns a subprocess inside an execution
  context whose network plane has an empty allow-list
- **THEN** the declared posture for that subprocess MUST be no egress
- **AND** the posture MUST come from the execution context, not from
  per-extension configuration

