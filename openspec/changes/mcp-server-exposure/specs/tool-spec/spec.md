# tool-spec Specification (delta)

## RENAMED Requirements

- FROM: `### Requirement: Extension Per-Harness Tool Methods Deprecated`
- TO: `### Requirement: Legacy Extension Tool Methods Removed`

## MODIFIED Requirements

### Requirement: Legacy Extension Tool Methods Removed

The system SHALL NOT define or consume the legacy
`Extension.as_langchain_tools()` and `Extension.as_ms_agent_tools()`
methods anywhere: the `Extension` protocol's sole tool surface is
`tool_specs() → list[ToolSpec]`, rendered through the per-harness
adapters. The migration window that permitted thin legacy shims is
CLOSED (P17 exit criterion satisfied — owner review verdict
2026-07-16): no shim is retained on `ExtensionBase` or any in-tree
extension, and no call site consumes a legacy method. Out-of-tree
structural extensions MUST migrate to `tool_specs()`; loading an
extension that lacks it fails the `Extension` protocol check.

#### Scenario: All consumers use ToolSpec adapters

- **WHEN** a harness or tool policy needs an extension's tools
- **THEN** it MUST obtain them via `tool_specs()` and a per-harness
  adapter
- **AND** it MUST NOT call `as_langchain_tools()` or
  `as_ms_agent_tools()`

#### Scenario: Legacy methods absent from the codebase

- **WHEN** `src/` is searched for `as_langchain_tools` or
  `as_ms_agent_tools`
- **THEN** no protocol member, method definition, or call site MUST
  match (historical prose references in docs and comments excepted)

#### Scenario: Protocol requires tool_specs

- **WHEN** a class defines only `name`, `tool_specs()`, and
  `health_check()`
- **THEN** `isinstance(instance, Extension)` MUST be `True`
