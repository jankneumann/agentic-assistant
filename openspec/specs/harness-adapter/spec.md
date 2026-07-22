# harness-adapter Specification

## Purpose
Governs the abstract `HarnessAdapter` contract and everything built on it:
the concrete Deep Agents, SDK, MS Agent Framework, and host harness
adapters, two-tier factory routing with validation, the `HarnessEvent`
discriminated union, streaming invocation, multi-turn conversation memory,
and observability spans around invocations. It exists so persona-times-role
composition stays harness-agnostic — the core composes prompts and
capabilities once, and any registered harness can execute the result.
Consumers are the CLI, the web server, and the delegation spawner.
## Requirements
### Requirement: Abstract Harness Adapter Contract

The system SHALL define an abstract `HarnessAdapter` base class with a
`harness_type() → str` property returning either `"sdk"` or `"host"`,
in addition to the existing `name() → str` method.

#### Scenario: harness_type identifies adapter category

- **WHEN** `DeepAgentsHarness(persona, role).harness_type()` is called
- **THEN** it MUST return `"sdk"`

### Requirement: Deep Agents Harness Implementation

The system SHALL provide a `DeepAgentsHarness` implementation that
constructs a Deep Agents agent using the persona's configured model,
the composed system prompt, and exactly the tool list passed to
`create_agent` — the complete, already-aggregated set produced by
`ToolPolicy.authorized_tools()` (which merges extension tools and
discovered HTTP tools and applies telemetry wrapping). The harness
MUST NOT re-derive tools from the `extensions` argument: it MUST NOT
call `as_langchain_tools()` (or any extension tool method) and MUST
NOT re-wrap tools that the tool policy has already wrapped.

#### Scenario: Harness name is deep_agents

- **WHEN** `DeepAgentsHarness(persona, role).name()` is called
- **THEN** it MUST return the string `"deep_agents"`

#### Scenario: create_agent uses the persona-configured model

- **WHEN** `persona.harnesses["deep_agents"]["model"]` equals
  `"anthropic:claude-sonnet-4-20250514"`
- **THEN** `create_agent(tools, extensions)` MUST construct a Deep Agents
  agent initialized with that model identifier

#### Scenario: create_agent uses only the provided tool list

- **WHEN** `ToolPolicy.authorized_tools()` produced `[tool_A, tool_B]`
  (where `tool_A` is extension-derived and `tool_B` is an HTTP tool)
- **AND** `create_agent(tools=[tool_A, tool_B], extensions=exts)` is
  called
- **THEN** the constructed agent's tool set MUST contain exactly
  `tool_A` and `tool_B`
- **AND** the harness MUST NOT call any tool-producing method on the
  members of `exts`

#### Scenario: invoke returns the last assistant message content

- **WHEN** a fake agent whose `ainvoke` coroutine returns
  `{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}`
  is passed to `DeepAgentsHarness.invoke(agent, "q")`
- **THEN** the returned value MUST equal `"a"`

### Requirement: Harness Factory Validation

The system SHALL provide a `create_harness(persona, role, harness_name)`
factory that rejects unknown harness names and harnesses not enabled for the
persona.

#### Scenario: Unknown harness name raises

- **WHEN** `create_harness(persona, role, "nonexistent")` is called
- **THEN** `ValueError` MUST be raised referencing the available harness names

#### Scenario: Disabled harness raises

- **WHEN** `persona.harnesses["deep_agents"]["enabled"] == false`
- **AND** `create_harness(persona, role, "deep_agents")` is called
- **THEN** `ValueError` MUST be raised indicating the harness is not enabled
  for that persona

### Requirement: SDK Harness Adapter

The system SHALL define an `SdkHarnessAdapter` abstract base class
extending `HarnessAdapter` with `harness_type() → "sdk"` and requiring
the methods `create_agent(tools: list, extensions: list) → Any`,
`invoke(agent: Any, message: str) → str`,
`astream_invoke(agent: Any, message: str) → AsyncIterator[HarnessEvent]`,
and `spawn_sub_agent(role: RoleConfig, task: str, tools: list,
extensions: list, context: DelegationContext | None = None) → str`.
The `tools` parameter of `create_agent` (and
`spawn_sub_agent`) is the complete, already-aggregated tool list
produced by `ToolPolicy.authorized_tools()` — the tool policy is the
sole tool aggregator. Harness implementations MUST NOT re-aggregate,
re-derive, filter, or re-wrap extension tools from the `extensions`
argument; that parameter is retained for non-tool concerns only
(lifecycle hooks, health checks). This keeps aggregation at one seam
so a tool-search/ranking stage can slot into the tool policy without
touching any harness. The `astream_invoke` method is an additive
streaming variant of `invoke`; it MUST NOT replace or alter the
contract of the existing blocking `invoke` method, which remains
callable by the CLI REPL.

