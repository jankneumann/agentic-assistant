# model-provider Specification (delta)

## ADDED Requirements

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

## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Default Model Providers

**Reason**: Owner review verdict #3 (2026-07-16, registry-only): with
no working personas deployed yet, the backward-compat dual config
path is churn with no beneficiaries. `StaticModelProvider` and the
per-harness `harnesses.<name>.model` config strings it wrapped are
deleted; personas without a `models:` registry now resolve against a
registry synthesized from the harness defaults (ADDED "Registry-Only
Model Selection"), and the host half of this requirement moves to the
ADDED "Host-Provided Model Provider" requirement unchanged.
