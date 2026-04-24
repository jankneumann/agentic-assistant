# Observability Design

Companion to `proposal.md`. Covers the technical design decisions that the selected approach (Approach A, typed Protocol + full hook coverage) implies.

## Module Layout

```
src/assistant/telemetry/
├── __init__.py                  # re-exports + outbound-only posture docstring
├── providers/
│   ├── __init__.py
│   ├── base.py                  # ObservabilityProvider Protocol (runtime_checkable)
│   ├── noop.py                  # NoopProvider — zero-allocation default
│   └── langfuse.py              # LangfuseProvider — native SDK, lazy import
├── factory.py                   # get_observability_provider() + 3-level degradation + singleton
├── config.py                    # TelemetryConfig frozen dataclass + from_env()
├── context.py                   # ContextVar-backed set/get/assistant_ctx context mgr (D4)
├── decorators.py                # @traced_harness, @traced_delegation — created by wp-hooks
├── tool_wrap.py                 # wrap_structured_tool + wrap_extension_tools — created by wp-hooks
├── sanitize.py                  # ordered regex list + sanitize(value) + _sanitize_mapping
└── flush_hook.py                # atexit registration + LANGFUSE_FLUSH_MODE dispatch
```

**Ownership note**: `src/assistant/telemetry/` as a directory is split across two work packages:
- `wp-contracts` owns everything except `decorators.py` and `tool_wrap.py`
- `wp-hooks` owns `decorators.py` and `tool_wrap.py` (they implement hook-integration logic that is logically part of the hook package, even though the files live under the telemetry module for import clarity)

Scope boundaries are enforced via explicit `write_allow`/`deny` lists in `work-packages.yaml` — no glob overlap.

## Decision 1 — Singleton Provider Lifecycle

**Decision**: `get_observability_provider()` returns a module-level singleton, initialized on first call, cached thereafter.

**Alternatives considered**:
- Per-call fresh instance — rejected. Langfuse SDK is designed to be reused; fresh instances would defeat batching.
- Explicit factory handle passed through every call — rejected. Would require threading the provider through every `invoke`/`delegate`/tool call — churn across the codebase for no benefit.
- Dependency injection via persona config — rejected for now. May be revisited in `work-persona-config` if personas need distinct telemetry backends.

**Implementation**:
```python
_provider: ObservabilityProvider | None = None
_provider_lock = threading.Lock()

def get_observability_provider() -> ObservabilityProvider:
    global _provider
    if _provider is not None:
        return _provider
    with _provider_lock:
        if _provider is not None:
            return _provider
        _provider = _init_provider()
        atexit.register(_provider.shutdown)
    return _provider
```

## Decision 2 — Three-Level Degradation State Machine

**Decision**: Each degradation check is a guard clause in `_init_provider()`, and a `NoopProvider` is returned at the first failure. A single warning per-process is emitted via `warnings.warn` (not `logger.warning`) so it's visible even when logging isn't configured.

**Alternatives considered**:
- Raise on failure, require callers to wrap in try/except — rejected. Every call site would need the same boilerplate; easy to forget → crash.
- Return `Optional[Provider]` and require `if provider is not None:` guards — rejected. Defeats the whole point of the noop provider pattern.

**State machine**:
```
                          ┌────────────────────┐
                          │ _init_provider()   │
                          └──────────┬─────────┘
                                     │
              Level 1: enabled?      │
         ┌───── false ────────────── ▼ ──────── true ────────┐
         │                                                    │
         ▼                                          ┌─────────▼─────────┐
     NoopProvider()                                 │ import langfuse   │
                                                    └─────────┬─────────┘
                                                              │
                                  Level 2: import ok?         │
                         ┌──── ImportError ────────────────── ▼ ── success ──┐
                         │                                                    │
                         ▼                                    ┌───────────────▼──┐
                     NoopProvider()                           │ LangfuseProvider  │
                     + warnings.warn(once)                    │   .setup()        │
                                                              └────────┬──────────┘
                                                                       │
                                         Level 3: setup ok?            │
                                    ┌──── any Exception ──────── ─ ─ ▼ ── success ──┐
                                    │                                                  │
                                    ▼                                                  ▼
                               NoopProvider()                               return LangfuseProvider
                               + warnings.warn(once)
```

## Decision 3 — Hook Integration via Decorators, Not Explicit Calls

**Decision**: Harness + delegation use `@traced_*` decorators; extension + http-tool use per-tool wrappers constructed at `as_langchain_tools()` / `_build_structured_tool` time; memory + graphiti use inline decorators on their primary methods.