The `context` parameter of `spawn_sub_agent` (P12 delegation-context)
is ADDITIVE: `None` — including every pre-P12 call shape — MUST
preserve the prior behavior exactly, with the sub-agent's composed
prompt byte-identical to pre-P12 output. When a `DelegationContext`
is provided, the concrete harness MUST thread it to the sub-harness
and render `context.render()` as a `## Delegation context` block
prepended AHEAD of the D27 `## Recent context` section (when present)
and the composed system prompt, so the sub-agent reads its delegation
identity and constraints first.

#### Scenario: SdkHarnessAdapter.create_agent consumes the aggregated tool list as-is

- **WHEN** `create_agent(tools, extensions)` is called on any concrete
  `SdkHarnessAdapter` implementation
- **THEN** the harness MUST construct an agent whose tool set is
  exactly the provided `tools` (rendered to the harness's native tool
  shape as needed)
- **AND** the harness MUST NOT derive additional tools from
  `extensions`

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

#### Scenario: spawn_sub_agent renders the delegation context block

- **WHEN** `spawn_sub_agent(role, task, tools, extensions,
  context=<DelegationContext>)` is awaited on either SDK harness
- **THEN** the sub-agent's composed system prompt MUST contain the
  `## Delegation context` block
- **AND** the block MUST appear before the `## Recent context`
  section (when snippets exist) and before the composed role prompt

#### Scenario: spawn_sub_agent without context preserves pre-P12 output

- **WHEN** `spawn_sub_agent(role, task, tools, extensions)` is
  awaited with no context
- **THEN** the sub-agent's composed system prompt MUST NOT contain
  `## Delegation context` and MUST equal the pre-P12 composition

### Requirement: Host Harness Adapter

The system SHALL define a `HostHarnessAdapter` abstract base class
extending `HarnessAdapter` with `harness_type() → "host"` and requiring
the methods `export_context(capabilities: CapabilitySet) → dict[str,
str]`, `export_guardrail_declarations(capabilities: CapabilitySet) →
list[dict[str, Any]]`, and `export_tool_manifest(capabilities:
CapabilitySet) → dict[str, Any]`.

#### Scenario: export_context returns string artifacts

- **WHEN** `ClaudeCodeHarness.export_context(capabilities)` is called
- **THEN** the returned dict MUST contain a `"system_prompt"` key with
  the composed system prompt
- **AND** it MUST contain a `"memory_context"` key with exported memory

#### Scenario: export_tool_manifest returns tool descriptions

- **WHEN** `ClaudeCodeHarness.export_tool_manifest(capabilities)` is
  called
- **THEN** the returned dict MUST contain keys for each tool source
  available to the persona

### Requirement: Claude Code Host Harness

The system SHALL provide a `ClaudeCodeHarness` implementation of
`HostHarnessAdapter` that generates artifacts suitable for Claude Code
integration (CLAUDE.md sections, MCP server references, skill
definitions).

#### Scenario: Harness name and type

- **WHEN** `ClaudeCodeHarness(persona, role).name()` is called
- **THEN** it MUST return `"claude_code"`
- **AND** `harness_type()` MUST return `"host"`

#### Scenario: export_context includes persona and role prompts

- **WHEN** `export_context(capabilities)` is called
- **THEN** the `"system_prompt"` value MUST contain the persona's
  `display_name`
- **AND** it MUST contain the role's prompt content

### Requirement: Harness Factory Two-Tier Routing

The harness factory SHALL accept both SDK and host harness names,
routing to the appropriate adapter type. The factory validation SHALL
check that the requested harness type (sdk or host) matches the
registration.

#### Scenario: Factory creates SDK harness

- **WHEN** `create_harness(persona, role, "deep_agents")` is called
- **AND** `persona.harnesses["deep_agents"]["enabled"] == true`
- **THEN** the returned adapter MUST be a `SdkHarnessAdapter` instance

#### Scenario: Factory creates host harness

- **WHEN** `create_harness(persona, role, "claude_code")` is called
- **THEN** the returned adapter MUST be a `HostHarnessAdapter` instance

#### Scenario: Unknown harness name raises

- **WHEN** `create_harness(persona, role, "nonexistent")` is called
- **THEN** `ValueError` MUST be raised referencing available harness
  names

### Requirement: Harness Invocation Emits Observability Span

