## ADDED Requirements

### Requirement: MSAgentFrameworkHarness Full Implementation

The system SHALL provide a full `MSAgentFrameworkHarness`
implementation in `src/assistant/harnesses/sdk/ms_agent_fw.py` that
satisfies the `SdkHarnessAdapter` contract from the existing
`harness-adapter` capability. The implementation SHALL use the
official `agent-framework` Python package
(`pip install agent-framework`, repo
`github.com/microsoft/agent-framework`). The previous stub that
raised `NotImplementedError` SHALL be removed.

#### Scenario: Harness is registered and instantiable

- **WHEN** `persona.harnesses["ms_agent_framework"]["enabled"] == true`
- **AND** `create_harness(persona, role, "ms_agent_framework")` is
  called
- **THEN** the returned object MUST be an `MSAgentFrameworkHarness`
  instance
- **AND** calling `instance.harness_type()` MUST return `"sdk"`
- **AND** calling `instance.name()` MUST return `"ms_agent_framework"`

#### Scenario: create_agent no longer raises NotImplementedError

- **WHEN** `MSAgentFrameworkHarness.create_agent(tools=[],
  extensions=[])` is awaited
- **THEN** `NotImplementedError` MUST NOT be raised
- **AND** the returned value MUST be an `agent_framework.Agent`
  instance

### Requirement: create_agent Builds an agent_framework.Agent

The system SHALL construct an `agent_framework.Agent` in
`create_agent()` using: (a) the persona-configured chat client (one of
`agent_framework.openai.OpenAIChatClient` or
`agent_framework.azure_openai.AzureOpenAIChatClient`), (b) the composed
system prompt (from the persona × role composition) as the
`instructions` parameter, and (c) the union of provided `tools` plus
each extension's `as_ms_agent_tools()` output as the `tools`
parameter.

#### Scenario: Agent receives composed instructions

- **WHEN** `compose_system_prompt(persona, role)` returns the string
  `"You are work assistant."`
- **AND** `create_agent(tools=[], extensions=[])` is awaited
- **THEN** the constructed `Agent` MUST be initialized with
  `instructions="You are work assistant."`

#### Scenario: Agent receives extension tools via as_ms_agent_tools

- **WHEN** an extension's `as_ms_agent_tools()` returns
  `[outlook_list_messages]`
- **AND** `create_agent(tools=[ad_hoc_tool],
  extensions=[outlook_extension])` is awaited
- **THEN** the constructed `Agent` MUST have both
  `outlook_list_messages` and `ad_hoc_tool` in its `tools` list
- **AND** the harness MUST NOT consume `as_langchain_tools()`

#### Scenario: Chat client selection respects persona configuration

- **WHEN** `persona.harnesses["ms_agent_framework"]["chat_client"] ==
  "azure_openai"`
- **AND** `create_agent(...)` is awaited
- **THEN** the constructed `Agent`'s `client` MUST be an
  `AzureOpenAIChatClient` instance

### Requirement: invoke Awaits agent.run and Returns String

The system SHALL implement `invoke(agent, message)` to await
`agent.run(message)` and return the response as a string. If the
underlying `agent.run` raises, the original exception SHALL propagate
unchanged after the existing `@traced_harness` decorator emits its
observability span.

#### Scenario: invoke returns the agent's response string

- **WHEN** a fake agent whose `run` coroutine returns the string
  `"42"` is passed to `MSAgentFrameworkHarness.invoke(agent, "what is
  the answer?")`
- **THEN** the returned value MUST equal `"42"`

#### Scenario: invoke propagates underlying exceptions unchanged

- **WHEN** the underlying agent's `run` raises
  `ValueError("rate limited")`
- **AND** the `@traced_harness` decorator is in scope
- **THEN** `trace_llm_call` MUST be invoked once with
  `metadata={"error": "ValueError"}` (per harness-adapter spec)
- **AND** the original `ValueError` MUST propagate to the caller

### Requirement: spawn_sub_agent Builds a Nested Agent for the Sub-Role

The system SHALL implement `spawn_sub_agent(role, task, tools,
extensions)` by constructing a new `MSAgentFrameworkHarness` instance
for the sub-role, calling its `create_agent` and then `invoke` with
the supplied `task` string, and returning the response.

#### Scenario: spawn_sub_agent returns the sub-agent's response

- **WHEN** `spawn_sub_agent(role=sub_role, task="search docs",
  tools=[], extensions=[outlook_extension])` is awaited on a parent
  harness
- **AND** the sub-agent's underlying `agent.run` coroutine returns
  `"found 3 docs"`
- **THEN** the returned value MUST equal `"found 3 docs"`

#### Scenario: Sub-agent uses sub-role's composed prompt

- **WHEN** `spawn_sub_agent(role=sub_role, ...)` is awaited
- **AND** `compose_system_prompt(persona, sub_role)` returns
  `"You are research assistant."`
- **THEN** the underlying `Agent` constructed for the sub-agent MUST
  have `instructions="You are research assistant."`

### Requirement: Capability Consumption

The system SHALL consume capabilities from the P1.8
`CapabilityResolver`: `ToolPolicy` (to determine authorized
extensions), `ContextProvider` (for the system prompt),
`GuardrailProvider` (to gate `spawn_sub_agent`), and `MemoryPolicy`
(for minimal memory injection — see "Memory Snippet Injection"
requirement below).

