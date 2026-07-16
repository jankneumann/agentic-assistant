# Proposal: extension-lifecycle

## Why

The `Extension` protocol (`src/assistant/extensions/base.py`) exposes
only tool accessors and `health_check()`. Nothing in the system ever
initializes an extension after construction, closes one on shutdown, or
offers a seam for proactive credential refresh (perplexity feedback
§3.1). The concrete cost today: every real MS extension constructs a
`GraphClient` whose `httpx.AsyncClient` connection pool is **never
closed** — the `CloudGraphClient.aclose()` contract even anticipates
"`PersonaRegistry.load_extensions` may end up closing a client"
(`src/assistant/core/cloud_client.py:128`), but no caller exists. There
is also no place for P13 (`security-hardening` manifest validation) or
P14 (`google-extensions` OAuth) to hang startup-time or refresh-time
behavior.

## What Changes

1. **Optional async lifecycle hooks** — `initialize()`, `shutdown()`,
   `refresh_credentials()` — are added to the extension contract as
   *documented-optional* members. The required `Extension` Protocol
   surface is unchanged (a `typing.Protocol` cannot carry default
   implementations, and adding the hooks to the `runtime_checkable`
   Protocol would flip `isinstance(ext, Extension)` to `False` for
   every existing private-submodule extension). Call sites discover
   each hook via `callable(getattr(ext, hook, None))`.

2. **`ExtensionBase`** (`src/assistant/extensions/base.py`) — a
   plain adoption base class carrying async no-op defaults for the
   three hooks. `StubExtension` and the four real MS extension classes
   subclass it; private structural-only extensions need no change.

3. **`PersonaRegistry` lifecycle driving**
   (`src/assistant/core/persona.py`):
   - `load_extensions()` calls `initialize()` post-load on each
     extension that defines it, in declaration order. A failing
     `initialize()` disables **that** extension (warning + excluded
     from the returned list, best-effort `shutdown()` of the partial
     instance) without failing persona load.
   - New `load_extensions_async()` is the awaitable form for callers
     already inside an event loop (CLI REPL, AG-UI server). The sync
     `load_extensions()` wraps it in `asyncio.run()` and raises an
     actionable `RuntimeError` if invoked while a loop is running.
   - Successfully loaded extensions are tracked; an `atexit` handler
     is registered once, and an explicit async
     `shutdown_extensions()` (reverse load order, error-swallowed,
     idempotent) serves tests and daemon shutdown paths.

4. **`GraphClient.refresh_credentials()`**
   (`src/assistant/core/graph_client.py`) — proactive
   `force_refresh=True` token acquisition. The existing *reactive*
   401 `invalid_token` retry path (D9) is untouched and does not
   route through the hook; the hook is the proactive/periodic seam
   for P13/P14 consumers.

5. **MS extensions wire the hooks** — each of
   `ms_graph`/`outlook`/`teams`/`sharepoint` implements `shutdown()`
   (close the injected client via its idempotent `aclose()`) and
   `refresh_credentials()` (delegate to the client's
   `refresh_credentials` when it exposes one; no-op for mocks).
   `initialize()` stays the inherited no-op — eager token acquisition
   at startup would trigger interactive MSAL prompts.

6. **Call-site updates** — `cli.py` and `web/app.py` switch to
   `await load_extensions_async(...)` and invoke
   `shutdown_extensions()` on teardown.

## Capabilities

### Modified: `extension-registry`

Optional lifecycle-hook contract + `ExtensionBase` + MS extension
wiring.

### Modified: `persona-registry`

`load_extensions()` initialization semantics, async variant, shutdown
registration.

### Modified: `graph-client`

`refresh_credentials()` proactive refresh method.

## Impact

- `src/assistant/extensions/base.py`, `_stub.py`, `ms_graph.py`,
  `outlook.py`, `teams.py`, `sharepoint.py`
- `src/assistant/core/persona.py`, `src/assistant/core/graph_client.py`
- `src/assistant/cli.py`, `src/assistant/web/app.py`
- Tests: new `tests/test_extension_lifecycle.py`; existing suites
  unchanged in expectation (stubs keep loading, hook-less private
  extensions keep loading).
- **Not in scope**: `ToolSpec` migration (P24 `tool-spec` owns
  `Extension.tool_specs()`; the hooks added here are orthogonal to the
  tool surface and remain compatible — see design.md), non-allow-all
  guardrails (P13), scheduled/periodic refresh invocation (P14).
