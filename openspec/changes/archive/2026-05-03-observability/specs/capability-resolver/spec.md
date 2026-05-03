# capability-resolver Specification Delta

## ADDED Requirements

### Requirement: Aggregated Extension Tools Are Traced

The system SHALL wrap every `StructuredTool` returned by `extension.as_langchain_tools()` with `trace_tool_call` instrumentation at each aggregation site that composes an extension tool bundle. The two known aggregation sites SHALL be:

- `src/assistant/core/capabilities/tools.py` — the capability-resolver's tool aggregation loop (currently at line ~41)
- `src/assistant/harnesses/sdk/deep_agents.py` — the Deep Agents harness tool bundle (currently at line ~27)

Both aggregation sites SHALL invoke the shared helper `src/assistant/telemetry/tool_wrap.wrap_extension_tools(ext)` rather than calling `wrap_structured_tool` inline. This ensures a single implementation owns the wrapping policy (attribute extraction, metadata passthrough, error handling) so it cannot drift between call sites.

The wrapping SHALL happen at these aggregation sites rather than in `src/assistant/extensions/base.py` because `Extension` is a Python `typing.Protocol`, not a base class — a Protocol cannot carry behavior for subclasses to inherit, so the wrapping must happen where extensions are consumed.

#### Scenario: Capability-resolver aggregation wraps each tool

- **WHEN** `get_tools_for_persona(persona)` is called and the persona has two extensions each returning one `StructuredTool`
- **THEN** the returned list MUST contain two tools
- **AND** invoking either tool MUST trigger `get_observability_provider().trace_tool_call(tool_kind="extension", ...)` exactly once per invocation

#### Scenario: Deep Agents harness aggregation wraps each tool

- **WHEN** `DeepAgentsHarness.create_agent(tools, extensions)` is called with one extension returning one `StructuredTool`
- **THEN** the constructed agent's tool set MUST include a wrapped version of that tool
- **AND** invoking the wrapped tool MUST call `trace_tool_call(tool_kind="extension", ...)` exactly once

#### Scenario: Helper is the single source of truth

- **WHEN** both aggregation sites are inspected
- **THEN** both MUST import and call `wrap_extension_tools` from `src.assistant.telemetry.tool_wrap`
- **AND** neither site MUST construct its own wrapping closure or call `wrap_structured_tool` directly
