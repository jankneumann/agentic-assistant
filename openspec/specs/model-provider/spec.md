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

The system SHALL support a persona-level `models:` registry with two
sections: `entries:` — named entries, each declaring the `ModelRef`
fields (dialect, wire `id`, endpoint, credential ref, tags,
OpenRouter-shaped catalog metadata) and an optional ordered
`fallbacks:` list naming other registry entries — and an optional
`bindings:` map from consumer name to entry name, where consumer
names are harness names (`deep_agents`, `ms_agent_framework`) today
and non-harness consumers (`embeddings`, `memory`) as they land, and
the reserved `default` binding key applies to any consumer without an
explicit binding. The registry is loaded and validated with the
persona configuration; entries with unknown dialects,
out-of-vocabulary tags, or fallback references to undeclared entries,
and bindings that target undeclared entries, MUST fail persona load
with an actionable error. Unknown top-level keys under `models:` —
including the pre-registry-only flat entry map — MUST fail load with
a pointer to the current shape.

#### Scenario: Registry entry resolves to a ModelRef

- **WHEN** a persona declares a `models:` `entries:` entry named
  `"local-fast"`
- **AND** the persona is loaded
- **THEN** the entry MUST be available as a `ModelRef` with
  `name="local-fast"` and all declared fields populated

#### Scenario: Dangling fallback reference fails load

- **WHEN** entry `"primary"` declares `fallbacks: ["missing-entry"]`
- **AND** no entry named `"missing-entry"` exists
- **THEN** persona load MUST fail with an error naming both entries

#### Scenario: Binding to an undeclared entry fails load

- **WHEN** `bindings:` maps `deep_agents` to `"missing-entry"`
- **AND** no entry named `"missing-entry"` exists
- **THEN** persona load MUST fail with an error naming the consumer
  and the missing entry

#### Scenario: Flat pre-registry-only shape fails load

- **WHEN** a persona declares model entries directly under `models:`
  instead of under `models.entries:`
- **THEN** persona load MUST fail with an error pointing at the
  `entries:` / `bindings:` shape

### Requirement: ModelProvider Protocol

The system SHALL define a `ModelProvider` runtime-checkable Protocol
with the methods `resolve(request: ModelRequest) → list[ModelRef]`
and `list_models() → list[ModelRef]`. A `ModelRequest` dataclass SHALL
carry `required_tags: list[str]`, `preferred_tags: list[str]`, and
`consumer: str` — the registry `bindings:` lookup key (an open
vocabulary of consumer names, defaulting to `"default"`). The
registry provider SHALL resolve bindings first: a consumer bound in
`bindings:` (directly or via the `default` key) resolves to the bound
entry followed by its declared `fallbacks`, filtered by
`required_tags`; an unbound consumer falls back to tag resolution
over all entries ordered by preferred-tag match count then
declaration order. `resolve` MUST return a non-empty ordered fallback
chain — the first `ModelRef` is the primary selection and each
subsequent entry is tried only after its predecessor fails — and MUST
raise a `ModelResolutionError` naming the unsatisfiable requirements
when no chain member matches `required_tags`.

#### Scenario: Conforming implementation satisfies Protocol

- **WHEN** a class implements `resolve` and `list_models` with the
  correct signatures
- **THEN** `isinstance(instance, ModelProvider)` MUST return `True`

#### Scenario: Consumer binding selects the bound entry

- **WHEN** `bindings:` maps `ms_agent_framework` to `"local-fast"`
- **AND** `resolve(ModelRequest(consumer="ms_agent_framework"))` is
  called
- **THEN** the returned chain MUST begin with the `"local-fast"`
  ModelRef

#### Scenario: Unbound consumer uses the default binding

- **WHEN** `bindings:` declares only `default: sonnet`
- **AND** `resolve(ModelRequest(consumer="deep_agents"))` is called
- **THEN** the returned chain MUST begin with the `"sonnet"` ModelRef
- **AND** `"sonnet"`'s declared fallbacks that carry the required
  tags MUST follow it

#### Scenario: Resolution returns an ordered fallback chain

- **WHEN** `resolve(ModelRequest(required_tags=["coding"], ...))` is
  called with an unbound consumer against a registry whose
  `"primary"` entry carries `coding` and declares
  `fallbacks: ["secondary"]`
- **THEN** the returned list MUST begin with the `"primary"` ModelRef
- **AND** the `"secondary"` ModelRef MUST appear after it

#### Scenario: Unsatisfiable requirements raise

- **WHEN** `resolve(ModelRequest(required_tags=["vision"], ...))` is
  called and no chain member carries the `vision` tag
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

### Requirement: ModelRef Wire Identifier

