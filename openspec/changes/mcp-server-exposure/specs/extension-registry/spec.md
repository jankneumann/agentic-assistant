# extension-registry Specification (delta)

## MODIFIED Requirements

### Requirement: Extension Protocol

The `Extension` Protocol SHALL expose a single harness-neutral tool
surface: `tool_specs() → list[ToolSpec]` (see the `tool-spec`
capability). The legacy `as_langchain_tools()` and
`as_ms_agent_tools()` methods are REMOVED from the Protocol (P17
tool-spec migration exit criterion). Extensions remain one tool
source managed by `ToolPolicy` alongside HTTP tools.

The Protocol's **required** surface SHALL NOT grow lifecycle methods:
the async lifecycle hooks `initialize()`, `shutdown()`, and
`refresh_credentials()` are OPTIONAL, documented-optional members of
the extension contract (see the "Extension Lifecycle Hooks"
requirement). An extension that defines none of them MUST still
satisfy `isinstance(ext, Extension)` and MUST load unchanged — this
protects private-persona extensions that satisfy the Protocol
structurally.

#### Scenario: Extensions accessible via ToolPolicy

- **WHEN** `ToolPolicy.authorized_extensions(persona, role)` is called
- **THEN** the returned list MUST contain all loaded extensions for the
  persona
- **AND** each extension MUST satisfy `isinstance(ext, Extension)`

#### Scenario: Hook-less extension still satisfies the Protocol

- **WHEN** an extension class defines only `name`, `tool_specs()`,
  and `health_check()` (no lifecycle hooks)
- **THEN** `isinstance(instance, Extension)` MUST be `True`
- **AND** `PersonaRegistry.load_extensions()` MUST return the instance

#### Scenario: Legacy dual-surface class no longer satisfies the Protocol

- **WHEN** a class defines `as_langchain_tools()` and
  `as_ms_agent_tools()` but no `tool_specs()`
- **THEN** `isinstance(instance, Extension)` MUST be `False`

### Requirement: Stub Implementations for All Configured Extensions

The system SHALL ship stub implementations for `gmail`, `gcal`, and
`gdrive` in `src/assistant/extensions/`, each exposing a
`create_extension(config: dict)` factory returning an
`Extension`-compatible instance whose `tool_specs()` returns an empty
list. The extensions `ms_graph`, `teams`, `sharepoint`, and `outlook`
SHALL no longer ship as stubs — those four are real implementations
delivered by the `ms-extensions` capability and import their
domain-specific tooling rather than `StubExtension`.

#### Scenario: Each remaining stub exports create_extension

- **WHEN** the module `assistant.extensions.<name>` is imported for
  each of `gmail`, `gcal`, and `gdrive`
- **THEN** each module MUST define a callable `create_extension`

#### Scenario: Remaining stubs return empty tool lists

- **WHEN** `create_extension({}).tool_specs()` is called on
  any of the three remaining stubs (`gmail`, `gcal`, `gdrive`)
- **THEN** it MUST return `[]`

#### Scenario: ms_graph/teams/sharepoint/outlook no longer return empty tool lists

- **WHEN** `create_extension({}, client=mock_client).tool_specs()`
  is called on any of the four real extensions
- **THEN** the returned list MUST be non-empty

### Requirement: Extension Tool Invocations Emit Observability Span

The system SHALL ensure that every `ToolSpec` returned by any
`Extension.tool_specs()` emits a `trace_tool_call` observability span
on each handler invocation. The wrapping SHALL be performed at the
single aggregation site that composes extension tool bundles — the
`DefaultToolPolicy.authorized_tools` loop (see the
`capability-resolver` capability) — via the shared
`wrap_extension_tool_specs` helper. Because the per-harness adapters
are pure renderings that invoke `spec.handler`, one wrap at the
ToolSpec layer survives every rendering (LangChain, MSAF, and direct
MCP handler dispatch). Individual extension implementations SHALL NOT
add tracing code themselves.

The emitted call MUST include `tool_name` (the ToolSpec's `name`),
`tool_kind="extension"`, `persona`, `role`, and `duration_ms`. When
the handler raises, the span MUST be emitted with `error=<exception
type name>` before the exception propagates.

Wrapping SHALL preserve each spec's original `name`, `description`,
`input_schema`, and `source` so that agents and tool-discovery
consumers see no change in the tool's public contract.

#### Scenario: Extension tool invocation emits trace_tool_call

- **WHEN** an extension returns a `ToolSpec` named `gmail.search` and
  its (wrapped) handler is awaited with `query="foo"` under persona
  `personal` and role `assistant`
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include
  `tool_name="gmail.search"`, `tool_kind="extension"`,
  `persona="personal"`, and `role="assistant"`

#### Scenario: Tool exception emits trace before propagating

- **WHEN** a wrapped handler raises `ValueError("invalid query")`
- **THEN** `trace_tool_call` MUST be called with `error="ValueError"`
- **AND** the exception MUST propagate to the caller

#### Scenario: Tool metadata passthrough is preserved

- **WHEN** an extension returns a `ToolSpec` with `name="x"`,
  `description="y"`, and a specific `input_schema`
- **THEN** the wrapped spec exposed by the aggregation site MUST have
  the identical `name`, `description`, and `input_schema`
