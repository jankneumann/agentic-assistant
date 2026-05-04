# Error Resilience Layer

**Change ID**: `error-resilience`
**Roadmap Phase**: P9 (item_id: `error-resilience`)
**Effort**: M
**Depends on**: `http-tools-layer` (archived 2026-04-24), `observability` (archived 2026-05-03)
**Blocks**: downstream phases that adopt the resilience theme on their new HTTP code paths (`ms-graph-extension`, `google-extensions`, `mcp-server-exposure`); also unblocks the §1.3 "graceful-degradation announcement" capability for any future role wanting to surface backend availability to the user.

## Why

The agent today has two failure modes that look identical to a user but are very different in cause:

1. **Transient HTTP failure (5xx, 429, network blip)** — `src/assistant/http_tools/builder.py:233` calls `client.stream(method, url, ...)` and immediately re-raises any non-2xx response via `raise_for_status()`. Tools fail on the first hiccup. There is no retry, no backoff, no jitter, no awareness that 5xx is fundamentally different from 4xx.
2. **Sustained backend outage** — there is no concept of "this backend is down — note it instead of trying every tool call". When MS Graph or Gmail is unreachable, every individual tool invocation will retry-and-fail in lockstep, multiplying load on a struggling backend and producing identical opaque exceptions to the agent loop.

Discovery is already graceful (`src/assistant/http_tools/discovery.py` catches `TimeoutException` / `HTTPError`, logs WARN, returns `None` per D4). Builder is not. Extensions declare `Extension.health_check() -> bool` (`src/assistant/extensions/base.py:21`) — a binary flag insufficient to express "down for the next 60 seconds because the last 5 calls returned 503".

This change lands the resilience substrate. It does **not** change agent prompting or introduce any new orchestration loop — it makes existing call paths automatically retry transient errors, fail fast when a backend is sustained-unhealthy, and expose enough state for an agent to truthfully announce unavailability rather than silently omit results.

Cross-references:
- Perplexity §1.3 (resilience: agent should observe and announce backend unavailability)
- Perplexity §8.8 (tenacity + circuit-breaker per backend + graceful degradation)
- Roadmap "Resilience" cross-cutting theme: P9 establishes; P3/P5/P14/P17 adopt
- Existing skill-layer breaker `.agents/skills/parallel-infrastructure/circuit_breaker.py` — sibling pattern for skill retries, **intentionally not shared** with the runtime layer this change adds (different lifecycle, different scoping)

## What Changes

### New module: `src/assistant/core/resilience.py`

Single runtime-layer module. Exports:

- `RetryPolicy` — frozen dataclass capturing the tenacity policy parameters (max_attempts, base_delay_s, max_delay_s, jitter_factor, retryable_status_codes, retryable_exceptions). Default constants for HTTP usage live in `DEFAULT_HTTP_RETRY_POLICY`.
- `CircuitBreaker` — per-key in-memory state machine: `closed → open → half_open → closed | open`. Counts consecutive failures; opens after `failure_threshold` (default 5); cooldown `cooldown_seconds` (default 30); single half-open probe before re-closing. Thread/async-safe via `asyncio.Lock` on the per-key state record. Exposes `state`, `last_error`, `opened_at`, `next_probe_at`.
- `CircuitBreakerRegistry` — `dict[str, CircuitBreaker]` keyed by backend identifier (e.g., `"http_tools:gcal"`, `"extension:gmail"`). Singleton accessor `get_circuit_breaker_registry()`.
- `CircuitBreakerOpenError(Exception)` — raised by guarded calls when the breaker is open; carries `breaker_key`, `opened_at`, `next_probe_at`, `last_error_summary` so callers can produce a degradation message.
- `@resilient_http(*, source: str, policy: RetryPolicy | None = None)` — decorator factory wrapping an `async def` returning the response. On entry: consult the breaker for `source`; if open, raise `CircuitBreakerOpenError`. Otherwise execute under tenacity retry on the policy's transient set; on terminal failure, record into the breaker; on success, reset breaker to closed.
- `HealthState(Enum)` — `OK`, `DEGRADED`, `UNAVAILABLE`, `UNKNOWN`.
- `HealthStatus` — frozen dataclass `(state: HealthState, reason: str | None, last_error: str | None, checked_at: datetime, breaker_key: str | None)`. Serializable to dict for telemetry attributes and for any future agent-facing message helper.
- `health_status_from_breaker(breaker, *, key) -> HealthStatus` — convenience for extensions whose only health signal is the runtime breaker.

