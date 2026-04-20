# memory-policy — spec delta

## ADDED Requirements

### Requirement: MemoryPolicy Protocol

The system SHALL define a `MemoryPolicy` runtime-checkable Protocol with
the methods `resolve(persona: PersonaConfig, harness_name: str) →
MemoryConfig` and `export_memory_context(persona: PersonaConfig) →
str`.

#### Scenario: Stub implementation satisfies Protocol

- **WHEN** a class implements `resolve` and `export_memory_context` with
  the correct signatures
- **THEN** `isinstance(instance, MemoryPolicy)` MUST return `True`

### Requirement: MemoryConfig Type

The system SHALL define a `MemoryConfig` dataclass with fields
`backend_type: str` (one of `"file"`, `"postgres"`, `"graphiti"`,
`"host_provided"`), `config: dict[str, Any]`, and
`scoping: MemoryScoping`.

#### Scenario: MemoryConfig captures backend selection

- **WHEN** a `MemoryConfig` is created with `backend_type="file"`,
  `config={"memory_files": ["./AGENTS.md"]}`
- **THEN** all fields MUST be accessible as typed attributes

### Requirement: MemoryScoping Type

The system SHALL define a `MemoryScoping` dataclass with fields
`per_persona: bool`, `per_role: bool`, and `per_session: bool`,
defaulting to `per_persona=True`, `per_role=False`,
`per_session=False`.

#### Scenario: Default scoping is per-persona only

- **WHEN** a `MemoryScoping()` is created with no arguments
- **THEN** `per_persona` MUST be `True`
- **AND** `per_role` MUST be `False`
- **AND** `per_session` MUST be `False`

### Requirement: FileMemoryPolicy Stub

The system SHALL provide a `FileMemoryPolicy` implementation that reads
`persona.harnesses[harness_name].memory_files` (defaulting to
`["./AGENTS.md"]`) and returns a `MemoryConfig` with
`backend_type="file"`.

#### Scenario: Reads memory_files from persona config

- **WHEN** `persona.harnesses["deep_agents"]["memory_files"]` equals
  `["./CONTEXT.md"]`
- **THEN** `FileMemoryPolicy().resolve(persona, "deep_agents")` MUST
  return a `MemoryConfig` with
  `config["memory_files"] == ["./CONTEXT.md"]`

#### Scenario: Defaults to AGENTS.md

- **WHEN** `persona.harnesses["deep_agents"]` has no `memory_files` key
- **THEN** `resolve()` MUST return a `MemoryConfig` with
  `config["memory_files"] == ["./AGENTS.md"]`

#### Scenario: export_memory_context returns persona memory content

- **WHEN** `persona.memory_content` equals `"## Memory\nSome context"`
- **THEN** `FileMemoryPolicy().export_memory_context(persona)` MUST
  return a string containing `"## Memory"`
