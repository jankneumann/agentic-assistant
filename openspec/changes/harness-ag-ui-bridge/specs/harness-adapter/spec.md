## MODIFIED Requirements

### Requirement: SDK Harness Adapter

The system SHALL define an `SdkHarnessAdapter` abstract base class
extending `HarnessAdapter` with `harness_type() → "sdk"` and requiring
the methods `create_agent(tools: list, extensions: list) → Any`,
`invoke(agent: Any, message: str) → str`,
`astream_invoke(agent: Any, message: str) → AsyncIterator[HarnessEvent]`,
and `spawn_sub_agent(role: RoleConfig, task: str, tools: list,
extensions: list) → str`. The `create_agent` signature retains the
P1 tools/extensions parameters; migration to `CapabilitySet`-based
invocation is deferred to P2 (memory-architecture) when concrete
`MemoryPolicy` implementations exist to inject. The `astream_invoke`
method is an additive streaming variant of `invoke`; it MUST NOT
replace or alter the contract of the existing blocking `invoke`
method, which remains callable by the CLI REPL.

#### Scenario: SdkHarnessAdapter.create_agent accepts tools and extensions

- **WHEN** `DeepAgentsHarness.create_agent(tools, extensions)` is called
- **THEN** the harness MUST construct an agent with the provided tools
  and extension tools combined
- **AND** the harness MUST read memory configuration from persona config

#### Scenario: SdkHarnessAdapter.invoke signature unchanged

- **WHEN** `invoke(agent, message)` is called
- **THEN** the returned value MUST be a string containing the agent's
  response

#### Scenario: SdkHarnessAdapter.astream_invoke returns async iterator of HarnessEvent

- **WHEN** `astream_invoke(agent, message)` is called on any concrete
  `SdkHarnessAdapter` implementation
- **THEN** the returned value MUST be an async iterator yielding
  `HarnessEvent` instances
- **AND** the stream MUST begin with a `RunStarted` event and end with
  a `RunFinished` event in every successful execution

#### Scenario: SdkHarnessAdapter exposes a thread_id for transport binding

- **WHEN** any concrete `SdkHarnessAdapter` instance is constructed by
  the harness factory
- **THEN** it MUST expose a stable `thread_id` attribute (or
  property) returning a non-empty string identifying the conversation
  thread bound to that adapter instance
- **AND** the value MUST persist for the lifetime of the adapter
  instance (i.e., across multiple `invoke` and `astream_invoke` calls)
- **AND** the value MUST be readable by the web transport layer (the
  SSE handler passes it to the AG-UI mapper as the `thread_id`
  keyword argument); harnesses MAY synthesize it (e.g., MSAF
  generates a UUID at construction) or derive it from an existing
  internal field (e.g., Deep Agents reuses `self._thread_id` already
  wired by the conversation-memory requirement)

## ADDED Requirements

### Requirement: HarnessEvent Discriminated Union

The system SHALL define a `HarnessEvent` discriminated union at
`src/assistant/harnesses/sdk/events.py` (next to the
`SdkHarnessAdapter` base class, in the harness layer) with exactly
six variants for v1: `RunStarted`, `RunFinished`, `TextDelta`,
`ToolCallStart`, `ToolCallArgs`, and `ToolCallEnd`. Each variant MUST
be a Pydantic model with a discriminator field. The field names MUST
be harness-agnostic (no LangChain-specific terminology) and
protocol-agnostic (no AG-UI-specific terminology). The module
location preserves the D6 import-direction rule (the transports layer
imports `HarnessEvent` from harnesses, never the reverse).

#### Scenario: HarnessEvent variants are exhaustive for v1

- **WHEN** the `HarnessEvent` union type is inspected at runtime
- **THEN** exactly six variant classes MUST be present
- **AND** the variants MUST be named `RunStarted`, `RunFinished`,
  `TextDelta`, `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`

#### Scenario: RunStarted carries an opaque run identifier

- **WHEN** a `RunStarted` event is constructed
- **THEN** it MUST include a `run_id` field of type `str` that is
  unique within the server process for the lifetime of the run
- **AND** it MUST include a `started_at` timestamp field

#### Scenario: TextDelta carries partial text chunks

- **WHEN** a `TextDelta` event is constructed
- **THEN** it MUST include a `message_id` field grouping deltas from
  the same logical message
- **AND** it MUST include a `text` field containing the partial chunk
  (which MAY be empty for keepalive purposes)

#### Scenario: Tool call lifecycle events share a call_id

