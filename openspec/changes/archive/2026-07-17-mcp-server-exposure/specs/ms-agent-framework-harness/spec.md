# ms-agent-framework-harness Specification (delta)

## MODIFIED Requirements

### Requirement: create_agent Builds an agent_framework.Agent

The system SHALL construct an `agent_framework.Agent` in
`create_agent()` using: (a) the persona-configured chat client (one of
`agent_framework.openai.OpenAIChatClient` or
`agent_framework.azure_openai.AzureOpenAIChatClient`), (b) the composed
system prompt (from the persona × role composition) as the
`instructions` parameter, and (c) the provided `tools` list — the
complete, already-aggregated `ToolSpec` list produced by
`ToolPolicy.authorized_tools()` — rendered to the MSAF native shape
via the per-harness adapter (`render_msaf_tools` →
`agent_framework.FunctionTool`). The harness MUST NOT derive tools
from the `extensions` argument (P17 tool-spec migration; the tool
policy is the sole aggregator per the harness-adapter contract).

#### Scenario: Agent receives composed instructions

- **WHEN** `compose_system_prompt(persona, role)` returns the string
  `"You are work assistant."`
- **AND** `create_agent(tools=[], extensions=[])` is awaited
- **THEN** the constructed `Agent` MUST be initialized with
  `instructions="You are work assistant."`

#### Scenario: Agent receives the rendered aggregated tool list

- **WHEN** `create_agent(tools=[outlook_search_spec],
  extensions=[outlook_extension])` is awaited, where
  `outlook_search_spec` is a `ToolSpec`
- **THEN** the constructed `Agent`'s `tools` list MUST contain the
  MSAF rendering of `outlook_search_spec` (a `FunctionTool` with the
  same name, description, and input schema)
- **AND** the harness MUST NOT call any tool-producing method on
  `outlook_extension`

#### Scenario: Chat client selection respects persona configuration

- **WHEN** `persona.harnesses["ms_agent_framework"]["chat_client"] ==
  "azure_openai"`
- **AND** `create_agent(...)` is awaited
- **THEN** the constructed `Agent`'s `client` MUST be an
  `AzureOpenAIChatClient` instance

### Requirement: Capability Consumption

The system SHALL consume capabilities from the P1.8
`CapabilityResolver`: `ToolPolicy` (upstream, as the sole tool
aggregator whose `authorized_tools()` output arrives via
`create_agent(tools=...)`), `ContextProvider` (for the system prompt),
`GuardrailProvider` (to gate `spawn_sub_agent`), and `MemoryPolicy`
(for minimal memory injection — see "Memory Snippet Injection"
requirement below).

#### Scenario: Tool aggregation happens upstream in ToolPolicy

- **WHEN** `ToolPolicy.authorized_tools(persona, role,
  loaded_extensions=[outlook_extension, teams_extension])` authorizes
  only outlook's specs
- **AND** the caller passes that authorized list to
  `create_agent(tools=<authorized>, extensions=[outlook_extension,
  teams_extension])`
- **THEN** only the authorized specs' renderings MUST flow into the
  constructed `Agent`
- **AND** the harness MUST NOT consult the extensions to add or
  remove tools

#### Scenario: spawn_sub_agent calls GuardrailProvider before constructing sub-agent

- **WHEN** `spawn_sub_agent(role=sub_role, task="X", ...)` is awaited
- **AND** the configured `GuardrailProvider` is non-noop
- **THEN** `GuardrailProvider.check_action(ActionRequest(kind=
  "delegate", target_role=sub_role.name, task="X"))` MUST be invoked
  before any `Agent` construction
- **AND** if the decision is denied, the sub-agent MUST NOT be
  created and a `PermissionError` MUST be raised
