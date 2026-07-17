# tool-policy Specification

## Purpose
Governs the `ToolPolicy` runtime-checkable protocol, the
`DefaultToolPolicy` implementation, and tool manifest export. It exists so
that which tools a given persona/role composition actually exposes is a
policy decision made in one place, rather than every discovered or
registered tool being unconditionally available. Consumers are the
capability resolver, the harness adapters that filter their aggregated tool
set through the policy, and the `assistant export` command that emits
manifests for host harnesses.
## Requirements
### Requirement: ToolPolicy Protocol

The system SHALL define a `ToolPolicy` runtime-checkable Protocol with
the methods `authorized_tools(persona, role, *, loaded_extensions)
→ list[Any]`, `authorized_extensions(persona, role, *,
loaded_extensions) → list[Any]`, and `export_tool_manifest(persona,
role) → dict[str, Any]`. The `loaded_extensions` keyword argument
receives pre-loaded extensions from the caller (CLI or harness),
keeping ToolPolicy decoupled from PersonaRegistry.

#### Scenario: Stub implementation satisfies Protocol

- **WHEN** a class implements `authorized_tools`,
  `authorized_extensions`, and `export_tool_manifest` with the correct
  signatures
- **THEN** `isinstance(instance, ToolPolicy)` MUST return `True`

### Requirement: DefaultToolPolicy Implementation

The `DefaultToolPolicy` SHALL accept an optional
`http_tool_registry: HttpToolRegistry | None = None` constructor
parameter. The `authorized_tools(persona, role, *, loaded_extensions)`
method SHALL return a list of harness-neutral `ToolSpec` instances
(see the `tool-spec` capability) containing (a) every spec from each
loaded extension's `tool_specs()` — telemetry-wrapped here, at the
single aggregation site, via `wrap_extension_tool_specs` — plus (b)
all specs from the `http_tool_registry` (when not `None`; those are
wrapped at build time), filtered by `role.preferred_tools` when that
list is non-empty. The tool policy is the SOLE tool aggregator:
harnesses receive this list through `create_agent(tools=...)` and
render it with their per-harness adapter.

When `role.preferred_tools` is empty, both extension specs and HTTP
specs MUST be returned unfiltered. When `role.preferred_tools` is
non-empty, the returned list MUST contain only specs whose `name`
(the `"{source_name}:{operation_id}"` registry key for HTTP tools)
appears in `preferred_tools`.

Extension specs and HTTP specs with the same name SHALL both appear in
the returned list (no deduplication); callers relying on uniqueness
SHALL namespace via the `"{source}:{op}"` key for HTTP tools.

#### Scenario: Merges extension and http tool specs

- **WHEN** `role.preferred_tools` is `[]`
- **AND** `loaded_extensions` provide `[ext_spec_a]`
- **AND** `http_tool_registry` contains `{"backend:list_items": http_spec_b}`
- **THEN** `authorized_tools()` MUST return a list containing both
  `ext_spec_a` (wrapped) and `http_spec_b`

#### Scenario: preferred_tools filters across both sources

- **WHEN** `role.preferred_tools` is `["backend:list_items"]`
- **AND** `loaded_extensions` provide a spec named `ext_tool_a`
- **AND** `http_tool_registry` contains `"backend:list_items"` and
  `"backend:create_item"`
- **THEN** `authorized_tools()` MUST return a list containing only the
  `backend:list_items` spec
- **AND** `ext_tool_a`, `backend:create_item` MUST NOT appear

#### Scenario: No registry means extension-only behavior

- **WHEN** `DefaultToolPolicy` is constructed with
  `http_tool_registry=None`
- **AND** `loaded_extensions` provide `[spec_a, spec_b]`
- **THEN** `authorized_tools()` MUST return `[spec_a, spec_b]` (prior
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

