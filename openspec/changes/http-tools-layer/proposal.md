# Proposal: http-tools-layer

## Why

P1 ships the skeleton of persona-scoped HTTP tool sources: every persona
config carries a `tool_sources` map and the `DefaultToolPolicy` from
P1.8 is ready to filter authorized tools per role. **But no discovery
layer exists.**

P3 also evolves the `tool_sources.auth_header` shape from the legacy
flat `auth_header_env: VAR_NAME` (bearer-only) to a structured
`{type, env, header?}` dict that supports both bearer and api-key auth,
with custom header names. The legacy flat form is auto-normalized for
backwards compatibility (see design decision D11). The per-source
`allowed_tools` field remains unchanged — it continues to flow through
`DefaultToolPolicy.preferred_tools` filtering at the role level; no
new per-source authorization behavior lands in P3.

`src/assistant/cli.py:181-195` is explicit about the gap:

```python
if any(src.get("base_url") for src in pc.tool_sources.values()):
    click.echo("  Tools:  HTTP tool discovery is deferred to P2; "
               "passing empty tool list.")
extensions = persona_reg.load_extensions(pc)
agent = await adapter.create_agent(tools=[], extensions=extensions)
```

Until P3 lands, every persona that declares `tool_sources` silently
degrades to extension-only tools. The `add-teacher-role` change
(archived) forward-declares `content_analyzer:search` and
`content_analyzer:knowledge_graph` as `preferred_tools` but they remain
non-functional. P5 (`ms-graph-extension`), P14 (`google-extensions`),
and P9 (`error-resilience`) all target this layer — none can land
until discovery + tool construction exists.

This change implements the HTTP discovery + tool-building path:
`src/assistant/http_tools/` queries each persona's configured service
for an **OpenAPI 3.x document at `{base_url}/openapi.json`** (falling
back to `{base_url}/help` if the primary path 404s — the legacy
endpoint referenced in earlier roadmap drafts serves the same OpenAPI
document). The layer generates a Pydantic input model per operation,
wraps the async HTTP call as a LangChain `StructuredTool`, and feeds
the resulting registry into `DefaultToolPolicy`. After this lands,
`assistant --list-tools` becomes a real command, `cli.py` calls
`discover_tools()` at startup, and HTTP tools flow through the same
per-role filtering as extension tools.

## What Changes

### 1. New `src/assistant/http_tools/` package

- **`discovery.py`** — `async def discover_tools(tool_sources: dict[str, ToolSourceConfig]) -> HttpToolRegistry`
  fetches `/openapi.json` (falling back to `{base_url}/openapi.json`)
  for each configured source, parses with a minimal OpenAPI 3.x reader,
  and returns a registry keyed by `"{source_name}:{operation_id}"`.
  Handles 404/5xx per source gracefully (logs warning, skips that
  source — does not fail entire startup).

- **`builder.py`** — `_build_tool(source_name, op_id, operation, schemas, client, auth) -> StructuredTool`
  generates a Pydantic input model via `pydantic.create_model()` from
  the operation's `requestBody` + `parameters` JSON schemas, and wraps
  the call as a `StructuredTool` whose `coroutine` invokes
  `client.request(method, path, json=..., params=..., headers=auth)`.

- **`auth.py`** — `resolve_auth_header(auth_header_config: AuthHeaderConfig) -> dict[str, str]`
  reads the configured `{type: bearer|api-key, env: VAR_NAME, header?: str}`
  and returns the HTTP header dict. Static only — no refresh, no OAuth
  (deferred to P10 extension-lifecycle + P5 ms-graph-extension).

- **`registry.py`** — `HttpToolRegistry` TypedDict wrapper over
  `dict[str, StructuredTool]` with lookup helpers
  (`by_source(name)`, `by_preferred(preferred_tools)`).

- **`__init__.py`** — public API: `discover_tools`, `HttpToolRegistry`.

### 2. `DefaultToolPolicy` accepts a registry

Extend `src/assistant/core/capabilities/tools.py:DefaultToolPolicy`:

- Add optional `http_tool_registry: HttpToolRegistry | None = None`
  constructor parameter.
