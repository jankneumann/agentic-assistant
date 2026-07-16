# capability-resolver Specification

## Purpose
Governs the `CapabilitySet` type and the `CapabilityResolver` that assembles
a persona/role pair's effective capabilities — memory policy, guardrails,
sandbox, and tool policy — into a single resolved object. It exists so that
harness adapters receive one pre-resolved bundle instead of each harness
re-deriving capability wiring from persona and role configuration.
Consumers are the harness adapters (Deep Agents, SDK, MS Agent Framework)
and the delegation spawner; the resolver is extensible so new capability
kinds can be added without touching harness code.
## Requirements
### Requirement: CapabilitySet Type

The system SHALL define a `CapabilitySet` dataclass with fields
`guardrails: GuardrailProvider`, `sandbox: SandboxProvider`,
`memory: MemoryPolicy`, `tools: ToolPolicy`,
`context: ContextProvider`, and — capability slot #6 —
`models: ModelProvider`. The six slots are the complete kernel
surface: new cross-cutting concerns extend an existing slot's
protocol rather than adding slots.

#### Scenario: CapabilitySet holds all six capabilities

- **WHEN** a `CapabilitySet` is created with all six providers
- **THEN** each field MUST be accessible as a typed attribute
- **AND** each field MUST satisfy its respective Protocol check

#### Scenario: models slot satisfies ModelProvider

- **WHEN** a `CapabilitySet` is assembled by the resolver
- **THEN** `isinstance(capability_set.models, ModelProvider)` MUST
  return `True`

### Requirement: CapabilityResolver

The system SHALL provide a `CapabilityResolver` with a
`resolve(persona: PersonaConfig, harness_type: str, role: RoleConfig)
→ CapabilitySet` method that assembles capability implementations —
including the slot #6 `ModelProvider` — based on harness type. For
SDK harnesses the resolver SHALL always select a
`RegistryModelProvider` for the models slot: backed by the persona's
validated `models:` registry when it declares at least one entry, and
by the default registry synthesized from the known per-harness
default models otherwise (registry-only — no per-harness `model`
config string is consulted).

#### Scenario: SDK harness resolves concrete providers

- **WHEN** `resolve(persona, "sdk", role)` is called for a persona
  that declares no `models:` registry
- **THEN** the returned `CapabilitySet.guardrails` MUST be an
  `AllowAllGuardrails` instance (stub)
- **AND** `CapabilitySet.sandbox` MUST be a `PassthroughSandbox`
  instance (stub)
- **AND** `CapabilitySet.memory` MUST be a `FileMemoryPolicy` instance
- **AND** `CapabilitySet.tools` MUST be a `DefaultToolPolicy` instance
- **AND** `CapabilitySet.models` MUST be a `RegistryModelProvider`
  backed by the synthesized default registry, whose bindings map each
  known harness name to that harness's default entry

#### Scenario: SDK harness with a models registry gets the registry provider

- **WHEN** `resolve(persona, "sdk", role)` is called for a persona
  whose validated `models:` registry declares at least one entry
- **THEN** `CapabilitySet.models` MUST be a `RegistryModelProvider`
  backed by that registry

#### Scenario: Host harness marks host-provided capabilities

- **WHEN** `resolve(persona, "host", role)` is called
- **THEN** the returned `CapabilitySet.memory.resolve(persona, _)`
  MUST return a `MemoryConfig` with `backend_type="host_provided"`
- **AND** `CapabilitySet.sandbox.create_context(_)` MUST return an
  `ExecutionContext` with `isolation_type="host_provided"`
- **AND** `CapabilitySet.models` MUST be a `HostProvidedModelProvider`
  instance — the host seat owns model selection

### Requirement: Resolver Extensibility

The `CapabilityResolver` SHALL accept optional override factories for
each capability — including a `model_factory` for slot #6 — allowing
callers to inject custom implementations following the same
factory-override pattern as the other five slots.

#### Scenario: Custom guardrail provider injected