The system SHALL carry the provider-side wire identifier on
`ModelRef` as `model_id: str`, populated from the registry entry's
`id` key (mirroring the OpenRouter `/models` schema field of the same
name) and defaulting to the entry `name` when omitted. Bindings MUST
send `model_id` — never the registry entry `name` — on the wire.
Synthesized default-registry entries MUST store the harness-default
`provider:model` string verbatim in `model_id` so the LangChain
binding reproduces the pre-P19 `init_chat_model` call exactly; a
`model_id` containing `:` is therefore consumed verbatim by the
LangChain binding, while bare wire identifiers receive the
dialect-mapped provider prefix.

#### Scenario: Registry id populates the wire identifier

- **WHEN** a registry entry named `"local-fast"` declares
  `id: llama-3.1-8b-instruct`
- **THEN** the resolved `ModelRef` MUST have `name="local-fast"` and
  `model_id="llama-3.1-8b-instruct"`
- **AND** the raw OpenAI-compatible binding MUST send
  `"llama-3.1-8b-instruct"` as the request `model`

#### Scenario: Omitted id defaults to the entry name

- **WHEN** a registry entry named `"sonnet"` declares no `id`
- **THEN** the resolved `ModelRef` MUST have `model_id="sonnet"`

#### Scenario: Synthesized default preserves the harness-default string

- **WHEN** a persona declares no `models:` registry and the
  synthesized default registry carries the DeepAgents default entry
  `"anthropic:claude-sonnet-4-20250514"`
- **THEN** the resolved `ModelRef` MUST have
  `model_id="anthropic:claude-sonnet-4-20250514"`
- **AND** the LangChain binding MUST call `init_chat_model` with that
  exact string and no extra arguments

### Requirement: Confirmation Requests Deny Until Interrupt Flow Exists

The system SHALL treat a `model_call` `ActionDecision` with
`require_confirmation=True` as a denial while the guardrail-provider
approval interrupt/resume flow remains unimplemented (it rides on the
durable-session machinery deferred from capability-protocols-v2): the
binding MUST NOT construct the client or issue the wire call, and the
raised error MUST state that confirmation was required and the
interrupt flow is not yet wired. When the interrupt flow lands, that
change supersedes this requirement by entering the approval flow
instead.

#### Scenario: Confirmation-required decision blocks the dispatch

- **WHEN** the guardrail returns
  `ActionDecision(allowed=True, require_confirmation=True)` for a
  `model_call` request
- **THEN** the binding MUST raise an error naming the confirmation
  requirement
- **AND** no client MUST be constructed and no wire call issued

### Requirement: Registry-Only Model Selection

The system SHALL treat the persona `models:` registry as the only
model-selection mechanism: no per-harness `model` configuration
string is read anywhere (persona parsing, harness adapters, or
telemetry fallbacks). When a persona declares no `models:` section,
the system SHALL synthesize a default registry from the known
per-harness default model strings — one entry per known harness
default, with `bindings:` mapping each harness name to its default
entry — and resolve against it through the same registry provider, so
the default path and the configured path share one resolution code
path.

#### Scenario: Persona without a registry gets synthesized defaults

- **WHEN** a persona declares no `models:` section
- **AND** the DeepAgents harness resolves
  `ModelRequest(consumer="deep_agents")`
- **THEN** the resolved chain MUST contain the DeepAgents default
  entry with the harness-default `provider:model` string as its
  `model_id`

#### Scenario: Legacy per-harness model strings are inert

- **WHEN** a persona config carries a `harnesses.<name>.model` key
- **THEN** the value MUST have no effect on model selection — the
  registry (declared or synthesized) alone selects the model

### Requirement: Host-Provided Model Provider

The system SHALL provide a `HostProvidedModelProvider` for host
harnesses whose `resolve` reports that model selection is owned by
the host seat, keeping the capability slot total for host harness
types.

#### Scenario: Host provider defers to the host

- **WHEN** `HostProvidedModelProvider.resolve(request)` is called
- **THEN** the result MUST identify the model slot as host-provided
  rather than naming a concrete endpoint

### Requirement: Endpoint Health Configuration

The system SHALL accept an optional `health:` block on a persona
`models:` registry entry with keys `path` (probe path appended to the
entry's endpoint, default `/models`), `timeout` (probe timeout in
seconds, default `2.0`), and `ttl` (freshness window of a cached probe
verdict in seconds, default `60`). Registry validation MUST reject a
`health:` block on an entry without a non-empty `endpoint`, unknown
keys inside the block, a `path` not starting with `/`, and
non-positive `timeout`/`ttl` values — each with an actionable error at
persona load. The parsed configuration SHALL be carried on the
resolved `ModelRef` as `health` (`None` when the entry declares no
block). The system SHALL provide an `EndpointHealthMonitor` whose
async `probe`/`refresh` methods issue `GET <endpoint><path>` with the
configured timeout, TLS verification on, and redirects refused,
recording a healthy verdict for a 2xx response and an unhealthy
verdict for any other outcome (including transport errors), stamped
for TTL evaluation.

#### Scenario: Health block parses with defaults

- **WHEN** a registry entry with `endpoint: "http://gx10.local:8000/v1"`
  declares `health: {}`
