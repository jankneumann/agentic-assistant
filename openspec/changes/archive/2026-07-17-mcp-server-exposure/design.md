# mcp-server-exposure — Design

## D1 — Official `mcp` SDK, low-level Server (not FastMCP, not hand-rolled)

Decision: use the official `mcp` Python SDK (1.27+), specifically the
**low-level** `mcp.server.lowlevel.Server` +
`StreamableHTTPSessionManager`, mounted into the existing FastAPI app.

- The pre-made instruction was "try the official SDK first; fall back
  to hand-rolled JSON-RPC (A2A `types.py` precedent) if it fights the
  mount pattern or drags conflicting deps". It does neither:
  `uv add mcp` resolves cleanly against the pinned `fastapi>=0.115,
  <0.116` (adds only `httpx-sse` and `python-multipart`), and the
  session manager exposes a raw ASGI `handle_request` that mounts
  under any path.
- Low-level Server over `FastMCP` because FastMCP derives tool schemas
  from Python function signatures, while our `ToolSpec` already *is*
  the MCP tool shape — the low-level `list_tools` handler accepts
  pre-built `mcp.types.Tool` entries, so `render_mcp_tools(specs)` is
  a field-for-field copy and the spec's "no translation layer" claim
  holds literally. FastMCP would have forced a reverse mapping
  (JSON Schema → typed signature) for zero benefit.
- The SDK also gives us protocol lifecycle (initialize/capabilities),
  jsonschema argument validation on `tools/call`, and `isError` result
  mapping for free — all things the hand-rolled fallback would have
  re-implemented.

### D1 addendum — owner review 2026-07-17 (FastMCP question)

Clarifications ratified during review: (a) FastMCP is the high-level
layer of the SAME official `mcp` package — wire protocol and client
compatibility are identical either way; this choice affects only the
in-process API. (b) The FastAPI analogy inverts here: FastMCP/FastAPI
generate schemas from hand-authored function signatures, while our
tools are pre-schematized ToolSpecs assembled dynamically per
persona×role — feeding them through FastMCP would reintroduce the
translation layer the tool-spec contract forbids. (c) Boundary for
future work: when the deferred hand-authored MCP surfaces land
(resources, prompts, elicitation — the P24 ApprovalRequest transport),
use FastMCP-style decorators for those; both layers coexist in one
server. Switching layers is an internal refactor with zero wire
impact.

## D2 — Stateless streamable HTTP, JSON responses; context_id carries continuity

`StreamableHTTPSessionManager(stateless=True, json_response=True)`:

- Every POST is self-contained — no MCP transport session for clients
  to establish/resume, which matches how tool-calling clients (and
  tests) actually use a served assistant.
- Conversation continuity is carried by the explicit `context_id`
  tool argument (returned in every result, ≡ session `thread_id`),
  exactly mirroring A2A's `contextId` semantics on the sibling
  surface. Unknown/expired ids are REJECTED (in-memory registry;
  durable sessions remain deferred to the harness-adapter Durable
  Session Persistence work).
- `json_response=True` returns plain JSON bodies instead of SSE for
  request/response calls — simpler clients, identical semantics for
  the non-streaming `invoke` path served today. Streaming task
  updates over MCP are deferred (the A2A surface already streams).

## D3 — Telemetry wraps at the ToolSpec layer (single seam)

`trace_tool_call` wrapping moves from LangChain `StructuredTool`
construction to the ToolSpec handler (`wrap_tool_spec` returns a copy
via `ToolSpec.with_handler`). Rationale: the per-harness adapters are
pure renderings that all ultimately call `spec.handler`, so one wrap
survives the LangChain rendering, the MSAF rendering, AND direct
handler invocation on the MCP surface — no per-rendering wrap, no
double-wrap risk. The single extension aggregation site stays
`DefaultToolPolicy.authorized_tools` (`wrap_extension_tool_specs`);
HTTP specs are wrapped at build time inside `_build_tool`
(`wrap_http_tool_spec`), preserving the established composition order
(observability span → Pydantic validation → resilient_http → HTTP
call).

## D4 — Legacy methods removed outright; no ExtensionBase shim

The tool-spec spec allowed legacy `as_langchain_tools()` /
`as_ms_agent_tools()` to remain "as thin shims deriving from
tool_specs()" during the migration window, with removal from the
protocol as the P17 exit criterion. Disposition: **removed
everywhere, no shim retained.**

- No in-tree call site consumes them after the migration (grep to
  zero across `src/`).
- A shim on `ExtensionBase` cannot help out-of-tree *structural*
  extensions anyway — they do not subclass `ExtensionBase`. The only
  compat that matters for private-submodule extensions is the
  Protocol surface itself, which now requires `tool_specs()`;
  out-of-tree extensions migrate by renaming their tool method and
  emitting ToolSpecs (`tool_spec_from_model` makes this mechanical).
  No persona currently enables an out-of-tree extension that would
  break (the four MS extensions are in-tree; gmail/gcal/gdrive are
  in-tree stubs).
- The spec's "Legacy shim preserves behavior during migration"
  scenario is satisfied vacuously and the migration window is closed
  by this change's tool-spec delta (deprecation requirement replaced
  by the removal requirement).

## D5 — MCP serves an `ask*` facade, not the raw tool inventory

The server exposes one `ask_<role>` tool per enabled role plus a
generic `ask` (bound to the serving role's registry, so contexts are
interchangeable between `ask` and `ask_<default-role>`). It does NOT
re-export the persona's own tool inventory (gmail, http tools, …) as
MCP tools: callers delegate a task to the assistant-as-agent; the
assistant's own ToolPolicy governs what *it* may call. Re-exporting
inventory would bypass persona guardrails and role filtering. (The
ToolSpec → `mcp.types.Tool` adapter makes an inventory surface
trivial later if a use case appears.)

## D6 — Validation lives in the ToolSpec handler, not the renderings

`tool_spec_from_model` wraps the canonical async callable so incoming
kwargs are validated/coerced by the same runtime Pydantic model the
old surfaces used, and only caller-provided keys are forwarded
(byte-compatible with LangChain `StructuredTool._parse_input`
semantics — callable-signature defaults keep applying). Consequences:
every surface (LangChain, MSAF, MCP, direct handler) gets identical
validation; the LangChain rendering passes the JSON-Schema dict as
`args_schema` (supported since langchain-core 0.3) instead of a
Pydantic class, and MSAF's `FunctionTool` receives the same dict as
`input_model`.

## D7 — Session factory is role-parameterized; per-role registries

The A2A `SessionRegistry` (P6) is reused unchanged (imported from
`assistant.a2a.task_handler` — it is the harness-adapter Session
Registry implementation, not A2A-specific; relocating it to a neutral
module is deliberately deferred to avoid churning the P6 surface in
the same change). MCP needs role-true sessions for `ask_<role>`, so
`build_mcp_state` takes a `RoleSessionFactory` (role → harness+agent
via the same `create_harness` + agent-factory pipeline the web
lifespan runs) and builds one registry per role. Per-session
`asyncio.Lock` serializes turns on a shared context, mirroring the
A2A task handler.

## D8 — Auth deferred to P25

The MCP transport ships with no authentication, consistent with the
AG-UI and A2A surfaces: the CLI binds loopback by default and warns on
non-loopback hosts. OAuth 2.1 / the MCP authorization spec land in
P25 (`security-production-hardening`) for all served surfaces at once.
