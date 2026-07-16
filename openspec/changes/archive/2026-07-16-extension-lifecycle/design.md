# Design: extension-lifecycle

## D1 — Optionality mechanism: documented-optional hooks + `ExtensionBase`, NOT Protocol members

**Decision**: the three lifecycle hooks are *not* added to the
`runtime_checkable Extension` Protocol's required surface. Call sites
(`PersonaRegistry`) discover each hook independently via
`callable(getattr(ext, "<hook>", None))`. A plain class
`ExtensionBase` with async no-op defaults ships in
`extensions/base.py` for public (and willing private) extensions to
subclass.

**Rationale**:

- A `typing.Protocol` cannot carry default implementations that
  structural implementers inherit — private submodule extensions
  satisfy `Extension` *structurally only* (they must not import
  `assistant.*`; see the standalone-test constraint in CLAUDE.md), so
  a Protocol change cannot give them defaults.
- `runtime_checkable` `isinstance` checks attribute presence. Adding
  the hooks to the Protocol would make `isinstance(ext, Extension)`
  return `False` for every existing hook-less extension, violating
  the tool-policy spec scenario "each extension MUST satisfy
  `isinstance(ext, Extension)`" and breaking private-persona
  extensions on upgrade — exactly what the roadmap row forbids.
- The hybrid gives both worlds: zero-change compatibility for
  structural implementers (hasattr checks), and inherited no-ops for
  in-tree classes (`StubExtension`, the four MS extensions) so they
  are lifecycle-complete without boilerplate.
- Precedent: the health-check widening (P9 D11) already established
  the pattern of a runtime conformance treatment at the registry
  rather than a Protocol-type change breaking structural implementers.

**Rejected alternatives**:

- *Hooks on the Protocol* — breaks `isinstance` for legacy extensions
  (above).
- *ABC replacing the Protocol* — would force private extensions to
  import `assistant.extensions.base`, violating the privacy boundary
  (private submodule tests must be self-contained, no
  `src/assistant/*` imports).
- *Separate `LifecycleExtension` Protocol for narrowing* — adds a
  public name with no consumer; per-hook `getattr` at the single call
  site is smaller and allows an extension to implement only
  `shutdown()` without faking the other two.

## D2 — Hook call tolerance (conformance treatment)

`initialize()`/`shutdown()`/`refresh_credentials()` are specified
async, but the registry calls them tolerantly: it invokes the hook and
awaits the result only when `inspect.isawaitable(result)` is true. A
private extension that wrote a *sync* `def initialize(self)` therefore
still works instead of failing on `await None`.

Unlike `health_check()` (P9 D11 conformance guard), no return-type
guard is needed: the hooks return `None`, so there is no
silently-wrong-type failure mode to trap — any misbehavior surfaces as
an exception, which the disable-on-failure path already handles. The
existing health-check conformance guard is unchanged.

## D3 — Failure semantics: failing `initialize()` disables that extension only

`load_extensions` wraps each `initialize()` in `try/except Exception`:
on failure it logs a WARNING naming the extension and the error,
best-effort awaits the instance's `shutdown()` (the failed initialize
may have opened partial resources — errors here are swallowed at DEBUG),
and excludes the instance from the returned list. Persona load never
fails because one extension failed to initialize; sibling extensions
still load. This mirrors the existing missing-module
warn-and-continue behavior.

`TypeError` from the *factory* contract (legacy signature, real
factory without persona) keeps its existing fail-fast behavior — the
disable-on-failure rule applies to the initialize phase only.

## D4 — Sync/async boundary: `load_extensions` vs `load_extensions_async`

Both production call sites (`cli._run_repl_with_registry`,
`web.app._default_agent_factory`) run inside an event loop, but the
historical `load_extensions()` is sync and widely used by tests.