**Alternatives considered**:
- Explicit `provider.trace_llm_call(...)` calls at each hook site — rejected. Churn across call sites, easy to forget, hard to refactor when the Protocol evolves.
- Middleware chain — rejected. Overkill for Python-sync-await code; the decorator approach already gives the same insertion points.

**Decorator signatures**:
```python
def traced_harness(f: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]: ...
def traced_delegation(f: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]: ...
def traced_memory_op(op: MemoryOp) -> Callable[[F], F]: ...
```

For tools, `wrap_structured_tool(tool, tool_kind, persona_getter, role_getter)` returns a new `StructuredTool` whose `_arun` calls `trace_tool_call(...)` around the original `_arun`.

## Decision 4 — Persona/Role Context Propagation

**Problem**: Spans need the current persona + role at emission time, but the hook sites (harness.invoke, delegation.delegate, tool._arun) don't all receive persona/role as method arguments.

**Decision**: Use a `contextvars.ContextVar[tuple[str | None, str | None]]` named `_CURRENT_ASSISTANT_CTX`, set at CLI startup when a persona/role are selected and updated at every delegation hop (so sub-agents emit spans with the sub-role).

**Alternatives considered**:
- Pass persona/role into every invoke/delegate/tool signature — rejected. Churn across every harness adapter, every extension, every tool. Not viable retrofit.
- Global module-level variable — rejected. Breaks under async concurrency (multiple conversations in one process, e.g., MCP server phase).
- `threading.local` — rejected. Doesn't propagate across `await` boundaries.

**Implementation location**: `src/assistant/telemetry/context.py` exports `set_assistant_ctx(persona, role)`, `get_assistant_ctx() -> tuple[str | None, str | None]`, and `assistant_ctx(persona, role)` context manager used by the delegation decorator to push the sub-role scope.

## Decision 5 — Sanitization as a Pure Function, Applied at Emission

**Decision**: `sanitize(value: str) -> str` is a pure function taking a string and returning the sanitized version. Every `trace_*` method on `LangfuseProvider` (and, defensively, on `NoopProvider` too) calls `_sanitize_mapping(metadata)` before emission.

**Regex ordering**:
```python
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(pk|sk)-lf-[A-Za-z0-9]+"), "LF-KEY-REDACTED"),
    (re.compile(r"sk-[A-Za-z0-9]+"), "SK-REDACTED"),
    (re.compile(r"sbp_[A-Za-z0-9]+"), "SBP-REDACTED"),
    (re.compile(r"eyJ[A-Za-z0-9_\-\.]+"), "JWT-REDACTED"),
    (re.compile(r"Bearer +[A-Za-z0-9_\-\.=]+"), "Bearer REDACTED"),
    (re.compile(r"git@[^\s:]+:[^\s]+\.git"), "SUBMODULE-URL-REDACTED"),
    (re.compile(r"https://[^\s@]+@[^\s]+\.git"), "SUBMODULE-URL-REDACTED"),
    (re.compile(r"(?i)(password|token|secret|key)=[^\s&]+"), r"\1=REDACTED"),
]
```

Ordering rationale: `pk-lf`/`sk-lf` come first because they're a specialization of `sk-*`; if `sk-*` matched first, the Langfuse-specific marker would be lost. Bearer is before the generic `key=value` catch-all.

**Fields never sanitized**: `persona`, `role`, `sub_role`, `parent_role`, `tool_name`, `model`, `name` (span name), `outcome`. These are semantic identifiers and expected to be short, known-safe strings.

## Decision 6 — Flush Mode via atexit

**Decision**: `atexit.register(provider.shutdown)` is called once inside `get_observability_provider()` after provider init succeeds. When `LANGFUSE_FLUSH_MODE=per_op`, each `trace_*` method on `LangfuseProvider` calls `self._client.flush()` before returning.

**Why atexit over `__del__` or context-manager**:
- `__del__` is unreliable under interpreter shutdown; `atexit` is the canonical Python pattern.
- Context-manager at CLI entrypoint works, but breaks for long-running processes like a future MCP server or A2A server where there's no natural "exit" boundary. `atexit` still fires.

**Process-crash behavior**: If the process crashes (SIGKILL, OOM), `atexit` does not fire and buffered events are lost. This is an accepted tradeoff documented in `docs/observability.md` — users running unstable workloads should set `LANGFUSE_FLUSH_MODE=per_op`.

## Decision 7 — NoopProvider is Zero-Allocation

**Decision**: Every `NoopProvider` method is defined as:

```python
def trace_llm_call(self, **kwargs: Any) -> None:
    return None
```

No `pass` body. No intermediate dict construction. No super() calls. Methods accept `**kwargs` so keyword-only callers don't raise, but the kwargs dict itself is created by Python's call machinery, not by us.

