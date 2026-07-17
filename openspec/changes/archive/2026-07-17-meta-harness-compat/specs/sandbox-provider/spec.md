# sandbox-provider Specification (delta)

## ADDED Requirements

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
