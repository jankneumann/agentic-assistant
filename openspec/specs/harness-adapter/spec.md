# harness-adapter Specification

## Purpose
TBD - created by archiving change bootstrap-vertical-slice. Update Purpose after archive.
## Requirements
### Requirement: Abstract Harness Adapter Contract

The system SHALL define an abstract `HarnessAdapter` base class with a
`harness_type() → str` property returning either `"sdk"` or `"host"`,
in addition to the existing `name() → str` method.

#### Scenario: harness_type identifies adapter category

- **WHEN** `DeepAgentsHarness(persona, role).harness_type()` is called
- **THEN** it MUST return `"sdk"`

### Requirement: Deep Agents Harness Implementation

The system SHALL provide a `DeepAgentsHarness` implementation that constructs
a Deep Agents agent using the persona's configured model, the composed system
prompt, and tools from both the discovered HTTP tool list and each loaded
extension's `as_langchain_tools()`.

#### Scenario: Harness name is deep_agents

- **WHEN** `DeepAgentsHarness(persona, role).name()` is called
- **THEN** it MUST return the string `"deep_agents"`

#### Scenario: create_agent uses the persona-configured model

- **WHEN** `persona.harnesses["deep_agents"]["model"]` equals
  `"anthropic:claude-sonnet-4-20250514"`
- **THEN** `create_agent(tools, extensions)` MUST construct a Deep Agents
  agent initialized with that model identifier

#### Scenario: create_agent includes extension tools

- **WHEN** one of the `extensions` returns `[tool_A]` from
  `as_langchain_tools()`
- **AND** `tools == [tool_B]`
- **THEN** the constructed agent's tool set MUST contain both `tool_A` and
  `tool_B`

#### Scenario: invoke returns the last assistant message content

- **WHEN** a fake agent whose `ainvoke` coroutine returns
  `{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}`
  is passed to `DeepAgentsHarness.invoke(agent, "q")`
- **THEN** the returned value MUST equal `"a"`

### Requirement: MS Agent Framework Harness Registered but Stubbed

The system SHALL register an `MSAgentFrameworkHarness` in the harness factory
whose `create_agent` raises `NotImplementedError` with a message indicating it
is deferred to a later proposal.

#### Scenario: Factory returns MS AF harness for enabled persona

- **WHEN** `persona.harnesses["ms_agent_framework"]["enabled"] == true`
- **AND** `create_harness(persona, role, "ms_agent_framework")` is called
- **THEN** the returned object MUST be an `MSAgentFrameworkHarness` instance

#### Scenario: MS AF create_agent raises NotImplementedError

- **WHEN** `MSAgentFrameworkHarness.create_agent(tools, extensions)` is called
- **THEN** `NotImplementedError` MUST be raised
- **AND** the message MUST reference that the full implementation is
  deferred (e.g., "P5" or "later proposal")

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
`invoke(agent: Any, message: str) → str`, and
`spawn_sub_agent(role: RoleConfig, task: str, tools: list,
extensions: list) → str`. The `create_agent` signature retains the
P1 tools/extensions parameters; migration to `CapabilitySet`-based
invocation is deferred to P2 (memory-architecture) when concrete
`MemoryPolicy` implementations exist to inject.

#### Scenario: SdkHarnessAdapter.create_agent accepts tools and extensions

- **WHEN** `DeepAgentsHarness.create_agent(tools, extensions)` is called
- **THEN** the harness MUST construct an agent with the provided tools
  and extension tools combined
- **AND** the harness MUST read memory configuration from persona config

#### Scenario: SdkHarnessAdapter.invoke signature unchanged

- **WHEN** `invoke(agent, message)` is called
- **THEN** the returned value MUST be a string containing the agent's
  response

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

