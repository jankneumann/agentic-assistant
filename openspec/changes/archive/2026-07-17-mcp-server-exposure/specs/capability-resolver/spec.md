# capability-resolver Specification (delta)

## MODIFIED Requirements

### Requirement: Aggregated Extension Tools Are Traced

The system SHALL wrap every extension-derived `ToolSpec` with
`trace_tool_call` instrumentation at the single tool aggregation
site — the tool policy's aggregation loop in
`src/assistant/core/capabilities/tools.py`. The tool policy is the
sole tool aggregator (per the harness-adapter `create_agent`
contract); no harness may wrap, re-wrap, or re-derive extension
tools — the per-harness adapters (`assistant.harnesses.tool_adapters`)
are pure renderings of the already-wrapped ToolSpec list.

The aggregation site SHALL invoke the shared helper
`src/assistant/telemetry/tool_wrap.wrap_extension_tool_specs(ext)`
rather than wrapping inline, so a single implementation owns the
wrapping policy (handler substitution via `ToolSpec.with_handler`,
metadata passthrough, error handling). Because the wrap happens at the
ToolSpec layer, the same span fires whether the tool is invoked
through the LangChain rendering, the MSAF rendering, or a direct
handler dispatch (e.g. the MCP surface).

#### Scenario: Tool-policy aggregation wraps each spec

- **WHEN** `authorized_tools` is called and the persona has two
  extensions each returning one ToolSpec
- **THEN** the returned list MUST contain two specs
- **AND** awaiting either spec's handler MUST trigger
  `get_observability_provider().trace_tool_call(tool_kind="extension", ...)`
  exactly once per invocation

#### Scenario: Harnesses receive pre-wrapped specs and do not re-wrap

- **WHEN** `DeepAgentsHarness.create_agent(tools, extensions)` is
  called with a ToolSpec list produced by the tool policy
- **THEN** the constructed agent's tool set MUST be the per-harness
  rendering of exactly those specs
- **AND** invoking one of them MUST call
  `trace_tool_call(tool_kind="extension", ...)` exactly once (no
  double wrapping)

#### Scenario: Helper is the single source of truth

- **WHEN** the tool-policy aggregation site is inspected
- **THEN** it MUST import and call `wrap_extension_tool_specs` from
  `src.assistant.telemetry.tool_wrap`
- **AND** no other module MUST construct its own extension-tool
  wrapping closure
