# Tasks: extension-lifecycle

## 1. Contract + base class

- [x] 1.1 Document the optional lifecycle hooks on the `Extension`
      Protocol docstring (required surface unchanged) in
      `src/assistant/extensions/base.py`
- [x] 1.2 Add `ExtensionBase` with async no-op
      `initialize`/`shutdown`/`refresh_credentials`
- [x] 1.3 `StubExtension` subclasses `ExtensionBase`

## 2. Transport + MS extensions

- [x] 2.1 `GraphClient.refresh_credentials()` — proactive
      `force_refresh=True` acquisition (reactive 401 path untouched)
- [x] 2.2 `ms_graph`/`outlook`/`teams`/`sharepoint` subclass
      `ExtensionBase`; override `shutdown()` (client `aclose()`) and
      `refresh_credentials()` (getattr-guarded client delegation)

## 3. PersonaRegistry lifecycle driving

- [x] 3.1 Extract module-loading into a private helper; add
      `load_extensions_async()` (load → tolerant `initialize()` per
      extension in declaration order → failure disables that
      extension with WARNING + best-effort shutdown)
- [x] 3.2 Sync `load_extensions()` wraps the async variant in
      `asyncio.run()`; actionable `RuntimeError` under a running loop
- [x] 3.3 Track active extensions; register `atexit` handler once;
      async `shutdown_extensions()` (reverse order, error-swallowed,
      idempotent) + sync atexit bridge
- [x] 3.4 Update call sites: `cli.py` `_run_repl` (async load +
      finally shutdown), `web/app.py` `_default_agent_factory` +
      lifespan finally shutdown

## 4. Tests

- [x] 4.1 `tests/test_extension_lifecycle.py`: initialize
      success/order, failure-disables-one, hook-less compatibility,
      sync-hook tolerance, running-loop RuntimeError, shutdown
      reverse-order/idempotence/failure containment, atexit
      registration, stub no-op hooks, MS shutdown closes client, MS
      refresh delegation + missing-method tolerance,
      `GraphClient.refresh_credentials` strategy call
- [x] 4.2 Verify existing suites unaffected (stubs, factory contract,
      persona registry)

## 5. Docs + validation

- [x] 5.1 CLAUDE.md extension-protocol touch-up
- [x] 5.2 `openspec validate extension-lifecycle --strict`
- [x] 5.3 Full gates: `uv run pytest tests/`, `ruff check src tests`,
      `mypy src tests`