**Why this matters**: The noop path is on the hot loop for every harness/tool/memory op. If the noop provider allocates a span dict, a metadata dict, or a logger message on every call, observability adds real latency even when disabled.

**Verification**: `tests/telemetry/test_noop_perf.py` uses `tracemalloc` to assert 10k noop calls don't grow the heap beyond the size of kwarg dicts passed in by the caller. This is a sanity check, not a strict microbenchmark — CI runners are noisy.

## Decision 8 — Test Strategy for 3-Level Degradation

Mirroring the newsletter-aggregator pattern (`tests/telemetry/test_langfuse_provider.py:155`):

```python
def test_factory_returns_noop_on_import_error(monkeypatch):
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "langfuse":
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    # Clear singleton cache
    import src.assistant.telemetry.factory as factory
    factory._provider = None

    provider = factory.get_observability_provider()
    assert provider.name == "noop"
```

Same pattern applies for runtime-failure (patch `LangfuseProvider.setup` to raise) and disabled (just unset env vars). Each of the three levels has a dedicated test.

## Decision 9 — LANGFUSE_INIT_* in Docker Compose (from Day 1)

**Decision**: `docker-compose.langfuse.yml` includes `LANGFUSE_INIT_ORG_ID`, `LANGFUSE_INIT_ORG_NAME`, `LANGFUSE_INIT_PROJECT_ID`, `LANGFUSE_INIT_PROJECT_NAME`, `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`, `LANGFUSE_INIT_PROJECT_SECRET_KEY`, `LANGFUSE_INIT_USER_EMAIL`, and `LANGFUSE_INIT_USER_PASSWORD` for the langfuse-web service, pointing at dev-default values committed alongside the compose file.

This mirrors agentic-coding-tools (which does have these) and fixes the gap that memory explicitly flagged as a newsletter-aggregator follow-up. Local `docker-compose -f docker-compose.langfuse.yml up -d` gives a usable Langfuse instance with seeded keys — no UI signup step required.

**Dev-default values** (committed, prefixed with `DUMMY-` so secret scanners like gitleaks and trufflehog skip them, and so a copy-paste to a production deployment is instantly visually wrong):
```yaml
LANGFUSE_INIT_ORG_ID: DUMMY-dev-org
LANGFUSE_INIT_ORG_NAME: "agentic-assistant dev (DUMMY)"
LANGFUSE_INIT_PROJECT_ID: DUMMY-dev-project
LANGFUSE_INIT_PROJECT_NAME: "agentic-assistant (DUMMY)"
LANGFUSE_INIT_PROJECT_PUBLIC_KEY: DUMMY-pk-lf-dev-local
LANGFUSE_INIT_PROJECT_SECRET_KEY: DUMMY-sk-lf-dev-local
LANGFUSE_INIT_USER_EMAIL: dev@localhost
LANGFUSE_INIT_USER_PASSWORD: DUMMY-change-me-before-prod
```

Additionally the compose file SHALL include a startup-check sidecar script that refuses to start the Langfuse container if any `LANGFUSE_INIT_*` value is `DUMMY-*` AND the `HOST` environment does not include `localhost` or `127.0.0.1` — preventing accidental launch with dev defaults outside a developer machine.

Documented in `docs/observability.md` as dev-only — never use these for a production Langfuse instance. Also listed in a `.gitleaksignore` file at repo root so secret scanners do not false-positive on the committed placeholders.

## Decision 10 — Claude Code Stop Hook Wiring (Documentation Only)

**Decision**: We do NOT re-implement the hook. `docs/observability.md` documents how to wire the existing repo-agnostic script at `~/Coding/agentic-coding-tools/agent-coordinator/scripts/langfuse_hook.py` into `~/.claude/settings.json` by setting `LANGFUSE_*` env vars and pointing the Stop hook config at the shared script.

**Rationale**: The hook is genuinely repo-agnostic — it reads the Claude Code transcript, cursor-tracks lines consumed, and sanitizes before emitting. Re-implementing would duplicate code and drift. The memory file explicitly flagged this as a "don't re-implement" item.

## Decision 11 — Test Fixtures: SpyProvider and Singleton Reset

**Decision**: Two test fixtures published in `tests/telemetry/conftest.py`, both `autouse=True` for the `tests/telemetry/` subtree:

1. **`reset_telemetry_singleton`**: sets `src.assistant.telemetry.factory._provider = None` before each test so the module-level cache from D1 does not leak between test cases. Without this fixture, a test that exercises the level-2 `ImportError` path would be invalidated by any prior test that successfully initialized a provider, because the singleton would remain cached. Applied automatically; no per-test opt-in needed.