The system SHALL emit exactly one `trace_llm_call` observability span
per invocation of any `SdkHarnessAdapter.invoke(...)` implementation.
A `@traced_harness` decorator SHALL record the start time, await the
underlying call, and then invoke
`get_observability_provider().trace_llm_call(...)` after either
success or caught exception — never before, because `duration_ms` and
output token counts are not known until the awaited call completes.

The emitted call MUST include the persona name, role name, model
identifier drawn from the harness configuration, input/output token
counts when reported by the harness, and the measured `duration_ms`.
When the awaited harness call raises an exception, the decorator MUST
catch, emit the span with `metadata={"error": type(exc).__name__}` and
`duration_ms` equal to the elapsed time until the exception, then
re-raise the original exception unchanged.

The integration SHALL be implemented via a `@traced_harness`
decorator applied to each concrete subclass of `SdkHarnessAdapter`.
Applying the decorator to the abstract base at
`src/assistant/harnesses/base.py` does NOT propagate to subclasses
that override `invoke` entirely; therefore the decorator MUST be
applied to concrete implementations directly —
`DeepAgentsHarness.invoke` at
`src/assistant/harnesses/sdk/deep_agents.py` and the
`MSAgentFrameworkHarness.invoke` (now a fully implemented method
that awaits `agent.run`) at
`src/assistant/harnesses/sdk/ms_agent_fw.py`. Future harness
implementations SHALL apply the same decorator at the point of
concrete subclass definition.

#### Scenario: Deep Agents harness invocation is traced

- **WHEN** `DeepAgentsHarness(persona, role).invoke(agent, "hello")`
  at `src/assistant/harnesses/sdk/deep_agents.py` is awaited with
  persona `personal` and role `assistant`
- **THEN** `get_observability_provider().trace_llm_call` MUST be
  called exactly once after the awaited underlying call completes
- **AND** the emitted call's kwargs MUST include `persona="personal"`,
  `role="assistant"`, and a `model` value drawn from the harness
  configuration
- **AND** the emitted `duration_ms` MUST be a non-negative float
  measuring the elapsed time across the awaited call

#### Scenario: Harness exception still emits trace before propagating

- **WHEN** the underlying harness raises `RuntimeError("quota
  exceeded")`