### Apply at three call-sites

**1. http_tools/builder.py — per-tool invocation hot path**
- Wrap the `_coroutine` body inside `_build_tool()` with `@resilient_http(source=source_name)`. The retry layer composes **inside** the existing `wrap_http_tool(tool)` (P4) so retry attempts and breaker open/close events emit observability spans (`trace_tool_call` + a sibling `trace_event(kind="circuit_breaker_open", ...)` recorded via the existing `start_span` escape hatch — no new observability protocol method).
- Retryable: HTTP `408`, `425`, `429`, `500`, `502`, `503`, `504`, plus `httpx.ReadTimeout`, `httpx.ConnectError`, `httpx.RemoteProtocolError`, `httpx.PoolTimeout`. Non-retryable: 4xx other than the listed codes (auth, validation), and `ValueError` raised by the existing 10-MiB cap or non-JSON-content-type guards.

**2. http_tools/openapi.py — discovery `GET /openapi.json`**
- Wrap the discovery client call with `@resilient_http(source=f"http_tools_discovery:{source_name}")`. Discovery's existing graceful-skip behavior (`return None` on `HTTPError`) is preserved — but now only after retries are exhausted, so a single transient blip during startup no longer permanently drops a tool source for the session. `CircuitBreakerOpenError` from a chronically-down source is also caught at this layer and logged as the same "skip source" outcome (preserving D4).

**3. extensions/base.py — `Extension.health_check()` protocol**
- Widen the return type from `bool` to `HealthStatus`. Update all seven stub implementations (`ms_graph`, `teams`, `sharepoint`, `outlook`, `gmail`, `gcal`, `gdrive`) to return `HealthStatus(state=HealthState.UNKNOWN, reason="extension is a stub", ...)` for now — the real backend probes ship with P5/P14.
- Add a sibling default helper `default_health_status_for_unimplemented()` so stubs can return a standard "not yet wired" status with one line. Saves duplication across the seven stubs and gives a single seam for P5/P14 to override.

### Dependencies

- Add `tenacity>=9.0,<10.0` to `pyproject.toml` as a regular runtime dep (not optional). It's small (~30 KB pure Python), MIT-licensed, well-typed, and the cross-cutting nature of resilience means making it conditional creates more confusion than it saves bytes.

### Tests

- `tests/core/test_resilience.py` — `RetryPolicy` defaults, `CircuitBreaker` state-machine transitions (closed→open→half_open→closed and ←open paths), registry singleton semantics, `CircuitBreakerOpenError` payload, async lock contention smoke test.
- `tests/core/test_resilience_decorator.py` — `@resilient_http` retry behavior on each retryable status code + each retryable exception type, non-retry on terminal codes, breaker-open short-circuit, breaker recovery via half-open probe.
- `tests/http_tools/test_builder_resilience.py` — integration against a fake `httpx.AsyncClient` that returns programmable status sequences; asserts (a) retry-then-success path, (b) retry-then-fail path raises a *single* exception (not a tenacity `RetryError` chain leaking), (c) breaker opens after threshold, (d) opening the breaker does not break the existing observability span emission (`trace_tool_call` still fires).
- `tests/http_tools/test_openapi_discovery_resilience.py` — discovery now retries transient errors before falling back to "skip source"; breaker-open also yields skip-source.
- `tests/extensions/test_health_status.py` — every stub returns a well-formed `HealthStatus`; mypy via `tests/test_protocols.py` confirms the protocol widening compiles for all seven stubs.
- The four pre-existing P3 builder tests that asserted bare `HTTPStatusError` propagation get updated to assert "raised after configured retries are exhausted" — a behavioral change but one the user explicitly approved at Q4.

