# extension-registry — spec delta

## MODIFIED Requirements

### Requirement: Extension Protocol

The `Extension` Protocol SHALL retain its existing `as_langchain_tools()`
and `as_ms_agent_tools()` methods. Extensions become one tool source
managed by `ToolPolicy` alongside HTTP tools and MCP servers.

#### Scenario: Extensions accessible via ToolPolicy

- **WHEN** `ToolPolicy.authorized_extensions(persona, role)` is called
- **THEN** the returned list MUST contain all loaded extensions for the
  persona
- **AND** each extension MUST satisfy `isinstance(ext, Extension)`