#### Scenario: Authorized extensions are filtered through ToolPolicy

- **WHEN** the `ToolPolicy` returns
  `authorized_extensions(persona, role) == [outlook_extension]`
- **AND** `create_agent(tools=[], extensions=[outlook_extension,
  teams_extension])` would otherwise see both
- **THEN** the harness MUST consult `ToolPolicy.authorized_extensions`
  before reading `as_ms_agent_tools()`
- **AND** only the authorized subset's tools MUST flow into the
  constructed `Agent`

#### Scenario: spawn_sub_agent calls GuardrailProvider before constructing sub-agent

- **WHEN** `spawn_sub_agent(role=sub_role, task="X", ...)` is awaited
- **AND** the configured `GuardrailProvider` is non-noop
- **THEN** `GuardrailProvider.check_action(ActionRequest(kind=
  "delegate", target_role=sub_role.name, task="X"))` MUST be invoked
  before any `Agent` construction
- **AND** if the decision is denied, the sub-agent MUST NOT be
  created and a `PermissionError` MUST be raised

### Requirement: Memory Snippet Injection in create_agent

The system SHALL inject the persona's recent memory snippets into the
constructed `Agent`'s `instructions` parameter at `create_agent`
time. The harness SHALL request the snippets via the configured
`MemoryPolicy.get_recent_snippets(persona, role, limit=N)` (where N
defaults to 10), and SHALL prepend the resulting text block to the
composed system prompt under a clearly demarcated section heading
(`## Recent context`). When the persona has no `MemoryPolicy`
configured, or the policy returns an empty list, no section MUST be
injected and the instructions MUST equal the composed prompt
unchanged.

This closes the asymmetry with the DeepAgents harness (which already
consumes `MemoryPolicy`) by ensuring MSAF agents on the work persona
have access to the same recent-context snippets without requiring
any change to the `agent-framework` SDK contract.

**Follow-up scope** — P5 deliberately ships the *minimum* viable
memory injection: a string prepend at `create_agent` time. A
higher-fidelity integration (live retrieval mid-turn, structured
memory items rather than concatenated text, write-back of agent
observations to memory) requires a structured memory hook on the
`agent-framework` SDK that does not exist in the SDK version pinned
by P5. Revisiting this is a P5b candidate when (a) the
`agent-framework` SDK exposes a memory injection point with a stable
contract, OR (b) usage data shows the prepend approach is
insufficient for the work persona. Until then, the asymmetry with
DeepAgents is a documented trade-off (DeepAgents has full
`MemoryPolicy` consumption; MSAF has prepend-only).

#### Scenario: Memory snippets prepended to instructions

- **WHEN** `MemoryPolicy.get_recent_snippets(persona, role,
  limit=10)` returns `["snippet-1", "snippet-2"]`
- **AND** `compose_system_prompt(persona, role)` returns
  `"You are work assistant."`
- **AND** `create_agent(...)` is awaited
- **THEN** the constructed `Agent`'s `instructions` MUST contain the
  substring `"## Recent context"`
- **AND** the instructions MUST contain both `"snippet-1"` and
  `"snippet-2"`
- **AND** the original prompt `"You are work assistant."` MUST also
  appear

#### Scenario: Empty memory snippets leaves instructions unchanged

- **WHEN** `MemoryPolicy.get_recent_snippets(...)` returns `[]`
- **AND** `compose_system_prompt(persona, role)` returns
  `"You are work assistant."`
- **AND** `create_agent(...)` is awaited
- **THEN** the constructed `Agent`'s `instructions` MUST equal
  `"You are work assistant."`
- **AND** the substring `"## Recent context"` MUST NOT appear in the
  instructions

#### Scenario: NoopMemoryPolicy yields no injection

- **WHEN** the persona has no `MemoryPolicy` configured (default
  noop policy is active)
- **AND** `create_agent(...)` is awaited
- **THEN** the harness MUST NOT call `get_recent_snippets` at all
  (or MUST treat the noop result as empty)
- **AND** the constructed `Agent`'s `instructions` MUST equal the
  composed prompt unchanged

### Requirement: @traced_harness Decorator is Applied to invoke

The system SHALL apply the `@traced_harness` decorator from the
`harness-adapter` capability to
`MSAgentFrameworkHarness.invoke` directly at the concrete subclass
level. The previous stub-only application of the decorator (which
relied on `NotImplementedError` propagation) SHALL be replaced with
the live decorator wrapping the now-real `agent.run` call.

#### Scenario: Successful invoke emits trace_llm_call once

- **WHEN** `await MSAgentFrameworkHarness(persona, role).invoke(agent,
  "hello")` succeeds with response `"hi"`
- **THEN** `get_observability_provider().trace_llm_call` MUST be called
  exactly once after the underlying call completes
- **AND** the emitted kwargs MUST include `persona`, `role`, `model`,
  and a non-negative `duration_ms`

#### Scenario: Failed invoke still emits trace_llm_call before propagating

- **WHEN** the underlying `agent.run` raises `RuntimeError("model
  unavailable")`
- **THEN** `trace_llm_call` MUST be called once with
  `metadata={"error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller
  unchanged