## Impact

### Affected specs

- **New spec**: `error-resilience` capability
- **Modified specs (hook integration clauses)**:
  - `http-tools` — adds SHALL clauses: per-tool invocation **MUST** be retried under `DEFAULT_HTTP_RETRY_POLICY`; discovery client **MUST** retry before applying the existing graceful-skip (D4) fallback; both paths **MUST** participate in the per-source circuit breaker registry
  - `extension-registry` — adds SHALL clause: extensions **MUST** return `HealthStatus` (replacing the `bool` return of `health_check()`); stubs **MUST** return `HealthState.UNKNOWN` until their backend probes are implemented
  - `observability` — adds clarifying SHALL: when a tool call is wrapped by both `wrap_http_tool` (observability) and `@resilient_http` (this change), the resilience layer **MUST** compose inside the observability wrapper so retries and breaker transitions emit spans (no double-instrumentation, no observability blind spots during retry)

### Affected code

- **New**: `src/assistant/core/resilience.py`
- **Instrumented**: `src/assistant/http_tools/builder.py`, `src/assistant/http_tools/openapi.py`
- **Protocol-widened**: `src/assistant/extensions/base.py` and all seven stub modules under `src/assistant/extensions/`
- **Modified**: `pyproject.toml` (adds `tenacity` runtime dep)

### Test impact

- **New test directories/files**: `tests/core/test_resilience.py`, `tests/core/test_resilience_decorator.py`, `tests/http_tools/test_builder_resilience.py`, `tests/http_tools/test_openapi_discovery_resilience.py`, `tests/extensions/test_health_status.py`
- **Modified**: ~4 P3 builder tests that asserted raw 5xx propagation are updated to assert "raised after configured retries"; behavior preserved at the test boundary (still fails the call), only the timing changes.

### Risk surface

- **Latency on the failure path**: with default policy (max 3 attempts, base 0.5s, exponential, jitter 0.25), worst-case retry chain is ~2.5s before terminal failure. Acceptable for an agent loop where call-level latency is already O(seconds); explicitly documented in the spec so future tuning is governed.
- **Hot-loop blast radius**: a misclassified retryable error could create a tight retry loop. Mitigated by (1) explicit allow-list of retry triggers, (2) `max_attempts` hard cap, (3) the breaker-open path which short-circuits a chronically-failing source after `failure_threshold` consecutive errors. The skill-layer circuit breaker pattern (`parallel-infrastructure/circuit_breaker.py`) was intentionally **not** reused — different lifecycle (per-skill-invocation vs long-lived process) and different scoping (package vs HTTP source).
- **Protocol break for extensions**: changing `health_check() -> bool` to `-> HealthStatus` breaks any external implementer. Inside this repo we update all seven stubs atomically. Outside this repo, only the persona submodule could in principle hold an extension — none currently do, so the impact is internal-only. Migration note in `docs/gotchas.md`.
- **CI scope**: tests under `tests/core/` and `tests/extensions/` are part of the public test suite (no submodule). The privacy guard in `tests/conftest.py` already excludes any private content; the new tests have no persona references.

## Approaches Considered

### Approach A: Decorator-based — `@resilient_http(source=...)` at each guarded call-site **(Recommended)**

`core/resilience.py` exposes a decorator that wraps an `async def` callable. Applied at three sites: per-tool coroutine in `builder.py`, discovery client call in `openapi.py`, and (eventually) extension `health_check()` probes. Tenacity for retry; in-house `CircuitBreaker` (small, ~80 LOC) for breaker; `HealthStatus` dataclass for the protocol. Composes inside `wrap_http_tool` so observability spans see every retry attempt.

- **Pros**:
  - Surgical: each guarded call-site is a single decorator line — easy to review and easy to opt-in for future P5/P14/P17 adopters.
  - Composes cleanly with the existing `wrap_http_tool` observability wrapper without modifying it.
  - Per-source circuit breaker scope (Q2) maps 1:1 to one decorator argument — no implicit derivation magic.
  - Retry + breaker policy are pure data (the `RetryPolicy` dataclass), trivially overridable per-site if a backend has unusual retry semantics.
  - Tenacity (Q1) is well-typed and async-friendly; the decorator factory adds maybe 30 lines on top of it.
  - Smallest test surface — the decorator is the only thing the resilience tests need to drive; integration tests confirm wiring.
