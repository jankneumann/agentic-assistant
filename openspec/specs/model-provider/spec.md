# model-provider Specification

## Purpose
TBD - created by archiving change capability-protocols-v2. Update Purpose after archive.
## Requirements
### Requirement: ModelRef Type

The system SHALL define a `ModelRef` dataclass that is the
harness-neutral description of one callable model, with fields:
`name: str` (registry entry name), `dialect: str` (one of
`"openai-compatible"`, `"anthropic"`, `"gemini"`, `"bedrock"`,
`"vertex"` — the converged wire protocols; no new wire protocol is
invented), `endpoint: str` (base URL; MAY be empty for a dialect's
hosted default), `credential_ref: str` (a `CredentialProvider` lookup
key — the `ModelRef` MUST NOT carry a secret value),
`tags: list[str]` (capability tags), and catalog metadata fields
mirroring the OpenRouter `/models` schema: `pricing: dict[str, Any]`
(per-token prompt/completion costs and related rate fields, verbatim
OpenRouter key names), `context_length: int`, and
`modalities: dict[str, Any]` (input/output modalities), so that cloud
entries sync verbatim from OpenRouter and local entries are
hand-authored in the same shape.

#### Scenario: ModelRef captures a metered cloud model

- **WHEN** a `ModelRef` is created with `name="sonnet"`,
  `dialect="anthropic"`, `credential_ref="ANTHROPIC_API_KEY"`,
  `tags=["coding", "long-context"]`, and OpenRouter-shaped `pricing`
- **THEN** all fields MUST be accessible as typed attributes
- **AND** no attribute of the instance may contain a resolved secret
  value

#### Scenario: ModelRef captures a local endpoint

- **WHEN** a `ModelRef` is created with `dialect="openai-compatible"`
  and `endpoint="http://gx10.local:8000/v1"`
- **THEN** the instance MUST be valid without any hosted-provider
  identifier — the `openai-compatible` dialect plus an endpoint alone
  fully describes a local backend (vLLM, Ollama, NIM)

#### Scenario: Unknown dialect rejected

- **WHEN** a `ModelRef` is created with `dialect="litellm"`
- **THEN** validation MUST fail — the dialect vocabulary is closed to
  the five converged wire protocols

### Requirement: Capability Tag Vocabulary

The system SHALL define the capability-tag vocabulary
`fast`, `cheap`, `long-context`, `coding`, `vision`, `local-only`,
`private-data-ok` as the shared routing vocabulary for `ModelRef.tags`
and `ModelRequest` requirements. The vocabulary is shared data with
`agentic-coding-tools`' cost-aware routing (contracts and data are
shared, code is not, per ADR-0006); additions extend this spec rather
than forking per consumer.

#### Scenario: Tags outside the vocabulary rejected

- **WHEN** a registry entry declares `tags: ["fast", "sparkly"]`
- **THEN** registry validation MUST reject `"sparkly"` with an error
  naming the allowed vocabulary

#### Scenario: Privacy tag drives local-first resolution

- **WHEN** a `ModelRequest` requires the `private-data-ok` tag
- **THEN** every `ModelRef` in the resolved chain MUST carry
  `private-data-ok` in its `tags`

### Requirement: Persona Model Registry

The system SHALL support a persona-level `models:` registry of named
entries, each declaring the `ModelRef` fields (dialect, endpoint,
credential ref, tags, OpenRouter-shaped catalog metadata) and an
optional ordered `fallbacks:` list naming other registry entries. The
registry is loaded and validated with the persona configuration;
entries with unknown dialects, out-of-vocabulary tags, or fallback
references to undeclared entries MUST fail persona load with an
actionable error.

#### Scenario: Registry entry resolves to a ModelRef

- **WHEN** a persona declares a `models:` entry named `"local-fast"`
- **AND** the persona is loaded
- **THEN** the entry MUST be available as a `ModelRef` with
  `name="local-fast"` and all declared fields populated

#### Scenario: Dangling fallback reference fails load

- **WHEN** entry `"primary"` declares `fallbacks: ["missing-entry"]`
- **AND** no entry named `"missing-entry"` exists
- **THEN** persona load MUST fail with an error naming both entries

### Requirement: ModelProvider Protocol

The system SHALL define a `ModelProvider` runtime-checkable Protocol
with the methods `resolve(request: ModelRequest) → list[ModelRef]`
and `list_models() → list[ModelRef]`. A `ModelRequest` dataclass SHALL
carry `required_tags: list[str]`, `preferred_tags: list[str]`, and
`consumer: str` (one of `"chat"`, `"embedding"`). `resolve` MUST
return a non-empty ordered fallback chain — the first `ModelRef` is
the primary selection and each subsequent entry is tried only after
its predecessor fails — and MUST raise a `ModelResolutionError` naming
the unsatisfiable requirements when no registry entry matches
`required_tags`.

#### Scenario: Conforming implementation satisfies Protocol

- **WHEN** a class implements `resolve` and `list_models` with the
  correct signatures
- **THEN** `isinstance(instance, ModelProvider)` MUST return `True`

#### Scenario: Resolution returns an ordered fallback chain

- **WHEN** `resolve(ModelRequest(required_tags=["coding"], ...))` is
  called against a registry whose `"primary"` entry carries `coding`
  and declares `fallbacks: ["secondary"]`
