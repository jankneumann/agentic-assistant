# memory-policy

## MODIFIED Requirements

### Requirement: MemoryPolicy Protocol

The system SHALL define a `MemoryPolicy` runtime-checkable Protocol
with the methods `resolve(persona: PersonaConfig, harness_name: str) →
MemoryConfig`, `export_memory_context(persona: PersonaConfig) → str`,
`async get_recent_snippets(persona, role, *, limit: int = 10) →
list[str]`, and `async record_interaction(persona, role, *,
user_message: str, response: str) → None`.

`get_recent_snippets` is async at the protocol level (owner review
verdict C8, 2026-07-16): consumers on async paths — SDK harness prompt
composition at `create_agent` time — MUST await it directly on the
running event loop, and synchronous callers (host-harness export, CLI
export) MUST bridge at their own edge rather than relying on a
sync-to-async bridge inside policy implementations. It returns up to
`limit` short memory snippets for prompt prepend; implementations MUST
degrade to `[]` on backend failure rather than raising.
`record_interaction` persists a completed turn to the policy's backend
(best effort); policies without a per-turn write path MUST implement
it as a no-op.

#### Scenario: Stub implementation satisfies Protocol

- **WHEN** a class implements `resolve`, `export_memory_context`,
  `get_recent_snippets`, and `record_interaction` with the correct
  signatures
- **THEN** `isinstance(instance, MemoryPolicy)` MUST return `True`

#### Scenario: Built-in policies satisfy the extended Protocol

- **WHEN** `FileMemoryPolicy`, `PostgresGraphitiMemoryPolicy`, or
  `HostProvidedMemoryPolicy` is instantiated
- **THEN** `isinstance(instance, MemoryPolicy)` MUST return `True`

#### Scenario: Snippet retrieval is awaited on the async hot path

- **WHEN** an SDK harness composes its prompt inside async
  `create_agent`
- **THEN** `get_recent_snippets` MUST be awaited directly on the
  running event loop with no intermediate sync-to-async bridge