- In `authorized_tools(...)`, after aggregating extension tools, merge
  HTTP tools from the registry filtered by each loaded extension's
  `tool_source_name` (or unfiltered when no role `preferred_tools` is
  set). Respect `role.preferred_tools` by exact name match
  (`"{source_name}:{operation_id}"`).
- In `export_tool_manifest(...)`, include the HTTP tool catalog under
  a new `http_tools` key alongside `extensions` and `tool_sources`.

### 3. `CapabilityResolver` forwards the registry

`src/assistant/core/capabilities/resolver.py`:

- Add `http_tool_registry` parameter on `__init__` (default `None`).
- When no `tool_factory` override is provided, construct
  `DefaultToolPolicy(http_tool_registry=self._http_tool_registry)` in
  both host and SDK paths.

### 4. CLI startup calls `discover_tools`

`src/assistant/cli.py`:

- Remove the "HTTP tool discovery is deferred to P2" warning block.
- Before `adapter.create_agent(...)`, when any
  `pc.tool_sources[*].base_url` is set, `await discover_tools(pc.tool_sources)`
  and pass the resulting registry to `CapabilityResolver` (or directly
  to the policy factory).
- Pass `tools=http_registry.as_list()` to `create_agent` — replacing
  the `tools=[]` stub.

### 5. New `assistant --list-tools` subcommand

`src/assistant/cli.py`:

- Add a `--list-tools` flag (mutually exclusive with the default REPL)
  that runs discovery, prints a per-source breakdown with tool names,
  descriptions, and input schemas, then exits 0.
- Exit code 1 if any configured source fails discovery; prints the
  failure reason alongside the sources that succeeded.

### 6. Integration tests against a mock server

- Add `pytest-httpserver` as a `dev` dependency.
- `tests/http_tools/test_discovery.py` — spins up an `HTTPServer`
  fixture serving a sample OpenAPI 3.1 document, asserts
  `discover_tools` produces the expected `HttpToolRegistry`.
- `tests/http_tools/test_builder.py` — verifies the generated
  `StructuredTool` has the right Pydantic input model, calls the right
  URL/method/headers, and raises on 4xx/5xx.
- `tests/http_tools/test_auth.py` — bearer, api-key, custom header.
- `tests/test_cli.py` — end-to-end CLI behavior: `CliRunner().invoke(cli,
  ["--list-tools", "-p", "fixture"])` against a pytest-httpserver
  fixture. CLI tests live alongside other `tests/test_cli.py` cases
  rather than under `tests/http_tools/` to keep CLI entry-point
  coverage in one place.

### 7. Spec deltas

- **ADDED `http-tools`** capability spec (new, under
  `openspec/specs/http-tools/`) — covers discovery, tool construction,
  auth header handling, registry, and `--list-tools` CLI behavior.
- **MODIFIED `capability-protocols`** capability spec — adds a
  `Scenario` under the existing `DefaultToolPolicy` requirement that
  the policy SHALL merge an optional `http_tool_registry` into the
  authorized tools list and respect `role.preferred_tools` for
  `"{source_name}:{operation_id}"` keys.

## Approaches Considered

### Approach A (Recommended): Dedicated `http_tools/` module, registry injected into CapabilityResolver

**How it works**: All discovery / tool-building lives in a new
`src/assistant/http_tools/` package. `cli.py` calls
`discover_tools(tool_sources)` once at startup, passes the resulting
registry to `CapabilityResolver(http_tool_registry=...)`.
`DefaultToolPolicy` reads the registry and merges its tools with the
extension-provided ones inside `authorized_tools()`. No new abstraction
layer.

**Pros**
- Minimal surface: four new files (`discovery.py`, `builder.py`,
  `auth.py`, `registry.py`) + three modifications (`tools.py`,
  `resolver.py`, `cli.py`).
- Registry is explicit data flowing from `cli.py` → `CapabilityResolver`
  → `DefaultToolPolicy`. Easy to test: the policy accepts either a
  registry or `None`.
- Fast startup: one parallel fan-out of httpx GETs, no framework
  overhead.
- Future tool sources (MCP in P17) can be added by extending the
  registry type or introducing a sum type when that phase lands — YAGNI
  until then.

