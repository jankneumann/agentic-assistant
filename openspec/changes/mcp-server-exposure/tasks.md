# mcp-server-exposure — Tasks

## 1. ToolSpec core + adapters + telemetry seam

- [x] 1.1 `core/toolspec.py` — frozen `ToolSpec` dataclass
  (name/description/JSON-Schema input_schema/async handler/source),
  `with_handler` copy helper, `as_mcp_listing`, and
  `tool_spec_from_model` (Pydantic validation inside the handler;
  provided-keys-only forwarding for StructuredTool parity)
- [x] 1.2 `harnesses/tool_adapters.py` — pure renderings:
  `render_langchain_tools` (StructuredTool, dict args_schema),
  `render_msaf_tools` (`agent_framework.FunctionTool` with JSON-Schema
  `input_model`), `render_mcp_tools` (`mcp.types.Tool`); N-in/N-out,
  order-preserving, non-ToolSpec passthrough
- [x] 1.3 `telemetry/tool_wrap.py` rewritten at the ToolSpec layer:
  `wrap_tool_spec` / `wrap_extension_tool_specs` /
  `wrap_http_tool_spec` (D3)

## 2. Tool-source migration (exit criterion)

- [x] 2.1 `extensions/base.py` — Protocol = `name` + `tool_specs()` +
  `health_check()`; legacy methods removed; docs updated (D4 — no
  shim retained)
- [x] 2.2 `extensions/_stub.py` — `tool_specs() -> []`
- [x] 2.3 Four MS extensions (`ms_graph`, `outlook`, `teams`,
  `sharepoint`) — `tool_specs()` via `tool_spec_from_model` (same
  canonical names/descriptions); per-extension MSAF `ai_function`
  wrapper machinery deleted
- [x] 2.4 `http_tools/builder.py` — `_build_tool` emits ToolSpec
  (validation in handler; resilient_http + wrap_http_tool_spec
  composition preserved); `http_tools/registry.py` typed to ToolSpec
- [x] 2.5 `core/capabilities/tools.py` — `DefaultToolPolicy`
  aggregates/authorizes ToolSpecs; single traced aggregation site
- [x] 2.6 `harnesses/sdk/deep_agents.py` — consume `tools` as-is,
  render via `render_langchain_tools`; former second aggregation site
  removed
- [x] 2.7 `harnesses/sdk/ms_agent_fw.py` — consume `tools` as-is,
  render via `render_msaf_tools`; `as_ms_agent_tools()` consumption
  and in-create_agent extension filtering removed
- [x] 2.8 `cli.py` — `--list-tools` reads `ToolSpec.input_schema`
- [x] 2.9 Exit-criterion verification: grep for
  `as_langchain_tools|as_ms_agent_tools` over `src/` hits only
  historical doc/comment references — zero call sites, zero
  definitions

## 3. MCP server surface

- [x] 3.1 `mcp/server.py` — `build_mcp_state` (per-role
  SessionRegistry over a role-parameterized session factory, D7),
  `build_ask_tool_specs` (one `ask_<role>` per enabled role + generic
  `ask`; sanitize names to the MCP charset), low-level SDK `Server`
  wiring (`tools/list` = `render_mcp_tools`; `tools/call` dispatch
  with unknown-tool/unknown-context error mapping),
  `StreamableHTTPSessionManager(stateless=True, json_response=True)`
  (D1/D2)
- [x] 3.2 `web/app.py` — `make_app(enable_mcp=)`: lifespan builds
  the MCP state with the same harness/agent pipeline, holds
  `session_manager.run()` open via `AsyncExitStack`, mounts the ASGI
  forwarder at `/mcp`
- [x] 3.3 `cli.py` — `assistant serve --mcp` (composes with `--a2a`;
  legacy call shape when absent; startup echo of the /mcp endpoint;
  auth deferred to P25, D8)
- [x] 3.4 `pyproject.toml` — add `mcp>=1.27`

## 4. Tests

- [x] 4.1 `tests/core/test_toolspec.py` — ToolSpec fields, MCP-listing
  triple serializability, async handler, `tool_spec_from_model`
  validation/coercion/default-forwarding
- [x] 4.2 `tests/harnesses/test_tool_adapters.py` — LangChain + MSAF +
  MCP renderings (fields, handler invocation, N-in/N-out order,
  passthrough)
- [x] 4.3 `tests/telemetry/` — wrap at ToolSpec layer (success/error
  spans, metadata passthrough, single aggregation site, trace
  survives LangChain rendering, no deep_agents re-wrap)
- [x] 4.4 http_tools suites migrated (builder/registry/resilience/
  discovery-simulation) — ToolSpec compile, input_schema surface,
  handler-level validation
- [x] 4.5 Extension suites migrated (`tool_specs()` on all four MS
  extensions + stubs); cross-adapter render-equivalence test pins the
  canonical (pre-migration) tool-name lists
- [x] 4.6 Harness suites — DeepAgents/MSAF consume the aggregated
  list as-is (extension fakes raise if a harness derives tools) and
  render ToolSpecs via their adapter
- [x] 4.7 `tests/mcp/test_server.py` — ask-tool construction, session
  multiplexing (fresh/reuse/reject-unknown), role-bound sessions,
  ask ↔ ask_<default> context sharing
- [x] 4.8 `tests/web/test_mcp_mount.py` — streamable-HTTP tools/list +
  tools/call happy path, error mapping (unknown tool / unknown
  context / schema violation), multiplexing across requests, AG-UI
  co-hosting, 404 when disabled
- [x] 4.9 `tests/cli/test_serve_mcp.py` — flag wiring (incl. --a2a
  composition and legacy call shape)

## 5. Docs

- [x] 5.1 CLAUDE.md — MCP section + extension protocol / tool-surface
  description updates
- [x] 5.2 OpenSpec deltas for all touched capabilities;
  `openspec validate mcp-server-exposure --strict` passes