2. **`spy_provider`** (not autouse — opt-in): returns a `SpyProvider` subclass of `NoopProvider` that records every Protocol method call into an in-memory list. Tests that need to assert "this call site emitted a `trace_llm_call` with these kwargs" can use `spy_provider.calls["trace_llm_call"]` to inspect the ordered history. `SpyProvider` inherits `NoopProvider`'s zero-allocation posture for methods it does not record, so it can stand in for the default provider without changing production behavior.

**Why both are fixtures, not ad-hoc patches**: applying them consistently prevents a common pytest pitfall where one test file installs monkeypatches that leak into a parallel test file's state. Fixtures are torn down deterministically by pytest's scope machinery.

**Location**: `tests/telemetry/conftest.py` — a new file owned by wp-contracts per the work-packages scope.

## Decision 12 — Optional Extra vs Dependency Group for Langfuse

**Decision**: `langfuse>=3.0,<4.0` is declared under `[project.optional-dependencies].telemetry` in `pyproject.toml`. It is NOT part of the default dependency set, and NOT a dev-only dependency group.

**Why optional extra**:
- Default `uv sync` keeps the install lean for users who run with `LANGFUSE_ENABLED=false` (the vast majority at first, and effectively all of CI under the noop path).
- `uv sync --extra telemetry` opts in for developers or environments that want to emit spans. Explicit, discoverable, documented.
- Test machinery does not need `langfuse` installed — the level-2 degradation tests monkey-patch `builtins.__import__` to simulate its absence, which works whether the real package is installed or not. This means the test suite passes under both `uv sync` and `uv sync --extra telemetry`.

**Why not a dependency group**:
- Dependency groups (PEP 735) are scoped to workflows (dev, docs, etc.) rather than deployment profiles. Observability is a deployment toggle, not a workflow toggle.
- Some `uv`/`pip` installers handle extras more uniformly than groups; extras have broader tooling compatibility today.

**Why not a default dep**:
- Adds Langfuse SDK + its transitive deps (httpx, pydantic, etc.) to every default install even when disabled. Transitively pulls ~5 MB of wheel data.

**CI implication**: the default CI job runs without the extra; the optional `langfuse-smoke` job (task 5.5) runs `uv sync --extra telemetry` before exercising live Langfuse.

## Decision 13 — Empty-String Credentials Are Disambiguated From Unset

**Decision**: `TelemetryConfig.from_env()` treats an empty-string `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` as the SAME as unset for the purpose of enabling telemetry — both produce `enabled=False` — but the two cases are distinguished in the warning log emitted at factory init.

**Why both disable**:
- Submitting a span with an empty public/secret key to Langfuse returns an authentication error and wastes a network round-trip per operation.
- An empty string is almost always a misconfiguration (env-var substitution that resolved to nothing, a `.env` entry missing a value), so treating it as "intentional disable" would be misleading.

**Why distinguish in logs**:
- If `LANGFUSE_ENABLED=true` is set but keys are empty, the user has signaled intent to enable but bungled the credentials. The warning should say "enabled=true but credentials are empty" so the user can debug.
- If `LANGFUSE_ENABLED` is unset/false and keys are absent, there is no user intent to enable, and no warning is needed at info level.

**Whitespace handling**: a credential that is all-whitespace (e.g., `LANGFUSE_PUBLIC_KEY="   "`) is normalized via `.strip()` and treated as empty.

## Privacy Boundary Compliance

The two-layer privacy guard (`tests/conftest.py` + `tests/_privacy_guard_plugin.py`, G6 gotcha) patches filesystem I/O. Telemetry MUST NOT write spans to any filesystem path — only to external backends via HTTP. `NoopProvider` does literally nothing; `LangfuseProvider` uses the Langfuse HTTP SDK. No JSONL fallback, no local `/tmp/spans.log`, no filesystem side-effects from telemetry.

Test assertion: a dedicated test in `tests/telemetry/test_privacy_compliance.py` exercises the telemetry module under the privacy guard fixtures and asserts no blocked filesystem operations are attempted.

## Backward Compatibility

This change is additive. Existing code that doesn't import from `src/assistant/telemetry/` is unaffected. The `pyproject.toml` change gates the `langfuse` dep behind an optional `[telemetry]` extra; the default install remains trace-free. Tests that don't opt in to observability fixtures see a noop provider and no behavior change.

## Out of Scope

- Dashboards, alerting, SLO definitions — downstream of this layer.
- Integration with an existing APM backend (Datadog, Honeycomb, etc.) — future phase via OTel adapter.
- Persona-specific provider selection — deferred to `work-persona-config` phase if needed.
- HTTP middleware tracing for the future MCP server — handled when `mcp-server-exposure` phase lands.
- Cost aggregation / reporting — consumers query Langfuse directly; this change emits the raw events only.
