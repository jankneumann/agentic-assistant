# harness-adapter — spec delta

## MODIFIED Requirements

### Requirement: Abstract Harness Adapter Contract

The system SHALL define an abstract `HarnessAdapter` base class with a
`harness_type() → str` property returning either `"sdk"` or `"host"`,
in addition to the existing `name() → str` method.

#### Scenario: harness_type identifies adapter category

- **WHEN** `DeepAgentsHarness(persona, role).harness_type()` is called
- **THEN** it MUST return `"sdk"`

## ADDED Requirements

### Requirement: SDK Harness Adapter

The system SHALL define an `SdkHarnessAdapter` abstract base class
extending `HarnessAdapter` with `harness_type() → "sdk"` and requiring
the methods `create_agent(capabilities: CapabilitySet) → Any`,
`invoke(agent: Any, message: str) → str`, and
`spawn_sub_agent(role: RoleConfig, task: str, capabilities:
CapabilitySet) → str`.

#### Scenario: SdkHarnessAdapter.create_agent receives capabilities

- **WHEN** `DeepAgentsHarness.create_agent(capabilities)` is called
- **THEN** the harness MUST use `capabilities.memory.resolve()` to
  obtain memory config instead of reading `memory_files` directly
- **AND** the harness MUST use `capabilities.tools.authorized_tools()`
  to obtain tools instead of receiving them as a parameter

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