**Decision**: `load_extensions_async(config)` is the primary
implementation (load → initialize → register shutdown).
`load_extensions(config)` becomes a thin wrapper:
`asyncio.run(self.load_extensions_async(config))` when no loop is
running; if a loop *is* running it raises an actionable
`RuntimeError` directing the caller to the async variant (a sync call
cannot await, and running initializers on a throwaway worker-thread
loop would bind extension resources — e.g. httpx pools — to a dead
loop). Both production call sites are migrated to the async variant
in this change; sync callers (tests, scripts) keep the exact
one-call ergonomics they had.

## D5 — Shutdown registration: atexit + explicit `shutdown_extensions()`

The registry tracks successfully initialized extensions in
`_active_extensions` (load order). `shutdown_extensions()` is async,
drains the list first (idempotent — a second/concurrent call sees an
empty list), and calls each extension's `shutdown()` in **reverse
load order**, swallowing and WARNING-logging per-extension errors.

An `atexit` handler is registered once per registry instance, on the
first load that produces extensions. At interpreter exit no loop is
running, so the handler wraps `shutdown_extensions()` in
`asyncio.run()`; if the daemon path already shut down explicitly the
list is empty and the handler is a no-op. Errors at atexit time are
swallowed (interpreter is dying; nothing actionable).

Explicit teardown is wired where a clean async context exists:
`web/app.py` lifespan `finally` and `cli._run_repl` `finally`.

## D6 — `refresh_credentials` wiring reality (MSAL)

`GraphClient` already performs *reactive* refresh: a 401
`invalid_token` triggers exactly one
`strategy.acquire_token(force_refresh=True)` retry inside
`_send_with_auth_retry` (D9 of ms-graph-extension). That path is
correct and self-contained — it does **not** need, and is not
rerouted through, the extension-level hook.

`Extension.refresh_credentials()` is therefore the **proactive** seam:

- `GraphClient` gains a public `refresh_credentials()` that awaits
  `self._strategy.acquire_token(self._scopes, force_refresh=True)`
  and discards the token (side effects: MSAL cache update + on-disk
  persist for the delegated strategy).
- Each MS extension's `refresh_credentials()` delegates to
  `getattr(self._client, "refresh_credentials", None)` when callable
  — `CloudGraphClient` (the injected Protocol) does not declare the
  method, so mocks and third-party clients without it degrade to a
  no-op instead of crashing. Promoting the method onto
  `CloudGraphClient` is deliberately deferred until a consumer
  requires it on the Protocol (P14).
- No caller invokes the hook periodically yet; P14
  (`google-extensions` OAuth) and any scheduled-refresh work are the
  documented consumers. The hook exists now so P13/P14 do not need
  another protocol change.

## D7 — `initialize()` on MS extensions stays a no-op

Eagerly acquiring a token in `initialize()` would fire
`acquire_token_interactive` (browser prompt) at persona load for the
delegated flow — hostile for a CLI startup and impossible for a
daemon. Connection pools are lazy in httpx. So the four MS extensions
inherit the no-op `initialize()`; their real lifecycle value is
`shutdown()` (closing the never-before-closed `GraphClient` pool,
satisfying the anticipation in `cloud_client.py`'s `aclose` contract)
and `refresh_credentials()`.

## D8 — Interaction with P24 `tool-spec` (`Extension.tool_specs()`)

The tool-spec spec adds `tool_specs() → list[ToolSpec]` to the
extension contract and deprecates the per-harness tool methods. The
lifecycle hooks are orthogonal to the tool surface: they neither
consume nor produce tools, and `ExtensionBase` deliberately carries
*only* lifecycle defaults (no tool-method stubs) so it composes
cleanly whichever tool surface an extension implements during the
migration window. When P24 lands, `ExtensionBase` is the natural
place for a default `tool_specs()` shim, but this change does NOT
implement `ToolSpec`.

## D9 — Ordering guarantees

- `initialize()` runs in `PersonaConfig.extensions` declaration order
  — per-extension, immediately after that instance's health guard is
  installed and before the next module is loaded. This keeps the
  existing one-pass loop shape, and a failing (disabled) extension
  never blocks a later one.
- `shutdown()` runs in reverse activation order, so extensions that
  (in the future) depend on earlier-loaded ones tear down first.
