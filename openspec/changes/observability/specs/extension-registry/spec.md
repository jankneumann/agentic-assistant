# extension-registry Specification Delta

## ADDED Requirements

### Requirement: Extension Tool Invocations Emit Observability Span

The system SHALL wrap every LangChain `StructuredTool` returned by `Extension.as_langchain_tools()` such that each tool invocation emits a `trace_tool_call` observability span. The wrapping SHALL happen in `src/assistant/extensions/base.py` so every extension (current stubs and future real implementations) inherits the behavior without needing to add tracing code.

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
