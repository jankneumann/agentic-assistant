# mcp-server-exposure — MCP Server + ToolSpec Migration (P17)

## Why

Other sessions and harnesses (Claude Code, MCP-speaking orchestrators,
sibling assistants) need a standards-based way to invoke this
assistant as a *tool* (roadmap row P17; protocol-standards analysis
2026-07-16 — MCP is the adopted agent-facing tool protocol,
complementary to P6 A2A: different protocol, different clients;
together they form the composition surface consumed by P22). Today the
only agent↔agent surface is A2A; there is no MCP transport.

The archived `capability-protocols-v2` change also left a BINDING exit
criterion on this phase (owner review verdict 2026-07-16, recorded in
`openspec/specs/tool-spec/spec.md`): the `ToolSpec` contract must be
implemented and **both SDK harnesses must stop consuming the legacy
`Extension.as_langchain_tools()` / `as_ms_agent_tools()` methods
before P17 archives**. The two deliverables are coupled by design:
`ToolSpec` is MCP-shaped, so serving it over MCP is a transport
concern with no translation layer.

## What Changes

- **ToolSpec migration (exit criterion)**:
  - New `src/assistant/core/toolspec.py` — frozen `ToolSpec` dataclass
    (`name`, `description`, JSON-Schema `input_schema`, async
    `handler`, `source` provenance) + `tool_spec_from_model` (compiles
    a Pydantic-args async callable into a spec whose handler validates
    exactly like LangChain's `StructuredTool` used to).
  - New `src/assistant/harnesses/tool_adapters.py` — pure per-harness
    renderings: LangChain `StructuredTool`, MSAF
    `agent_framework.FunctionTool` (accepts a JSON-Schema mapping as
    `input_model` natively), and `mcp.types.Tool` for the served
    surface. N specs in → N tools out, same order; non-ToolSpec items
    pass through unchanged (migration passthrough for injected native
    tools).
  - `Extension` protocol becomes `name` + `tool_specs()` +
    `health_check()`; the legacy dual-surface methods are **removed**
    from the protocol, the four real MS extensions, and the shared
    stub — grep-to-zero, no shim retained (design.md D4).
  - `http_tools/builder.py` emits `ToolSpec` (validation inside the
    handler; `resilient_http` + telemetry composition preserved);
    `HttpToolRegistry` holds ToolSpecs.
  - `DefaultToolPolicy.authorized_tools` aggregates/authorizes
    ToolSpecs and remains the SINGLE telemetry-wrapping aggregation
    site (`wrap_extension_tool_specs`); telemetry wrapping moves to
    the ToolSpec layer (`wrap_tool_spec`) so traces survive every
    rendering — including direct MCP handler invocation (design.md
    D3).
  - Both SDK harnesses consume the aggregated ToolSpec list as-is and
    render via their adapter; neither derives tools from the
    `extensions` argument anymore (brings the code into compliance
    with the harness-adapter "sole aggregator" contract).
- **MCP server exposure**:
  - New `src/assistant/mcp/` package: official `mcp` Python SDK,
    low-level `Server` + `StreamableHTTPSessionManager`
    (stateless, JSON responses — design.md D1/D2). `tools/list` is a
    pure `render_mcp_tools` rendering; `tools/call` dispatches to the
    matching spec's handler with SDK-side jsonschema argument
    validation and `isError` mapping.
  - Served tools: one `ask_<role>` per enabled role plus a generic
    `ask` bound to the serving role. Each call multiplexes over
    per-role `SessionRegistry` instances (reusing the P6 registry) —
    fresh session when no `context_id` is given, reuse on a known one,
    reject unknown ones. `context_id` ≡ session `thread_id`
    (mirroring A2A `contextId`).
  - `make_app(..., enable_mcp=True)` mounts the transport at `/mcp`
    (register-then-populate: state built in the lifespan, ASGI mount
    forwards to it; `session_manager.run()` held open for the app's
    lifetime).
  - CLI: `assistant serve --mcp` (composes with `--a2a`;
    loopback-only default preserved; **auth deferred to P25**).
  - New dependency: `mcp>=1.27` (resolves cleanly against the pinned
    fastapi 0.115 line; brings only `httpx-sse` + `python-multipart`).

## Impact

- Affected specs: **ADDED** `mcp-server`; **MODIFIED** `tool-spec`
  (deprecation requirement → removal complete), `extension-registry`
  (protocol + stubs + observability wrap seam), `tool-policy`
  (ToolSpec aggregation), `http-tools` (builder emits ToolSpec;
  observability/resilience composition wording), `capability-resolver`
  (traced aggregation at the ToolSpec layer), `ms-extensions`
  (`tool_specs()` surfaces; dual-format parity requirement removed),
  `ms-agent-framework-harness` (adapter rendering; no extension-tool
  derivation), `observability` (ToolSpec-layer tool tracing),
  `cli-interface` (serve `--mcp`).
- Affected code: `src/assistant/core/toolspec.py`,
  `src/assistant/harnesses/tool_adapters.py`,
  `src/assistant/telemetry/tool_wrap.py`,
  `src/assistant/extensions/*`, `src/assistant/http_tools/*`,
  `src/assistant/core/capabilities/tools.py`,
  `src/assistant/harnesses/sdk/{deep_agents,ms_agent_fw}.py`,
  `src/assistant/mcp/`, `src/assistant/web/app.py`,
  `src/assistant/cli.py`; test suites updated to the ToolSpec
  surfaces.
- NOT in scope: MCP resources/prompts/elicitation (later phases per
  the protocol-standards analysis), transport auth (P25), durable
  sessions (harness-adapter Durable Session Persistence), exposing
  the persona's raw tool inventory over MCP (only the `ask*` facade
  is served — design.md D5).
