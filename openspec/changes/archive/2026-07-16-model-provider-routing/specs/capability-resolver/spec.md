# capability-resolver Specification (delta)

## MODIFIED Requirements

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
