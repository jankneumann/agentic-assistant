# tool-policy Specification Delta

## MODIFIED Requirements

### Requirement: DefaultToolPolicy Implementation

The `DefaultToolPolicy` SHALL accept an optional
`http_tool_registry: HttpToolRegistry | None = None` constructor
parameter. The `authorized_tools(persona, role, *, loaded_extensions)`
method SHALL return a list containing (a) all tools from the provided
`loaded_extensions` plus (b) all tools from the `http_tool_registry`
(when not `None`), filtered by `role.preferred_tools` when that list
is non-empty.

When `role.preferred_tools` is empty, both extension tools and HTTP
tools MUST be returned unfiltered. When `role.preferred_tools` is
non-empty, the returned list MUST contain only tools whose name (for
extension tools) or registry key `"{source_name}:{operation_id}"` (for
HTTP tools) appears in `preferred_tools`.

Extension tools and HTTP tools with the same name SHALL both appear in
the returned list (no deduplication); callers relying on uniqueness
SHALL namespace via the `"{source}:{op}"` key for HTTP tools.

#### Scenario: Merges extension and http tools

- **WHEN** `role.preferred_tools` is `[]`
- **AND** `loaded_extensions` provide `[ext_tool_a]`
- **AND** `http_tool_registry` contains `{"backend:list_items": http_tool_b}`
- **THEN** `authorized_tools()` MUST return a list containing both
  `ext_tool_a` and `http_tool_b`

#### Scenario: preferred_tools filters across both sources

- **WHEN** `role.preferred_tools` is `["backend:list_items"]`
- **AND** `loaded_extensions` provide a tool named `ext_tool_a`
- **AND** `http_tool_registry` contains `"backend:list_items"` and
  `"backend:create_item"`
- **THEN** `authorized_tools()` MUST return a list containing only the
  `backend:list_items` HTTP tool
- **AND** `ext_tool_a`, `backend:create_item` MUST NOT appear

#### Scenario: No registry means extension-only behavior

- **WHEN** `DefaultToolPolicy` is constructed with
  `http_tool_registry=None`
- **AND** `loaded_extensions` provide `[tool_a, tool_b]`
- **THEN** `authorized_tools()` MUST return `[tool_a, tool_b]` (prior
  behavior preserved)

### Requirement: Tool Manifest Export

The `export_tool_manifest(persona, role)` method SHALL return a
dictionary describing available tools in a format suitable for
host-harness integration (MCP server configs, skill registrations).
When an `http_tool_registry` was supplied, the manifest SHALL include
a new key `"http_tools"` mapping to a list of registered HTTP tool
keys `"{source}:{op_id}"` alongside the existing `"extensions"` and
`"tool_sources"` keys.

#### Scenario: Manifest includes http_tools when registry present

- **WHEN** `DefaultToolPolicy` was constructed with a registry
  containing `{"backend:list_items": tool, "backend:create_item": tool}`
- **AND** `export_tool_manifest(persona, role)` is called
- **THEN** the returned dict MUST contain a key `"http_tools"` whose
  value is a list containing both `"backend:list_items"` and
  `"backend:create_item"`

#### Scenario: Manifest omits http_tools when registry is None

- **WHEN** `DefaultToolPolicy` was constructed without an
  `http_tool_registry`
- **THEN** the returned manifest dict MUST either omit the
  `"http_tools"` key or set it to an empty list
