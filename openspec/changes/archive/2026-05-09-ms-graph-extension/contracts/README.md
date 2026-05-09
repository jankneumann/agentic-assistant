# Contracts — ms-graph-extension

This change introduces no machine-readable cross-language interface
contracts. Each contract sub-type was evaluated and ruled out below.

## Sub-types evaluated

### OpenAPI

**Not applicable.** The change does not introduce or modify any
HTTP endpoints exposed by this project. The Microsoft Graph API
endpoints consumed by the new extensions are owned by Microsoft, not
by this project, and are not part of our outbound contract surface.

### Database schema

**Not applicable.** No new tables, columns, indexes, or constraints
are introduced. The MSAL token cache is a per-persona JSON file
on the filesystem, not a database resource.

### Events

**Not applicable.** No events are emitted, consumed, or modified by
this change. Existing observability spans (`trace_llm_call`,
`trace_tool_call`) are reused via decorators specified in the
`harness-adapter` and `extension-registry` capabilities; their wire
format is unchanged.

### Type generation stubs

**Not applicable.** Type-generation stubs are typically derived from
OpenAPI or DB schemas. With neither present, there is nothing to
generate. The Python type Protocols introduced by this change
(`CloudGraphClient`, `MSALStrategy`) are authoritative in
`spec.md` and implemented directly in `src/assistant/core/`.

## Where the binding interfaces live

The change introduces three Python `Protocol` shapes that bind
multiple work packages together. Each is specified in a spec file
under this change and implemented under `src/assistant/core/` at the
referenced module path:

| Protocol | Spec file | Source module (lands at impl time) |
|----------|-----------|------------------------------------|
| `CloudGraphClient` | `specs/graph-client/spec.md` | `src/assistant/core/cloud_client.py` |
| `MSALStrategy` | `specs/msal-auth/spec.md` | `src/assistant/core/msal_auth.py` |
| `MSAgentFrameworkHarness` (concrete subclass of existing `SdkHarnessAdapter`) | `specs/ms-agent-framework-harness/spec.md` | `src/assistant/harnesses/sdk/ms_agent_fw.py` |

## Test fixtures

Per project convention (memory entry
`feedback_test_fixture_placement`), test fixtures live under
`tests/fixtures/`, never under `openspec/changes/<id>/contracts/`.
Graph response fixtures land at `tests/fixtures/graph_responses/`.
The fixture sentinel `// FIXTURE_GRAPH_RESPONSE_v1` MUST appear at
the top of each file to satisfy the privacy guard pattern (CLAUDE.md
G6).
