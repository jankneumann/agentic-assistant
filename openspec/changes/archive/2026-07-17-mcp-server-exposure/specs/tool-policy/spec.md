# tool-policy Specification (delta)

## MODIFIED Requirements

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
