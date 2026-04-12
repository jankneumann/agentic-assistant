# extension-registry Specification

## Purpose
TBD - created by archiving change bootstrap-vertical-slice. Update Purpose after archive.
## Requirements
### Requirement: Extension Protocol

The system SHALL define an `Extension` runtime-checkable Protocol with a `name`
attribute and the methods `as_langchain_tools()`, `as_ms_agent_tools()`, and
`async health_check()`.

#### Scenario: Stub implementation satisfies Protocol

- **WHEN** a class defines `name: str`, `as_langchain_tools() -> list`,
  `as_ms_agent_tools() -> list`, and `async def health_check() -> bool`
- **THEN** `isinstance(instance, Extension)` MUST return `True`

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

