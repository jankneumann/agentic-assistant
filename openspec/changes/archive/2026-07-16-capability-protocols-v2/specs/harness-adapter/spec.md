# harness-adapter Specification (delta)

## MODIFIED Requirements

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

### Requirement: SDK Harness Adapter

The system SHALL define an `SdkHarnessAdapter` abstract base class
extending `HarnessAdapter` with `harness_type() → "sdk"` and requiring
the methods `create_agent(tools: list, extensions: list) → Any`,
`invoke(agent: Any, message: str) → str`,
`astream_invoke(agent: Any, message: str) → AsyncIterator[HarnessEvent]`,
and `spawn_sub_agent(role: RoleConfig, task: str, tools: list,
extensions: list) → str`. The `tools` parameter of `create_agent` (and
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

## ADDED Requirements

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