- **THEN** `trace_llm_call` MUST be called once with
  `metadata={"error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller
  unchanged

#### Scenario: Noop provider produces no side effects

- **WHEN** the active provider is the default noop provider and
  `invoke` is awaited
- **THEN** the `@traced_harness` decorator MUST still invoke
  `trace_llm_call`
- **AND** the noop provider's method MUST return without performing
  any I/O or raising

#### Scenario: MSAgentFrameworkHarness invoke emits trace on the success path

- **WHEN** the registered `MSAgentFrameworkHarness.invoke()` is
  awaited (which now calls the real `agent.run` from the
  `agent-framework` package per the `ms-agent-framework-harness`
  capability spec)
- **AND** the underlying `agent.run` returns the string `"hello"`
- **THEN** `@traced_harness` MUST be applied to that method
- **AND** `trace_llm_call` MUST be called exactly once after
  `agent.run` returns
- **AND** the returned value MUST equal `"hello"`

#### Scenario: MSAgentFrameworkHarness exception path still emits trace

- **WHEN** `MSAgentFrameworkHarness.invoke()` is awaited and the
  underlying `agent.run` raises `RuntimeError("model unavailable")`
- **THEN** `trace_llm_call` MUST be called once with
  `metadata={"error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller
  unchanged

### Requirement: Multi-Turn Conversation Memory

The `DeepAgentsHarness` SHALL preserve conversation history across
successive `invoke` calls on a single harness instance by
constructing its underlying agent with a `checkpointer` and passing a
stable `thread_id` in the invocation `config` on every call. The
`thread_id` MUST be generated once per harness instance (at
`create_agent` time) and MUST NOT change between `invoke` calls on
that instance. A new harness instance MUST be assigned a new,
distinct `thread_id` so that role-switch rebuilds (which construct a
fresh harness) start a fresh conversation.

#### Scenario: create_agent constructs the agent with a checkpointer

- **WHEN** `DeepAgentsHarness(persona, role).create_agent(tools, extensions)`
  is called
- **THEN** the `create_deep_agent` factory MUST receive a non-None
  `checkpointer` keyword argument
- **AND** `self._thread_id` MUST be set to a non-empty string

#### Scenario: invoke passes the harness thread_id on every call

- **WHEN** `DeepAgentsHarness.invoke(agent, message)` is called
- **THEN** the call to `agent.ainvoke` MUST include a `config` argument
  whose `configurable.thread_id` field equals `self._thread_id`

#### Scenario: A second invoke on the same harness sees prior history

- **WHEN** `DeepAgentsHarness.invoke(agent, "first turn")` is called
- **AND** `DeepAgentsHarness.invoke(agent, "second turn")` is called
  immediately after on the same harness instance and same agent
- **THEN** the messages list the model receives on the second call
  MUST contain both the user message `"first turn"` and the assistant
  response to the first turn
- **AND** the model receives the new user message `"second turn"`
  appended to that history

#### Scenario: Two harness instances have distinct thread_ids

- **WHEN** two separate `DeepAgentsHarness` instances each call
  `create_agent(tools, extensions)`
- **THEN** `harness_a._thread_id` MUST NOT equal `harness_b._thread_id`
- **AND** invoking `harness_b` MUST NOT see any messages produced by
  invoking `harness_a` (the two threads are isolated)

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
- **AND** the value MUST match the pattern
  `^(?:[a-z_][a-zA-Z0-9_]*\.)*[A-Z][A-Za-z0-9_]*$` (Python class
  identifier with optional dotted module qualifier — allows lowercase
  or underscore-leading module segments followed by an uppercase-
  leading class name; matches the same pattern in both JSON schemas)

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

### Requirement: Durable Session Persistence

The system SHALL make SDK harness sessions durable through
checkpointer-backed persistence. For the DeepAgents harness this
adopts the LangGraph checkpointer interface rather than inventing a
session store: the harness SHALL accept an injected checkpointer at
agent-construction time, keep `InMemorySaver` as the in-process
default, and support a Postgres checkpointer implementation as the
durable backend. When a durable checkpointer is configured, all
conversation state keyed by `thread_id` — including runs suspended by
the approval interrupt contract — MUST survive process restarts and
be resumable by `thread_id` alone. Other SDK harnesses SHALL expose
the same injection seam (a session-persistence object accepted at
construction) so cross-harness session parity is a wiring concern,
not a redesign.

#### Scenario: Checkpointer is injectable

- **WHEN** `DeepAgentsHarness` is constructed with an explicit
  checkpointer
- **AND** `create_agent(tools, extensions)` is called
- **THEN** the underlying agent MUST be constructed with that
  checkpointer instance
- **AND** omitting the injection MUST preserve the `InMemorySaver`
  default

#### Scenario: Postgres-backed session survives a restart

- **WHEN** a conversation runs against a Postgres checkpointer with
  `thread_id="t1"`
- **AND** the process restarts and a new harness is constructed with
  the same checkpointer backend
- **THEN** invoking with `thread_id="t1"` MUST see the prior
  conversation history

#### Scenario: Suspended runs are resumable by thread_id

- **WHEN** a run on `thread_id="t2"` is suspended awaiting approval
  (guardrail-provider approval interrupt contract)
- **THEN** the suspended state MUST be recoverable from the durable
  checkpointer using `thread_id="t2"` alone

### Requirement: Session Registry

The system SHALL provide a session registry that creates, looks up,
and expires sessions keyed by `thread_id`, so serving surfaces (web
transport, the P7 daemon, the P6 A2A server) can multiplex concurrent
users and tasks instead of binding one global harness at startup.
`create` SHALL produce a new session (persona/role-bound harness and
agent) and return its `thread_id`; `lookup` SHALL return the live
session for a known `thread_id` and signal unknown ids distinctly;
`expire` SHALL release a session's in-process resources by
`thread_id` or idle TTL policy — expiry releases the in-process
session but MUST NOT delete durably checkpointed state, which remains
resumable by re-creating a session bound to the same `thread_id`.

#### Scenario: Registry multiplexes concurrent sessions

- **WHEN** two sessions are created for the same persona and role
- **THEN** they MUST have distinct `thread_id` values
- **AND** invoking one session MUST NOT observe messages from the
  other

#### Scenario: Lookup returns the live session

- **WHEN** a session is created with `thread_id="t1"`
- **AND** `lookup("t1")` is called before expiry
- **THEN** it MUST return the same session instance

#### Scenario: Unknown thread_id is signaled distinctly

- **WHEN** `lookup("never-created")` is called
- **THEN** the registry MUST signal an unknown-session condition
  (error or `None` per implementation) rather than silently creating
  a new session

#### Scenario: Expiry releases the session but not durable state

- **WHEN** a session with a durable checkpointer is expired
- **AND** a new session is created bound to the same `thread_id`
- **THEN** the prior conversation history MUST still be visible to
  the new session

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

### Requirement: Automatic Harness Selection

The system SHALL provide a `select_harness(persona, role, *,
requested=None)` function in `harnesses/factory.py` that
deterministically resolves the harness name for a persona × role
composition without any LLM call, with the following precedence:

1. An explicit `requested` harness name (any value other than `None`
   or the `auto` sentinel) SHALL be returned verbatim — explicit
   selection always bypasses routing (enablement validation remains
   `create_harness`'s job).
2. The persona's ordered `harnesses.routing:` rules SHALL be
   evaluated first-match: a rule matches when its `role:` glob (when
   declared) matches the role name AND (when declared) any of its
   `tools:` globs matches any role `preferred_tools` entry. A
   `tools:` pattern containing `:` matches the full
   `source:operation` string; a bare pattern matches the source
   prefix. A matching rule whose target harness is not enabled for
   the persona SHALL be skipped with a WARNING and evaluation SHALL
   continue; a matching rule naming an unregistered harness or a host
   harness SHALL raise `ValueError`.
3. Built-in defaults SHALL apply when no rule matches: when any role
   `preferred_tools` entry references an MS tool source (`ms_graph`,
   `outlook`, `teams`, `sharepoint`) and `ms_agent_framework` is
   enabled, the result is `ms_agent_framework`; otherwise
   `deep_agents` when enabled; otherwise the remaining enabled SDK
   harness; otherwise `ValueError` naming the persona and pointing at
   explicit host-tier selection.

A host harness MUST NOT ever be returned by rules or built-in
defaults — host harnesses export configuration rather than execute,
so auto-selecting one would silently no-op an interactive run; the
host (subscription) tier is reachable only by explicit request.

#### Scenario: Explicit request bypasses routing

- **WHEN** `select_harness(persona, role, requested="deep_agents")`
  is called for a persona whose routing rules would select
  `ms_agent_framework`
- **THEN** the returned name MUST equal `"deep_agents"`

#### Scenario: MS-source preferred_tools route to MSAF

- **WHEN** the role's `preferred_tools` contains `outlook:send_mail`
- **AND** `persona.harnesses["ms_agent_framework"]["enabled"]` is true
- **AND** `select_harness(persona, role)` is called with no routing
  rules declared
- **THEN** the returned name MUST equal `"ms_agent_framework"`

#### Scenario: MS-tool role falls back when MSAF is disabled

- **WHEN** the role's `preferred_tools` contains `ms_graph:list_users`
- **AND** `ms_agent_framework` is not enabled for the persona
- **AND** `deep_agents` is enabled
- **THEN** `select_harness(persona, role)` MUST return `"deep_agents"`

#### Scenario: Persona routing rules match first

- **WHEN** the persona declares
  `harnesses.routing: [{role: "coder", harness: ms_agent_framework}]`
- **AND** `ms_agent_framework` is enabled
- **AND** `select_harness(persona, coder_role)` is called
- **THEN** the returned name MUST equal `"ms_agent_framework"` even
  though the role prefers no MS-source tools

#### Scenario: Matching rule with disabled target is skipped

- **WHEN** the first routing rule matches but names a harness with
  `enabled: false`
- **AND** a later rule (or the built-in default) yields an enabled
  harness
- **THEN** `select_harness` MUST return the later result
- **AND** a WARNING naming the skipped rule MUST be logged

#### Scenario: Rule targeting a host harness raises

- **WHEN** a matching routing rule declares `harness: claude_code`
- **THEN** `select_harness` MUST raise `ValueError` indicating host
  harnesses cannot be auto-selected

#### Scenario: Host harness never auto-selected by defaults

- **WHEN** only `claude_code` is enabled for the persona
- **AND** `select_harness(persona, role)` is called
- **THEN** `ValueError` MUST be raised rather than returning
  `"claude_code"`

### Requirement: Harness Routing Decision Telemetry

Every `select_harness` resolution SHALL emit exactly one
`harness.routing` span through the observability provider's
`start_span` escape hatch, carrying attributes for the persona name,
role name, requested value (or `auto`), selected harness, and the
selection reason (`explicit`, a rule reference, or a
`builtin:*` label), and SHALL log one INFO line with the same facts.
Emission MUST be defensive: a failing telemetry provider logs a
WARNING and MUST NOT change the selection outcome.

#### Scenario: Routing decision emits a span

- **WHEN** `select_harness(persona, role)` resolves to
  `"deep_agents"` via the built-in default
- **THEN** `start_span` MUST be called once with the span name
  `"harness.routing"`
- **AND** the attributes MUST include `selected == "deep_agents"`
  and a `reason` beginning with `"builtin:"`

#### Scenario: Telemetry failure does not break selection

- **WHEN** the observability provider's `start_span` raises
- **THEN** `select_harness` MUST still return the selected harness
- **AND** a WARNING MUST be logged