- **THEN** the returned list MUST begin with the `"primary"` ModelRef
- **AND** the `"secondary"` ModelRef MUST appear after it

#### Scenario: Unsatisfiable requirements raise

- **WHEN** `resolve(ModelRequest(required_tags=["vision"], ...))` is
  called and no registry entry carries the `vision` tag
- **THEN** a `ModelResolutionError` MUST be raised naming the missing
  tag
- **AND** the provider MUST NOT silently return a non-matching model

### Requirement: Per-Consumer Model Bindings

The system SHALL provide thin per-consumer bindings that adapt a
`ModelRef` to each consumer's native client — the binding is the only
consumer-specific code; the seam is the `ModelProvider` protocol
itself:

- a LangChain binding that adapts a `ModelRef` via
  `init_chat_model` for LangChain-native harnesses (DeepAgents);
- an MSAF binding that adapts a `ModelRef` to an `agent-framework`
  chat client;
- a raw OpenAI-compatible client binding for direct calls that need
  no harness — including embeddings — covering every
  `openai-compatible` endpoint (OpenRouter and all local backends).

Bindings MUST resolve `credential_ref` through the
`CredentialProvider` seam at binding time, and MUST NOT introduce a
second provider-abstraction library (per ADR-0005; any exception is a
superseding ADR when P19 lands).

#### Scenario: LangChain binding consumes a ModelRef

- **WHEN** the LangChain binding is given a `ModelRef` with
  `dialect="anthropic"`
- **THEN** it MUST construct the chat model via `init_chat_model`
  using the ref's name, endpoint, and a credential resolved from
  `credential_ref`
- **AND** the harness code consuming the result MUST NOT read raw
  model-id strings from persona config

#### Scenario: Embeddings use the raw OpenAI-compatible binding

- **WHEN** a direct embedding call resolves a `ModelRef` with
  `dialect="openai-compatible"` and `consumer="embedding"`
- **THEN** the raw OpenAI-compatible client binding MUST be used
- **AND** no harness or LangChain machinery may be required on that
  path

### Requirement: Model-Call Budget Hook

The system SHALL gate every model dispatch made through a
`ModelProvider` binding with the persona's `GuardrailProvider`: before
the wire call, the consumer MUST invoke
`check_action(ActionRequest(action_type="model_call",
resource=<ModelRef.name>, persona=..., role=..., metadata=...))`,
where `metadata` carries at minimum the dialect and, when available,
estimated token counts and the ref's pricing fields. A decision with
`allowed=False` MUST prevent the wire call; a decision with
`require_confirmation=True` MUST enter the approval interrupt flow
defined by the guardrail-provider capability.

#### Scenario: Denied model call never reaches the wire

- **WHEN** the guardrail returns `ActionDecision(allowed=False,
  reason="budget exceeded")` for a `model_call` request
- **THEN** the binding MUST NOT issue the HTTP request
- **AND** the caller MUST receive an error carrying the guardrail
  reason

#### Scenario: Allow-all guardrail preserves current behavior

- **WHEN** the persona's guardrail is `AllowAllGuardrails`
- **THEN** every `model_call` check MUST return `allowed=True` and the
  dispatch MUST proceed unchanged

### Requirement: Model Cost Attribution

The system SHALL attribute cost through the existing telemetry spans:
every traced model invocation resolved through a `ModelProvider` MUST
carry the resolved `ModelRef.name`, its dialect, and — when the ref's
OpenRouter-shaped `pricing` fields are present — a computed cost
derived from reported token counts, attributable per persona and role.

#### Scenario: Traced call carries model identity and cost

- **WHEN** a harness invocation completes using a resolved `ModelRef`
  whose `pricing` declares prompt/completion rates
- **AND** the harness reports input/output token counts
- **THEN** the emitted telemetry span MUST include the ref's `name`
  and a cost value computed from the pricing fields and token counts

#### Scenario: Missing pricing degrades gracefully

- **WHEN** a resolved `ModelRef` has empty `pricing` (e.g., a local
  GX10 endpoint)
- **THEN** the span MUST still be emitted with the model identity
- **AND** the cost field MUST be omitted or null, never guessed

### Requirement: Default Model Providers

The system SHALL provide two default `ModelProvider` implementations
so the capability slot is total before P19 lands: a
`StaticModelProvider` for SDK harnesses that wraps the persona's
existing per-harness `model` configuration string into a single-entry
fallback chain (dialect inferred from the provider prefix, no
registry required), and a `HostProvidedModelProvider` for host
harnesses whose `resolve` reports that model selection is owned by
the host seat.

#### Scenario: StaticModelProvider wraps persona config

- **WHEN** `persona.harnesses["deep_agents"]["model"]` equals
  `"anthropic:claude-sonnet-4-20250514"`
- **AND** `StaticModelProvider.resolve(request)` is called
- **THEN** the returned chain MUST contain exactly one `ModelRef` with
  `dialect="anthropic"` and the configured model identifier

#### Scenario: Host provider defers to the host

- **WHEN** `HostProvidedModelProvider.resolve(request)` is called
- **THEN** the result MUST identify the model slot as host-provided
  rather than naming a concrete endpoint

