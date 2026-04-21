# capability-resolver Specification Delta — memory-architecture

## ADDED Requirements

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
