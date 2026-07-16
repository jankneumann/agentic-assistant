# tool-spec Specification (delta)

## ADDED Requirements

### Requirement: ToolSpec Type

The system SHALL define a `ToolSpec` dataclass as the single internal,
harness-neutral tool representation, shaped after the MCP tool schema:
`name: str`, `description: str`, `input_schema: dict[str, Any]` (a
JSON Schema object describing the tool's parameters), and
`handler: Callable[..., Awaitable[Any]]` (an async callable executing
the tool), plus `source: str` provenance metadata (e.g.,
`"extension:gmail"`, `"http:backend"`). Because the shape mirrors the
MCP tool schema, serving a `ToolSpec` over MCP (P17) is a transport
concern requiring no translation layer.

#### Scenario: ToolSpec captures an MCP-shaped tool

- **WHEN** a `ToolSpec` is created with `name="search"`, a
  description, a JSON-Schema `input_schema`, and an async handler
- **THEN** all fields MUST be accessible as typed attributes
- **AND** the (`name`, `description`, `input_schema`) triple MUST be
  directly serializable as an MCP tool listing entry

#### Scenario: Handler is async

- **WHEN** `ToolSpec.handler` is invoked with arguments valid against
  `input_schema`
- **THEN** it MUST return an awaitable

### Requirement: All Tool Sources Compile to ToolSpec

The system SHALL compile every tool source into `ToolSpec` as its
output type — one compiler seam, not per-harness wrapping logic:
OpenAPI-derived HTTP tools (the `http_tools` discovery pipeline)
SHALL emit `ToolSpec` instances preserving their
`"{source}:{operation_id}"` naming, and extensions SHALL expose their
tools as `ToolSpec` instances via a `tool_specs() → list[ToolSpec]`
method on the `Extension` protocol. Downstream aggregation
(`ToolPolicy`), telemetry wrapping, and manifest export operate on
`ToolSpec` only.

#### Scenario: OpenAPI-derived tool compiles to ToolSpec

- **WHEN** the HTTP tool discovery pipeline processes an operation
  `list_items` from source `backend`
- **THEN** the resulting tool MUST be a `ToolSpec` named
  `"backend:list_items"`
- **AND** its `input_schema` MUST be the JSON Schema derived from the
  operation's parameters and request body

#### Scenario: Extension exposes ToolSpecs

- **WHEN** an extension implementing the `Extension` protocol is
  loaded
- **AND** `tool_specs()` is called
- **THEN** it MUST return a list of `ToolSpec` instances, each with
  `source` identifying the extension

### Requirement: Per-Harness ToolSpec Adapters

The system SHALL render `ToolSpec` to each harness's native tool shape
through per-harness adapters owned by the harness layer — a LangChain
adapter producing `StructuredTool` instances for LangChain-native
harnesses (DeepAgents), an MSAF adapter producing `agent-framework`
tool shapes, and an MCP rendering for served surfaces (P17). Adapters
are pure renderings: they MUST NOT filter, re-order, re-aggregate, or
re-wrap the tool set (aggregation and telemetry wrapping happen once,
upstream, in `ToolPolicy`).

#### Scenario: LangChain adapter renders a ToolSpec

- **WHEN** the LangChain adapter is given a `ToolSpec`
- **THEN** it MUST return a `StructuredTool` whose name, description,
  and argument schema match the `ToolSpec` fields
- **AND** invoking the rendered tool MUST call the `ToolSpec.handler`

#### Scenario: Adapters do not change the tool set

- **WHEN** any per-harness adapter is given a list of N `ToolSpec`
  instances
- **THEN** it MUST return exactly N rendered tools in the same order

### Requirement: Extension Per-Harness Tool Methods Deprecated

The system SHALL deprecate `Extension.as_langchain_tools()` and
`Extension.as_ms_agent_tools()` in favor of `tool_specs()` rendered
through the per-harness adapters. During migration the two legacy
methods MAY remain on extensions as thin shims deriving from
`tool_specs()`, but no new call site may consume them: harnesses and
tool policies MUST consume `ToolSpec` via the adapters. The legacy
methods are removed from the `Extension` protocol once the phases
implementing this contract have migrated both SDK harnesses.

#### Scenario: New consumers use ToolSpec adapters

- **WHEN** a harness or tool policy implemented against this contract
  needs an extension's tools
- **THEN** it MUST obtain them via `tool_specs()` and a per-harness
  adapter
- **AND** it MUST NOT call `as_langchain_tools()` or
  `as_ms_agent_tools()`

#### Scenario: Legacy shim preserves behavior during migration

- **WHEN** an extension still exposes `as_langchain_tools()` during
  the migration window
- **THEN** its output MUST be equivalent to rendering `tool_specs()`
  through the LangChain adapter (same names, schemas, and handlers)
