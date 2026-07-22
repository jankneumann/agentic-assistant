# harness-adapter

## ADDED Requirements

### Requirement: DeepAgents Memory Snippet Injection in create_agent

The `DeepAgentsHarness` SHALL inject the persona's recent memory
snippets into the `system_prompt` passed to `create_deep_agent` at
`create_agent` time, achieving parity with the MSAF harness's D27
prepend. The harness SHALL await the configured async
`MemoryPolicy.get_recent_snippets(persona, role, limit=N)` (N defaults
to 10; overridable via the `memory_snippet_limit` constructor kwarg)
directly on the `create_agent` event loop (owner review verdict C8,
2026-07-16 — no sync-to-async bridge on the hot path) and SHALL
prepend the result under a `## Recent context` heading ahead
of the composed system prompt. The policy is resolved via
`CapabilityResolver` (SDK tier) unless a `memory_policy` constructor
kwarg is injected. When the policy returns an empty list, the
system prompt MUST equal the composed prompt unchanged with no heading
injected. The `InMemorySaver` checkpointer and thread-id semantics
MUST be unchanged by this injection. `spawn_sub_agent` MUST propagate
the parent's injected `memory_policy` and `memory_snippet_limit` to
the sub-harness.

#### Scenario: Memory snippets prepended to the system prompt

- **WHEN** the configured `MemoryPolicy.get_recent_snippets(persona,
  role, limit=10)` returns `["snippet-1", "snippet-2"]`
- **AND** `create_agent(...)` is awaited
- **THEN** the `system_prompt` passed to `create_deep_agent` MUST
  contain the substring `"## Recent context"` followed by both
  snippets
- **AND** the composed role prompt MUST also appear, after the
  snippet block

#### Scenario: Empty snippets leave the system prompt unchanged

- **WHEN** `MemoryPolicy.get_recent_snippets(...)` returns `[]`
- **AND** `create_agent(...)` is awaited
- **THEN** the `system_prompt` MUST equal
  `compose_system_prompt(persona, role)` exactly
- **AND** the substring `"## Recent context"` MUST NOT appear

#### Scenario: Default file policy on an empty persona injects nothing

- **WHEN** the persona has no `database_url` and empty
  `memory_content`, and no `memory_policy` kwarg is injected
- **AND** `create_agent(...)` is awaited
- **THEN** the resolved `FileMemoryPolicy` MUST yield no injection and
  the prompt MUST NOT contain `"## Recent context"`

### Requirement: SDK Harness Post-Turn Memory Capture

The system SHALL capture completed turns to memory from every concrete
`SdkHarnessAdapter` after a **successful** `invoke` or
`astream_invoke`, via a shared `_capture_interaction(user_message,
response)` helper on the base class. The helper resolves the concrete
harness's `MemoryPolicy` and awaits
`record_interaction(persona, role, user_message=..., response=...)`.
Every failure — policy resolution, missing method on a third-party
policy, backend write error — MUST be swallowed with a
`logging.WARNING`-level message: memory failures MUST never break a
conversation. For `invoke`, `response` is the returned response
string; for `astream_invoke`, `response` is the concatenation of all
emitted `TextDelta` text, and capture MUST occur before the terminal
success `RunFinished` is yielded. Failed invocations and client
disconnects MUST NOT trigger capture.

#### Scenario: Successful invoke captures the turn

- **WHEN** `invoke(agent, "the question")` succeeds with response
  `"the answer"` and the resolved policy implements
  `record_interaction`
- **THEN** `record_interaction` MUST be awaited once with
  `user_message="the question"` and `response="the answer"`

#### Scenario: Capture failure is swallowed with a warning

- **WHEN** `record_interaction` raises a connection error during a
  successful `invoke`
- **THEN** `invoke` MUST still return the agent's response
- **AND** a `logging.WARNING`-level message MUST be emitted

#### Scenario: Failed invocation does not capture

- **WHEN** the underlying agent call raises
- **THEN** `record_interaction` MUST NOT be called
- **AND** the original exception MUST propagate unchanged

#### Scenario: Streaming success captures accumulated text

- **WHEN** `astream_invoke(agent, "greet me")` completes successfully
  after emitting `TextDelta` events with texts `"Hello "` and
  `"world"`
- **THEN** `record_interaction` MUST be awaited once with
  `user_message="greet me"` and `response="Hello world"` before the
  terminal `RunFinished(error=None)` is yielded