- **WHEN** `CapabilityResolver(guardrail_factory=custom_factory)` is
  constructed
- **AND** `resolve(persona, "sdk", role)` is called
- **THEN** `CapabilitySet.guardrails` MUST be the instance returned by
  `custom_factory`

#### Scenario: Custom model provider injected

- **WHEN** `CapabilityResolver(model_factory=custom_model_factory)` is
  constructed
- **AND** `resolve(persona, "sdk", role)` is called
- **THEN** `CapabilitySet.models` MUST be the instance returned by
  `custom_model_factory`

#### Scenario: Unset overrides use defaults

- **WHEN** `CapabilityResolver()` is constructed with no overrides
- **AND** `resolve(persona, "sdk", role)` is called
- **THEN** all capabilities MUST use their default implementations

### Requirement: SDK Harness Memory Policy Selection

The `CapabilityResolver` SHALL select the memory policy for SDK
harnesses based on the persona's `database_url` configuration.

#### Scenario: PostgresGraphitiMemoryPolicy when database_url present

- **WHEN** `CapabilityResolver.resolve()` is called for an SDK harness
  with a persona whose `database_url` is
  `"postgresql+asyncpg://localhost/personal"`
- **THEN** `CapabilitySet.memory` MUST be a
  `PostgresGraphitiMemoryPolicy` instance

#### Scenario: FileMemoryPolicy when database_url empty

- **WHEN** `CapabilityResolver.resolve()` is called for an SDK harness
  with a persona whose `database_url` is `""`
- **THEN** `CapabilitySet.memory` MUST be a `FileMemoryPolicy` instance

#### Scenario: Host harness memory policy unchanged

- **WHEN** `CapabilityResolver.resolve()` is called for a host harness
- **THEN** `CapabilitySet.memory` MUST be a
  `HostProvidedMemoryPolicy` instance regardless of `database_url`

### Requirement: Aggregated Extension Tools Are Traced

The system SHALL wrap every extension-derived tool with
`trace_tool_call` instrumentation at the single tool aggregation
site — the tool policy's aggregation loop in
`src/assistant/core/capabilities/tools.py`. The tool policy is the
sole tool aggregator (per the harness-adapter `create_agent`
contract); the former second aggregation site in
`src/assistant/harnesses/sdk/deep_agents.py` is removed, and no
harness may wrap or re-wrap extension tools.

The aggregation site SHALL invoke the shared helper
`src/assistant/telemetry/tool_wrap.wrap_extension_tools(ext)` rather
than calling `wrap_structured_tool` inline, so a single implementation
owns the wrapping policy (attribute extraction, metadata passthrough,
error handling).

The wrapping SHALL happen at the aggregation site rather than in
`src/assistant/extensions/base.py` because `Extension` is a Python
`typing.Protocol`, not a base class — a Protocol cannot carry behavior
for subclasses to inherit, so the wrapping must happen where
extensions are consumed.

#### Scenario: Tool-policy aggregation wraps each tool

- **WHEN** `get_tools_for_persona(persona)` is called and the persona has two extensions each returning one tool
- **THEN** the returned list MUST contain two tools
- **AND** invoking either tool MUST trigger `get_observability_provider().trace_tool_call(tool_kind="extension", ...)` exactly once per invocation

#### Scenario: Harnesses receive pre-wrapped tools and do not re-wrap

- **WHEN** `DeepAgentsHarness.create_agent(tools, extensions)` is
  called with a tool list produced by the tool policy
- **THEN** the constructed agent's tool set MUST contain those tools
  unchanged
- **AND** invoking one of them MUST call
  `trace_tool_call(tool_kind="extension", ...)` exactly once (no
  double wrapping)

#### Scenario: Helper is the single source of truth

- **WHEN** the tool-policy aggregation site is inspected
- **THEN** it MUST import and call `wrap_extension_tools` from `src.assistant.telemetry.tool_wrap`
- **AND** no other module MUST construct its own wrapping closure or call `wrap_structured_tool` directly