- **WHEN** a `ToolCallStart` event with `call_id="c1"` is emitted
- **AND** subsequent `ToolCallArgs` and `ToolCallEnd` events for the
  same tool invocation are emitted
- **THEN** the `call_id` field of every event in that sequence MUST
  equal `"c1"`
- **AND** `ToolCallStart` MUST include a `tool_name` field

#### Scenario: RunFinished.error field is class-name-only when populated

- **WHEN** a `RunFinished` event is constructed with a non-null
  `error` field (i.e., on failure)
- **THEN** the `error` field value MUST be the original exception's
  class name only (e.g., `"RuntimeError"`, `"PermissionError"`)
- **AND** the value MUST NOT contain the exception message body,
  any traceback, or any wrapped-exception detail
- **AND** the value MUST match the pattern `^[A-Z][A-Za-z0-9_.]*$`
  (Python class identifier with optional dotted qualifiers)

### Requirement: Deep Agents Streaming Invocation

The `DeepAgentsHarness` SHALL implement `astream_invoke(agent, message)`
by consuming `agent.astream(...)` from LangGraph (which is already
available via the `InMemorySaver` checkpointer wired in by the
`Multi-Turn Conversation Memory` requirement) and translating each
LangChain stream event into the appropriate `HarnessEvent` variant.
The implementation MUST emit `RunStarted` before the first underlying
chunk, `RunFinished` after the last underlying chunk (or on exception),
and MUST pass `self._thread_id` in the `config` argument to `astream`
exactly as `invoke` does.

#### Scenario: astream_invoke emits RunStarted then RunFinished

- **WHEN** `DeepAgentsHarness.astream_invoke(agent, "hi")` is iterated
  against a fake agent whose `astream` yields a single text chunk
- **THEN** the first event yielded MUST be a `RunStarted` instance
- **AND** the last event yielded MUST be a `RunFinished` instance

#### Scenario: astream_invoke passes thread_id to LangGraph

- **WHEN** `DeepAgentsHarness.astream_invoke(agent, message)` is
  called
- **THEN** the underlying `agent.astream` MUST be called with a
  `config` argument whose `configurable.thread_id` field equals
  `self._thread_id`

#### Scenario: astream_invoke translates LangChain text chunks to TextDelta

- **WHEN** the underlying `agent.astream` yields a text-message
  chunk with content `"Hello"`
- **THEN** the harness MUST yield a `TextDelta` event whose `text`
  field equals `"Hello"`
- **AND** the `message_id` MUST be stable across consecutive text
  chunks belonging to the same assistant message

#### Scenario: astream_invoke translates tool calls to lifecycle events

- **WHEN** the underlying agent invokes a tool named `"search"` with
  arguments `{"query": "python decorators"}` during streaming
- **THEN** the harness MUST yield a `ToolCallStart` with `tool_name`
  equal to `"search"`
- **AND** at least one `ToolCallArgs` event whose accumulated payload
  parses to the original arguments
- **AND** a `ToolCallEnd` event with the same `call_id`

#### Scenario: astream_invoke emits RunFinished with error on exception (two-phase)

- **WHEN** the underlying `agent.astream` raises
  `RuntimeError("quota exceeded")` mid-stream
- **THEN** the harness MUST yield a terminal `RunFinished` event
  whose `error` field equals the exception class name only
  (e.g., `"RuntimeError"`) — Phase 1 of the two-phase error contract
  (design.md D8)
- **AND** the harness MUST then re-raise the original `RuntimeError`
  unchanged after yielding the terminal event — Phase 2 of the
  two-phase error contract
- **AND** the harness MUST NOT yield any further events after the
  terminal `RunFinished`

### Requirement: MS Agent Framework Streaming Invocation

The `MSAgentFrameworkHarness` SHALL implement `astream_invoke(agent,
message)` by invoking `agent.run(messages, stream=True)` from the
`agent-framework` SDK (which returns a `ResponseStream[AgentResponseUpdate,
AgentResponse[Any]]`) and translating each `AgentResponseUpdate` instance
into the appropriate `HarnessEvent` variant per the mapping table in
design.md D11. The implementation MUST emit `RunStarted` synthetically
before iterating the response stream, MUST emit `RunFinished` after the
stream is exhausted (or on exception), and MUST defensively access the
update's text and tool-call fields via attribute lookup with fallbacks
(mirroring the existing `_stringify_run_result` defensive pattern) so
that SDK shape drift across `agent-framework` minor versions does not
break the harness contract.

#### Scenario: MSAF astream_invoke calls agent.run with stream=True

