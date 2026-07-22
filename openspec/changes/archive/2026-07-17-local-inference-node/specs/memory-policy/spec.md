# memory-policy Specification (delta)

## ADDED Requirements

### Requirement: Embeddings Consumer Binding for Graphiti

The system SHALL wire a persona's explicit `models:` `bindings:`
entry for the `embeddings` consumer into the Graphiti client factory:
when the binding is declared, `create_graphiti_client(persona)` MUST
resolve `ModelRequest(consumer="embeddings")` through the registry
provider (health-aware) and construct the `Graphiti` client with an
embedder adapter over the raw OpenAI-compatible client binding — the
first chain member with dialect `openai-compatible` and a non-empty
endpoint supplies the wire endpoint and model id; credentials resolve
through the persona-scoped `CredentialProvider` and every embedding
dispatch is gated by the persona's `GuardrailProvider` `model_call`
hook. The reserved `default` binding key MUST NOT activate this
wiring — only an explicit `embeddings` binding does. When no
`embeddings` binding is declared, the factory MUST construct the
client exactly as before (graphiti-core default embedder). When the
binding is declared but cannot be honored (resolution failure, no
`openai-compatible` chain member with an endpoint), the factory MUST
return `None` with a `logging.WARNING`-level message naming the
persona — disabling Graphiti (Postgres-only degradation) rather than
silently embedding through the default cloud path.

#### Scenario: Declared embeddings binding selects the local embedder

- **WHEN** the persona's registry binds `embeddings` to an
  `openai-compatible` entry with endpoint
  `"http://gx10.local:8001/v1"`
- **AND** `create_graphiti_client(persona)` is called
- **THEN** the `Graphiti` client MUST be constructed with an
  `embedder` whose embedding calls POST to
  `http://gx10.local:8001/v1/embeddings` with the entry's wire
  `model_id`

#### Scenario: No embeddings binding preserves current behavior

- **WHEN** the persona declares a `models:` registry without an
  `embeddings` binding (or no registry at all)
- **AND** `create_graphiti_client(persona)` is called
- **THEN** the `Graphiti` client MUST be constructed without an
  `embedder` argument

#### Scenario: Unhonorable binding disables Graphiti instead of cloud fallback

- **WHEN** the persona binds `embeddings` to an entry that is not
  `openai-compatible` or has no endpoint
- **AND** `create_graphiti_client(persona)` is called
- **THEN** the factory MUST return `None`
- **AND** a `logging.WARNING`-level message naming the persona MUST
  be emitted

#### Scenario: Embedding dispatch is budget-gated

- **WHEN** the persona's guardrails deny `model_call` for the bound
  embeddings entry
- **AND** the embedder adapter's `create` is awaited
- **THEN** no HTTP request may be issued and the guardrail denial
  MUST propagate
