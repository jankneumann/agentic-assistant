# model-provider Specification (delta)

## ADDED Requirements

### Requirement: ModelRef Wire Identifier

The system SHALL carry the provider-side wire identifier on
`ModelRef` as `model_id: str`, populated from the registry entry's
`id` key (mirroring the OpenRouter `/models` schema field of the same
name) and defaulting to the entry `name` when omitted. Bindings MUST
send `model_id` — never the registry entry `name` — on the wire.
`StaticModelProvider` MUST store the persona's configured
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

#### Scenario: Static passthrough preserves the configured string

- **WHEN** `StaticModelProvider` wraps
  `persona.harnesses["deep_agents"]["model"] ==
  "anthropic:claude-sonnet-4-20250514"`
- **THEN** the single `ModelRef` MUST have
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