- **THEN** the resolved `ModelRef.health` MUST carry
  `path="/models"`, `timeout=2.0`, and `ttl=60.0`

#### Scenario: Health on an endpoint-less entry fails load

- **WHEN** a registry entry with no `endpoint` declares `health:`
- **THEN** persona load MUST fail with an error naming the entry and
  stating that health checks require an endpoint

#### Scenario: Probe records the endpoint verdict

- **WHEN** `EndpointHealthMonitor.probe(ref)` is awaited and
  `GET <endpoint><path>` returns HTTP 200
- **THEN** the monitor MUST record a healthy verdict for the entry
- **AND** a subsequent probe receiving a connection error MUST record
  an unhealthy verdict

### Requirement: Health-Filtered Resolution

The system SHALL filter `RegistryModelProvider.resolve` chains by
cached endpoint health *after* required-tag filtering, on both the
binding and tag-resolution paths, consulting only cached state — the
synchronous resolve path MUST NOT issue a network probe. An entry is
skipped only when its cached verdict is unhealthy and younger than its
configured `ttl`; entries without a `health:` block, never-probed
entries, and entries whose verdict has aged past `ttl` remain
eligible. When health filtering empties a chain that satisfied
`required_tags`, `resolve` MUST raise `ModelResolutionError` naming
the unhealthy entries rather than substituting any entry that does not
satisfy the required tags — a request requiring `local-only` or
`private-data-ok` therefore fails closed when no healthy entry carries
those tags, never silently falling back to cloud.

#### Scenario: Unhealthy local entry is skipped in favor of its fallback

- **WHEN** entry `"gx10-chat"` (with `health:`) has a fresh unhealthy
  verdict and declares `fallbacks: ["sonnet"]`
- **AND** `resolve(ModelRequest(consumer="scheduler"))` is called
  against a binding to `"gx10-chat"` with no required tags
- **THEN** the returned chain MUST begin with the `"sonnet"` ModelRef
- **AND** MUST NOT contain `"gx10-chat"`

#### Scenario: Unknown health state stays eligible without probing

- **WHEN** entry `"gx10-chat"` declares `health:` but has never been
  probed
- **AND** `resolve` is called
- **THEN** `"gx10-chat"` MUST appear in the returned chain
- **AND** no network request may be issued during resolution

#### Scenario: Privacy-tagged request fails closed on unhealthy local node

- **WHEN** `resolve(ModelRequest(required_tags=["private-data-ok"]))`
  is called and the only entries carrying `private-data-ok` have fresh
  unhealthy verdicts
- **THEN** a `ModelResolutionError` MUST be raised naming the
  unhealthy entries
- **AND** the provider MUST NOT return any entry lacking
  `private-data-ok`, regardless of its health

#### Scenario: Stale verdict expires back to eligible

- **WHEN** entry `"gx10-chat"` has an unhealthy verdict older than its
  configured `ttl`
- **AND** `resolve` is called
- **THEN** `"gx10-chat"` MUST appear in the returned chain

### Requirement: OpenRouter Catalog Cache

The system SHALL support an optional persona-local model catalog cache
at `<persona_dir>/.cache/models/catalog.json` (git-ignored via the
established `.cache/` convention) written by an explicit sync command
that fetches the OpenRouter `/models` catalog with the http_tools D9
security posture (redirects refused, 10 MiB streaming size cap, TLS
verification, bounded timeouts) and an optional API key resolved
through the persona-scoped `CredentialProvider` (ref
`OPENROUTER_API_KEY`, never logged). The cache SHALL store, per model
`id`, the OpenRouter-shaped `pricing` (verbatim key names),
`context_length`, and normalized `modalities`. At persona load,
registry entries whose `id` matches a cached row MUST inherit
`pricing`, `context_length`, and `modalities` for exactly those fields
they left empty — declared values always win — and a missing or
malformed cache file MUST be a silent no-op: persona load never
touches the network and never fails because of the catalog cache.

#### Scenario: Entry with omitted pricing inherits catalog pricing at load

- **WHEN** the persona's catalog cache holds pricing for id
  `"anthropic/claude-sonnet-4"` and a registry entry declares that
  `id` with no `pricing`
- **THEN** the loaded entry's `ModelRef.pricing` MUST equal the cached
  pricing

#### Scenario: Declared pricing wins over the catalog

- **WHEN** a registry entry declares both an `id` present in the cache
  and its own non-empty `pricing`
- **THEN** the loaded entry's `ModelRef.pricing` MUST equal the
  declared value, not the cached one

#### Scenario: Missing cache is a no-op

- **WHEN** a persona with a `models:` registry has no catalog cache
  file
- **THEN** persona load MUST succeed with all entries exactly as
  declared
- **AND** no network request may be issued

#### Scenario: Sync without network fails clearly

- **WHEN** the catalog sync command runs and the catalog URL is
  unreachable
- **THEN** the command MUST exit non-zero with an error naming the
  transport failure
- **AND** any existing cache file MUST be left unmodified