- **Cons**:
  - Three call-site additions instead of one — but they're each one line.
  - In-house `CircuitBreaker` is one more thing to maintain than reusing an off-the-shelf library (e.g., `pybreaker`). Mitigated: tenacity already covers the hard part (retry + backoff), so the breaker is straightforwardly state-machine code (~80 LOC).
- **Effort**: M

### Approach B: Resilient client wrapper — subclass `httpx.AsyncClient` with retry/breaker built into every request

Introduce `ResilientAsyncClient(httpx.AsyncClient)` that overrides `send()` to apply retry + breaker. Replace the single shared `httpx.AsyncClient` with this subclass in the registry. No call-site changes in `builder.py` or `openapi.py`.

- **Pros**:
  - Zero touchpoints in `builder.py` / `openapi.py` once the client is swapped in.
  - Every request gets resilience whether or not the call-site author remembered to add the decorator.
- **Cons**:
  - Magic: a future maintainer reading `client.stream(...)` has no signal that retry is happening. Debug surprise during incidents.
  - Per-backend scoping is awkward: the `ResilientAsyncClient` doesn't know "which backend" — it'd have to derive that from request URL or carry per-call metadata, which contradicts Q2's "per backend / source" decision.
  - Doesn't help extensions at all — the extension protocol doesn't go through `httpx.AsyncClient`. We'd still need a parallel layer for `health_check()`.
  - Subclassing third-party clients is an upgrade-fragility pattern (httpx.AsyncClient's internals can change).
- **Effort**: M (one-shot wrapper), but reduced reuse for extensions and obscured call-sites argue against.

### Approach C: Hand-rolled retry + breaker (no tenacity dep)

Skip tenacity. Write a small `_retry_async()` helper (~20 LOC) plus the same `CircuitBreaker` from Approach A. Same call-site shape (decorator), but the retry primitive is internal.

- **Pros**:
  - No new runtime dependency.
  - Smaller import-time surface.
- **Cons**:
  - The user's Q1 answer is explicitly "tenacity (Recommended)" — proceeding with C contradicts approved guidance.
  - We rebuild backoff math, jitter, exception filtering, retry-after parsing — all of which tenacity does correctly out of the box. Net new code ~150 LOC including tests vs. ~30 LOC adapter on tenacity.
  - The roadmap explicitly names tenacity in the P9 description; deviating creates a "why didn't you use what the roadmap said" review burden.
- **Effort**: M-L (adds ~120 net new LOC + the tests for them)

### Recommendation

**Approach A**. Aligns with all four user answers (tenacity at Q1, per-backend scope at Q2, `HealthStatus` dataclass at Q3, additive test scope at Q4) and matches the "design for reuse" cross-cutting theme — future P5/P14/P17 adopters need only annotate their HTTP entry point with `@resilient_http(source=...)` and (for extensions) implement `health_check() -> HealthStatus`.

---

## Selected Approach

**Approach A — Decorator-based `@resilient_http(source=...)`** (selected at Gate 1, 2026-05-04).

Rationale:
- Aligns with the four discovery-question answers: tenacity (Q1), per-backend circuit-breaker scope (Q2), `HealthStatus` dataclass replacing `bool` (Q3), additive-test-scope (Q4).
- Smallest call-site footprint without sacrificing visibility — three decorator lines, no client-subclass magic.
- Cleanly composes inside the existing `wrap_http_tool` observability wrapper from P4, so retries and breaker transitions emit spans without rewriting the observability protocol.
- Uniform across http_tools and extensions: same `HealthStatus` type that extension `health_check()` returns is also derivable from the breaker via `health_status_from_breaker()`, so future agents can produce a single degradation-announcement format regardless of which backend layer surfaced the unavailability.

Approaches B and C are recorded above for posterity; neither is being pursued.