- **WHEN** `MSAgentFrameworkHarness.astream_invoke(agent, "hi")` is
  iterated
- **THEN** the underlying `agent.run` MUST be called with
  `stream=True` as a keyword argument
- **AND** the call MUST pass the user message in the `messages`
  parameter shape that the agent expects

#### Scenario: MSAF astream_invoke emits RunStarted then RunFinished

- **WHEN** `MSAgentFrameworkHarness.astream_invoke(agent, "hi")` is
  iterated against a fake agent whose `run(stream=True)` yields a single
  text update
- **THEN** the first event yielded MUST be a `RunStarted` instance
- **AND** the last event yielded MUST be a `RunFinished` instance
  with the `error` field set to `None`

#### Scenario: MSAF astream_invoke translates text updates to TextDelta

- **WHEN** an `AgentResponseUpdate` carrying text content `"Hello"` is
  produced by `agent.run(stream=True)`
- **THEN** the harness MUST yield a `TextDelta` event whose `text`
  field equals `"Hello"`
- **AND** the `message_id` MUST be stable across consecutive text
  updates belonging to the same assistant message

#### Scenario: MSAF astream_invoke translates tool calls to lifecycle events

- **WHEN** the underlying `agent.run(stream=True)` emits a sequence
  representing a tool invocation named `"search"` with arguments
  `{"q": "decorators"}`
- **THEN** the harness MUST yield a `ToolCallStart` with `tool_name`
  equal to `"search"`
- **AND** at least one `ToolCallArgs` event whose accumulated payload
  parses to the original arguments
- **AND** a `ToolCallEnd` event with the same `call_id`

#### Scenario: MSAF astream_invoke emits RunFinished with error on exception (two-phase)

- **WHEN** the underlying `agent.run(stream=True)` raises
  `RuntimeError("quota exceeded")` mid-stream
- **THEN** the harness MUST yield a terminal `RunFinished` event
  whose `error` field equals the exception class name only
  (e.g., `"RuntimeError"`) — Phase 1 of the two-phase error contract
  (design.md D8)
- **AND** the harness MUST then re-raise the original `RuntimeError`
  unchanged after yielding the terminal event — Phase 2 of the
  two-phase error contract
- **AND** the harness MUST NOT yield any further events after the
  terminal `RunFinished`

#### Scenario: MSAF astream_invoke applies @traced_harness

- **WHEN** `MSAgentFrameworkHarness.astream_invoke(agent, "hi")` is
  fully consumed
- **THEN** the `@traced_harness` decorator MUST be applied to the
  concrete method
- **AND** `trace_llm_call` MUST be called exactly once after the
  generator is exhausted, with `metadata={"streaming": True}`

### Requirement: Streaming Harness Invocation Emits Observability Span

The system SHALL emit exactly one `trace_llm_call` observability span
per invocation of any `SdkHarnessAdapter.astream_invoke(...)`
implementation, on the same `@traced_harness` decorator basis as the
existing `invoke` requirement. The decorator MUST detect whether the
wrapped function returns a coroutine or an async generator and emit
the span correctly in both cases. For the async-generator path, the
span MUST be emitted when the generator is fully consumed (success)
or when an exception escapes the generator (failure). The emitted call
MUST include the same fields as the `invoke` tracing requirement
(persona, role, model, duration_ms) and additionally MUST include a
metadata field indicating `streaming=True`.

#### Scenario: Deep Agents astream_invoke is traced on success

- **WHEN** `DeepAgentsHarness.astream_invoke(agent, "hello")` is fully
  consumed
- **THEN** `get_observability_provider().trace_llm_call` MUST be called
  exactly once after the generator is exhausted
- **AND** the emitted call's `metadata` MUST contain
  `{"streaming": True}`
- **AND** the emitted `duration_ms` MUST be a non-negative float

#### Scenario: Deep Agents astream_invoke is traced on exception

- **WHEN** the underlying `agent.astream` raises `RuntimeError` mid-stream
  and the exception propagates out of `astream_invoke` (Phase 2 of D8)
- **THEN** `trace_llm_call` MUST be called once with
  `metadata={"streaming": True, "error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller
  unchanged

#### Scenario: MSAF astream_invoke is traced on exception

- **WHEN** the underlying `agent.run(stream=True)` raises `RuntimeError`
  mid-stream and the exception propagates out of `astream_invoke`
  (Phase 2 of D8)
- **THEN** `trace_llm_call` MUST be called once with
  `metadata={"streaming": True, "error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller
  unchanged