**Cons**
- `CapabilityResolver` gains one more constructor parameter. If P5/P14
  introduce their own discovery paths, we may need to refactor to a
  `ToolSource` list. But the refactor is mechanical.
- The registry is shape-specific to HTTP/OpenAPI — other sources (MCP)
  would need a parallel registry until unified.

**Effort**: M (~350-450 LOC new, ~40 LOC modified)

### Approach B: `ToolSource` abstraction with `HttpToolSource` as first impl

**How it works**: Introduce `ToolSource` Protocol
(`async def discover() -> list[StructuredTool]`) in
`src/assistant/core/capabilities/sources.py`. Implement
`HttpToolSource(tool_sources_config)` as the first concrete source.
`CapabilityResolver` accepts `list[ToolSource]`; `DefaultToolPolicy`
iterates sources and aggregates.

**Pros**
- Forward-compatible with MCP (`McpToolSource`), A2A agent tools
  (`AgentCardToolSource`), and persona-provided sources.
- Cleaner separation — `DefaultToolPolicy` doesn't know about HTTP
  specifics.

**Cons**
- More abstraction than P3 needs — the only source we're implementing
  is HTTP. Protocol ergonomics need design work (sync vs async
  discovery, refresh semantics) that are premature.
- Couples P3 to a decision that's better made in P17 (MCP server
  exposure) when we have a second source to generalize from.
- Violates YAGNI: the abstraction that feels right now will almost
  certainly want revision once we have a real second implementer.

**Effort**: M-L (~450-600 LOC new — includes the abstraction + a
concrete impl)

### Approach C: Discovery owned by `DefaultToolPolicy` (lazy, cached)

**How it works**: Pass `tool_sources` config directly into
`DefaultToolPolicy`. First call to `authorized_tools()` triggers
discovery; results cached in the policy instance. No separate registry
type, no startup discovery.

**Pros**
- Fewer moving parts — no registry, no new module seam.

**Cons**
- Violates the roadmap acceptance outcome: *"cli.py calls discover_tools
  at startup"*. Under this approach, CLI doesn't call discovery — the
  first tool-using invocation does, which can surprise users with
  unrelated-looking latency.
- `--list-tools` forces an eager discovery anyway — so we'd have both
  paths.
- Harder to test the discovery layer in isolation because it's fused
  into the policy.

**Effort**: M (~300-400 LOC new)

## Recommended

**Approach A** — matches the roadmap acceptance outcomes literally,
keeps the new surface minimal, and defers the abstraction question to
P17 when there's a genuine second tool source to generalize from.

### Selected Approach

**Approach A** (confirmed at Gate 1, 2026-04-23). No modifications
requested.

Rejected alternatives (for audit trail):
- **Approach B** — `ToolSource` abstraction. Premature; defer until
  P17 `mcp-server-exposure` provides a second concrete source to
  generalize from.
- **Approach C** — Discovery owned by `DefaultToolPolicy` (lazy +
  cached). Contradicts roadmap acceptance outcome *"cli.py calls
  discover_tools at startup"* and fuses discovery into the policy,
  making it harder to test in isolation.

## User-confirmed decisions (from discovery gate)

- **Discovery shape**: OpenAPI 3.x documents at `{base_url}/openapi.json`.
- **Policy integration**: Extend `DefaultToolPolicy` to merge HTTP
  tools with extension tools.
- **Mock server**: `pytest-httpserver` — real HTTP on a random port,
  exercises the full httpx stack.
- **Auth scope**: Static `bearer` and `api-key` only. OAuth / refresh
  flows deferred to P5 (ms-graph-extension) + P10
  (extension-lifecycle).

## Impact

**Phases this unblocks**: P5 `ms-graph-extension`, P9
`error-resilience` (retries applied to http_tools client), P14
`google-extensions`, X1 `add-teacher-role`'s forward-declared
`content_analyzer:*` tools.

**Breaking**: None. Personas without `tool_sources` configured are
unaffected (the CLI path is a no-op). Existing extensions continue to
expose tools via `as_langchain_tools()`.

**Migration**: None required. The "HTTP tool discovery deferred to P2"
warning simply disappears.
