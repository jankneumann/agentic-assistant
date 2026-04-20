# extension-registry Specification

## Purpose
TBD - created by archiving change bootstrap-vertical-slice. Update Purpose after archive.
## Requirements
### Requirement: Extension Protocol

The `Extension` Protocol SHALL retain its existing `as_langchain_tools()`
and `as_ms_agent_tools()` methods. Extensions become one tool source
managed by `ToolPolicy` alongside HTTP tools and MCP servers.

#### Scenario: Extensions accessible via ToolPolicy

- **WHEN** `ToolPolicy.authorized_extensions(persona, role)` is called
- **THEN** the returned list MUST contain all loaded extensions for the
  persona
- **AND** each extension MUST satisfy `isinstance(ext, Extension)`

### Requirement: Stub Implementations for All Configured Extensions

The system SHALL ship stub implementations for `ms_graph`, `teams`,
`sharepoint`, `outlook`, `gmail`, `gcal`, and `gdrive` in
`src/assistant/extensions/`, each exposing a `create_extension(config: dict)`
factory returning an `Extension`-compatible instance.

#### Scenario: Each stub exports create_extension

- **WHEN** the module `assistant.extensions.<name>` is imported for each of the
  seven extension names
- **THEN** each module MUST define a callable `create_extension`

#### Scenario: Stubs return empty tool lists

- **WHEN** `create_extension({}).as_langchain_tools()` is called on any stub
- **THEN** it MUST return `[]`
- **AND** `as_ms_agent_tools()` MUST return `[]`

#### Scenario: Stub health_check returns True

- **WHEN** `await create_extension({}).health_check()` is called on any stub
- **THEN** it MUST return `True`

### Requirement: Extension config is passed to constructor

Each stub's `create_extension` SHALL pass its `config` argument to the
underlying class constructor, and the resulting instance SHALL expose
`self.scopes` when the config contains a `scopes` key.

#### Scenario: Scopes are stored on the instance

- **WHEN** `create_extension({"scopes": ["s1", "s2"]})` is called
- **THEN** the returned instance's `.scopes` attribute MUST equal
  `["s1", "s2"]`

#### Scenario: Missing scopes default to empty list

- **WHEN** `create_extension({})` is called
- **THEN** the returned instance's `.scopes` attribute MUST equal `[]`

