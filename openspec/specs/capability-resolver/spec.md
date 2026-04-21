# capability-resolver Specification

## Purpose
TBD - created by archiving change capability-protocols. Update Purpose after archive.
## Requirements
### Requirement: CapabilitySet Type

The system SHALL define a `CapabilitySet` dataclass with fields
`guardrails: GuardrailProvider`, `sandbox: SandboxProvider`,
`memory: MemoryPolicy`, `tools: ToolPolicy`, and
`context: ContextProvider`.

#### Scenario: CapabilitySet holds all five capabilities

- **WHEN** a `CapabilitySet` is created with all five providers
- **THEN** each field MUST be accessible as a typed attribute
- **AND** each field MUST satisfy its respective Protocol check

### Requirement: CapabilityResolver

The system SHALL provide a `CapabilityResolver` with a
`resolve(persona: PersonaConfig, harness_type: str, role: RoleConfig)
→ CapabilitySet` method that assembles capability implementations
based on harness type.

#### Scenario: SDK harness resolves concrete providers

- **WHEN** `resolve(persona, "sdk", role)` is called
- **THEN** the returned `CapabilitySet.guardrails` MUST be an
  `AllowAllGuardrails` instance (stub)
- **AND** `CapabilitySet.sandbox` MUST be a `PassthroughSandbox`
  instance (stub)
- **AND** `CapabilitySet.memory` MUST be a `FileMemoryPolicy` instance
- **AND** `CapabilitySet.tools` MUST be a `DefaultToolPolicy` instance

#### Scenario: Host harness marks host-provided capabilities

- **WHEN** `resolve(persona, "host", role)` is called
- **THEN** the returned `CapabilitySet.memory.resolve(persona, _)`
  MUST return a `MemoryConfig` with `backend_type="host_provided"`
- **AND** `CapabilitySet.sandbox.create_context(_)` MUST return an
  `ExecutionContext` with `isolation_type="host_provided"`

### Requirement: Resolver Extensibility

The `CapabilityResolver` SHALL accept optional override factories for
each capability, allowing callers to inject custom implementations.

#### Scenario: Custom guardrail provider injected

- **WHEN** `CapabilityResolver(guardrail_factory=custom_factory)` is
  constructed
- **AND** `resolve(persona, "sdk", role)` is called
- **THEN** `CapabilitySet.guardrails` MUST be the instance returned by
  `custom_factory`

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

