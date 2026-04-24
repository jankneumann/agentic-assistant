# Observability Design

Companion to `proposal.md`. Covers the technical design decisions that the selected approach (Approach A, typed Protocol + full hook coverage) implies.

## Module Layout

```
src/assistant/telemetry/
├── __init__.py                  # re-exports: get_observability_provider, ObservabilityProvider
├── providers/
│   ├── __init__.py
│   ├── base.py                  # ObservabilityProvider Protocol (runtime_checkable)
│   ├── noop.py                  # NoopProvider — zero-allocation default
│   └── langfuse.py              # LangfuseProvider — native SDK, lazy import
├── factory.py                   # get_observability_provider() + 3-level degradation
├── config.py                    # TelemetryConfig frozen dataclass + from_env()
├── decorators.py                # @traced_harness, @traced_delegation decorators
├── tool_wrap.py                 # wrap_structured_tool() for extensions + http_tools
├── sanitize.py                  # ordered regex list + sanitize(value)
└── flush_hook.py                # atexit registration + LANGFUSE_FLUSH_MODE dispatch
```

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

**Dev-default values** (committed):
```yaml
LANGFUSE_INIT_ORG_ID: dev-org
LANGFUSE_INIT_ORG_NAME: "agentic-assistant dev"
LANGFUSE_INIT_PROJECT_ID: dev-project
LANGFUSE_INIT_PROJECT_NAME: "agentic-assistant"
LANGFUSE_INIT_PROJECT_PUBLIC_KEY: pk-lf-dev-local
LANGFUSE_INIT_PROJECT_SECRET_KEY: sk-lf-dev-local
LANGFUSE_INIT_USER_EMAIL: dev@localhost
LANGFUSE_INIT_USER_PASSWORD: dev-password-change-me
```

Documented in `docs/observability.md` as dev-only — never use these for a production Langfuse instance.

## Decision 10 — Claude Code Stop Hook Wiring (Documentation Only)

**Decision**: We do NOT re-implement the hook. `docs/observability.md` documents how to wire the existing repo-agnostic script at `~/Coding/agentic-coding-tools/agent-coordinator/scripts/langfuse_hook.py` into `~/.claude/settings.json` by setting `LANGFUSE_*` env vars and pointing the Stop hook config at the shared script.

**Rationale**: The hook is genuinely repo-agnostic — it reads the Claude Code transcript, cursor-tracks lines consumed, and sanitizes before emitting. Re-implementing would duplicate code and drift. The memory file explicitly flagged this as a "don't re-implement" item.

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
