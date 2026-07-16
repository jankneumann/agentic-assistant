# capability-resolver Specification (delta)

## MODIFIED Requirements

### Requirement: CapabilityResolver

The system SHALL provide a `CapabilityResolver` with a
`resolve(persona: PersonaConfig, harness_type: str, role: RoleConfig)
→ CapabilitySet` method that assembles capability implementations —
including the slot #6 `ModelProvider` — based on harness type. For
SDK harnesses the resolver SHALL select the models slot from the
persona configuration: a `RegistryModelProvider` when the persona
declares a non-empty `models:` registry, and the `StaticModelProvider`
default (wrapping the per-harness `model` config string) otherwise.

#### Scenario: SDK harness resolves concrete providers

- **WHEN** `resolve(persona, "sdk", role)` is called
- **THEN** the returned `CapabilitySet.guardrails` MUST be an
  `AllowAllGuardrails` instance (stub)
- **AND** `CapabilitySet.sandbox` MUST be a `PassthroughSandbox`
  instance (stub)
- **AND** `CapabilitySet.memory` MUST be a `FileMemoryPolicy` instance
- **AND** `CapabilitySet.tools` MUST be a `DefaultToolPolicy` instance
- **AND** `CapabilitySet.models` MUST be a `StaticModelProvider`
  instance when the persona declares no `models:` registry

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
