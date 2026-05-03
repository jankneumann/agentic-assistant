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

### Requirement: Extension Tool Invocations Emit Observability Span

The system SHALL ensure that every LangChain `StructuredTool` returned by any `Extension.as_langchain_tools()` emits a `trace_tool_call` observability span on each invocation. Because `Extension` is a `typing.Protocol` (not a base class that carries behavior for subclasses), the wrapping SHALL be performed at the aggregation sites that compose extension tool bundles — see the `capability-resolver` capability spec for the authoritative list of aggregation sites and the shared `wrap_extension_tools` helper. Individual extension implementations SHALL NOT add tracing code themselves.

The emitted call MUST include `tool_name` (the StructuredTool's `name`), `tool_kind="extension"`, `persona`, `role`, and `duration_ms`. When the tool's `_run` or `_arun` raises, the span MUST be emitted with `error=<exception type name>` before the exception propagates.

Wrapping SHALL preserve each tool's original `name`, `description`, and `args_schema` so that agents and tool-discovery consumers see no change in the tool's public contract.

#### Scenario: Extension tool invocation emits trace_tool_call

- **WHEN** an extension returns a `StructuredTool` named `gmail.search` and `gmail.search.invoke({"query": "foo"})` is called with persona `personal` and role `assistant`
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include `tool_name="gmail.search"`, `tool_kind="extension"`, `persona="personal"`, and `role="assistant"`

#### Scenario: Tool exception emits trace before propagating

- **WHEN** a wrapped tool's `_run` raises `ValueError("invalid query")`
- **THEN** `trace_tool_call` MUST be called with `error="ValueError"`
- **AND** the exception MUST propagate to the caller

#### Scenario: Tool metadata passthrough is preserved

- **WHEN** an extension returns a `StructuredTool` with `name="x"`, `description="y"`, and a specific `args_schema`
- **THEN** the wrapped tool exposed by `as_langchain_tools()` MUST have the identical `name`, `description`, and `args_schema`

