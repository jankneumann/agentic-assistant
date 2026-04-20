# tool-policy Specification

## Purpose
TBD - created by archiving change capability-protocols. Update Purpose after archive.
## Requirements
### Requirement: ToolPolicy Protocol

The system SHALL define a `ToolPolicy` runtime-checkable Protocol with
the methods `authorized_tools(persona, role, *, loaded_extensions)
→ list[Any]`, `authorized_extensions(persona, role, *,
loaded_extensions) → list[Any]`, and `export_tool_manifest(persona,
role) → dict[str, Any]`. The `loaded_extensions` keyword argument
receives pre-loaded extensions from the caller (CLI or harness),
keeping ToolPolicy decoupled from PersonaRegistry.

#### Scenario: Stub implementation satisfies Protocol

- **WHEN** a class implements `authorized_tools`,
  `authorized_extensions`, and `export_tool_manifest` with the correct
  signatures
- **THEN** `isinstance(instance, ToolPolicy)` MUST return `True`

### Requirement: DefaultToolPolicy Implementation

The system SHALL provide a `DefaultToolPolicy` implementation that
returns all tools from the provided `loaded_extensions` filtered by
the role's `preferred_tools` list when non-empty, or all tools when
`preferred_tools` is empty.

#### Scenario: All extension tools when preferred_tools is empty

- **WHEN** `role.preferred_tools` is `[]`
- **AND** `loaded_extensions` provide `[tool_a, tool_b]`
- **THEN** `authorized_tools()` MUST return a list containing both
  `tool_a` and `tool_b`

#### Scenario: Filtered by preferred_tools

- **WHEN** `role.preferred_tools` is `["tool_a"]`
- **AND** `loaded_extensions` provide `[tool_a, tool_b]`
- **THEN** `authorized_tools()` MUST return a list containing `tool_a`
- **AND** `tool_b` MUST NOT be in the returned list

#### Scenario: Extension authorization returns loaded extensions

- **WHEN** `authorized_extensions(persona, role, loaded_extensions=[ext1, ext2])` is called
- **THEN** the returned list MUST contain both `ext1` and `ext2`

### Requirement: Tool Manifest Export

The `export_tool_manifest` method SHALL return a dictionary describing
available tools in a format suitable for host-harness integration (MCP
server configs, skill registrations).

#### Scenario: Manifest includes extension metadata

- **WHEN** `export_tool_manifest()` is called with a persona that has
  `extensions: [{module: "gmail", config: {scopes: ["read"]}}]`
- **THEN** the returned dict MUST contain a key `"extensions"` with an
  entry for `"gmail"`

#### Scenario: Manifest includes tool_sources

- **WHEN** `persona.tool_sources` contains `{"backend": {"base_url_env":
  "URL"}}`
- **THEN** the returned dict MUST contain a key `"tool_sources"` with an
  entry for `"backend"`

