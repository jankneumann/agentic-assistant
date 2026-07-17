# observability Specification (delta)

## MODIFIED Requirements

### Requirement: Tool Call Tracing Across Extensions and HTTP Tools

Every `ToolSpec` returned by an `Extension.tool_specs()` call and every HTTP `ToolSpec` constructed by `src/assistant/http_tools/builder.py` SHALL be wrapped at the ToolSpec layer (`wrap_tool_spec` — handler substitution via `ToolSpec.with_handler`) such that `provider.trace_tool_call(...)` is invoked on each handler invocation, regardless of which per-harness rendering (LangChain, MSAF, or direct MCP dispatch) triggered it. The `tool_kind` argument MUST be `"extension"` for extension tools and `"http"` for HTTP-discovered tools. When the handler raises, the trace call MUST record `error=<exception type name>` before re-raising.

#### Scenario: Extension tool invocation is traced

- **WHEN** an extension ToolSpec `gmail.search` has its handler awaited with persona `personal`
- **THEN** `provider.trace_tool_call` MUST be called once
- **AND** the call's `tool_name` MUST equal `"gmail.search"` and `tool_kind` MUST equal `"extension"`

#### Scenario: HTTP tool invocation is traced

- **WHEN** an HTTP-discovered ToolSpec `linear:listIssues` has its handler awaited
- **THEN** `provider.trace_tool_call` MUST be called once with `tool_kind="http"`

#### Scenario: Trace survives per-harness rendering

- **WHEN** a wrapped extension ToolSpec is rendered through the LangChain adapter and the rendered tool is invoked
- **THEN** `provider.trace_tool_call` MUST be called exactly once (no double wrapping, no lost span)

#### Scenario: Tool error is recorded before propagating

- **WHEN** a tool invocation raises `httpx.HTTPStatusError`
- **THEN** `provider.trace_tool_call` MUST be called with `error="HTTPStatusError"`
- **AND** the exception MUST propagate to the caller
