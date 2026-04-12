# harness-adapter Specification

## Purpose
TBD - created by archiving change bootstrap-vertical-slice. Update Purpose after archive.
## Requirements
### Requirement: Abstract Harness Adapter Contract

The system SHALL define an abstract `HarnessAdapter` base class requiring the
methods `create_agent(tools, extensions)`, `invoke(agent, message)`,
`spawn_sub_agent(role, task, tools, extensions)`, and `name()`.

#### Scenario: Instantiating the abstract class raises

- **WHEN** `HarnessAdapter(persona, role)` is called directly
- **THEN** `TypeError` MUST be raised because the class is abstract

#### Scenario: Concrete subclass must implement all methods

- **WHEN** a subclass of `HarnessAdapter` is defined without implementing one
  of the abstract methods
- **THEN** instantiating that subclass MUST raise `TypeError`

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

