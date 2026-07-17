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

### Requirement: ContainerSandboxProvider

The system SHALL provide a `ContainerSandboxProvider` implementing the
`SandboxProvider` protocol that compiles a v2 `SandboxConfig`'s three
planes into a container run invocation (`docker run` or `podman run`),
with the runtime autodetected from PATH (docker preferred, podman
fallback) when not declared, and with the process runner injectable so
tests never execute a real container. Plane compilation SHALL be:
filesystem `read-only` → read-only root filesystem plus the execution
context's `work_dir` mounted read-only at the container workspace;
`workspace-write` → read-only root plus the workspace mounted
writable; `full-access` → writable root; declared mounts become
host:sandbox volume arguments honoring their writable flag. A declared
network plane with an empty allow-list SHALL compile to no network at
all (`--network=none`); a non-empty allow-list SHALL compile to
`SANDBOX_NET_ALLOW` (plus proxy environment variables when a proxy is
declared) as a documented limitation — plain container runtimes cannot
filter per-host egress, so enforcement is delegated to an egress proxy
or an enforcing backend, and the provider MUST log a warning saying
so. The credentials plane SHALL compile to explicit `-e REF=value`
arguments for exactly the visible refs (resolved through the injected
credential provider); no ambient host environment may be inherited.
An unavailable or unsupported runtime SHALL fail with an actionable
error, never silently degrade to passthrough.

#### Scenario: Read-only filesystem plane compiles to a read-only container

- **WHEN** `compile_run_argv` runs with filesystem level `"read-only"`
- **THEN** the argv MUST contain `--read-only`
- **AND** the workspace mount MUST be suffixed `:ro`

#### Scenario: Empty network allow-list compiles to no network

- **WHEN** the config declares a network plane with an empty allow-list
- **THEN** the compiled argv MUST contain `--network=none`

#### Scenario: Non-empty allow-list is a documented limitation

- **WHEN** the network plane allows `"api.anthropic.com"` with a proxy
- **THEN** the argv MUST NOT contain `--network=none`
- **AND** it MUST carry `SANDBOX_NET_ALLOW=api.anthropic.com` and the
  proxy environment variables
- **AND** a warning MUST be logged that enforcement is delegated

#### Scenario: Credentials plane exports only the visibility set

- **WHEN** the credentials plane lists only `"GMAIL_TOKEN"`
- **THEN** the argv MUST contain exactly one `-e` pair for
  `GMAIL_TOKEN` with its resolved value
- **AND** no other credential ref may appear

#### Scenario: Runtime autodetect and injection

- **WHEN** no runtime is declared and only podman is on PATH
- **THEN** the provider MUST select `podman`
- **AND** when neither docker nor podman is found, construction MUST
  fail with an actionable error naming both

### Requirement: Sandboxed Process Runner Seam

The system SHALL provide a `SandboxedProcessRunner` implementing the
extension-subprocess-boundary enforcement seam: constructed from a
provider, a `SandboxConfig`, and an `ExecutionContext`, its `run`
method executes a command with the posture derived from the execution
context — under a `ContainerSandboxProvider` context the command is
compiled into the container invocation carrying the three planes;
under any other provider the command runs unwrapped. The posture MUST
come from the execution context, never from per-extension
configuration.

#### Scenario: Container context wraps the command

- **WHEN** `run(["echo", "hi"])` executes under a container context
  whose network plane has an empty allow-list
- **THEN** the executed argv MUST be a container invocation containing
  `--network=none` and ending with the original command

#### Scenario: Passthrough context runs the command unwrapped

- **WHEN** `run(["echo", "hi"])` executes under a `PassthroughSandbox`
  context
- **THEN** the executed argv MUST equal the original command

### Requirement: Persona Sandbox Selection

The system SHALL parse an optional persona `sandbox:` section
(`provider` = `passthrough` | `container`, `image`, `runtime`, plus
the three plane declarations) with actionable validation errors —
unknown keys, unsupported providers/runtimes, a missing image for the
container provider, levels outside the Codex vocabulary, malformed
mounts, and a writable mount under a `read-only` level MUST each fail
persona load naming the offender. The capability resolver SHALL select
`ContainerSandboxProvider` only when the persona requests
`provider: container` (injecting the persona-scoped credential
provider for the credentials plane); an injected sandbox factory still
wins, and every other persona keeps `PassthroughSandbox` as the
default. Provider construction errors for an explicitly requested
container sandbox SHALL propagate rather than degrade to passthrough.

#### Scenario: Resolver selects the container provider on request

- **WHEN** a persona declares `sandbox: {provider: container, image:
  python:3.12-slim, runtime: docker}`
- **THEN** the resolved `CapabilitySet.sandbox` MUST be a
  `ContainerSandboxProvider` with that image and runtime

#### Scenario: Personas without a sandbox section keep passthrough

- **WHEN** a persona declares no `sandbox:` section
- **THEN** the resolved sandbox MUST be `PassthroughSandbox`

#### Scenario: Invalid sandbox declarations fail persona load

- **WHEN** a persona declares `sandbox: {provider: container}` with no
  image
- **THEN** persona load MUST fail with an error naming the missing
  `image`

