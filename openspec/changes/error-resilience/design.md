# Design — error-resilience

## Module layout

```
src/assistant/core/resilience.py       # single file, ~250 LOC
tests/core/test_resilience.py
tests/core/test_resilience_decorator.py
tests/http_tools/test_builder_resilience.py
tests/http_tools/test_openapi_discovery_resilience.py
tests/extensions/test_health_status.py
```

The new module lives at `core/` (not `http_tools/`) because it is a generic primitive consumed by multiple subsystems (http_tools today, extensions next, P5 / P14 / P17 in the future). Living inside `http_tools/` would violate the dependency direction — extensions don't depend on http_tools.

## Decisions

### D1 — Single file (not a package)

**Decision**: ship `core/resilience.py` as a single module rather than `core/resilience/__init__.py` + sub-modules.

**Why**: the surface is small (`RetryPolicy`, `CircuitBreaker`, `CircuitBreakerRegistry`, `CircuitBreakerOpenError`, `resilient_http`, `HealthState`, `HealthStatus`, two helpers). Splitting into sub-modules at this size adds import overhead without gain. If P12 / P5 add backend-specific policies, splitting can happen then.

**Trade-off accepted**: one file slightly larger (~250 LOC) vs. easier-to-navigate package structure later. Reverse the call when the file exceeds ~500 LOC.

### D2 — In-house CircuitBreaker rather than `pybreaker`

**Decision**: implement `CircuitBreaker` ourselves in ~80 LOC rather than depend on `pybreaker` or similar.

**Why considered**: `pybreaker` is a known good library. But (a) it's sync-first; the async story is bolt-on and not type-checked. (b) Its scoping primitives don't match our `f"http_tools:{source_name}"` namespace exactly — we'd write a wrapping layer anyway. (c) The behavior is small enough that ownership > dep.

**Why rejected reuse with `.agents/skills/parallel-infrastructure/circuit_breaker.py`**: that breaker tracks per-package retry budgets in a skill-invocation lifecycle (process exits when the skill finishes). Runtime breakers must persist across many requests in a long-running agent process and account for `asyncio` concurrency. Sharing code would create a knot of shared state with subtly different semantics — clearer to keep them separate.

### D3 — Per-source breaker scope (one breaker per OpenAPI source / extension)

**Decision**: breaker key is `f"http_tools:{source_name}"` for tools, `f"http_tools_discovery:{source_name}"` for discovery, `f"extension:{name}"` for extensions. Operations within a source share a breaker.

**Why**: matches the user's Q2 answer. Operations within one backend source observe the same upstream availability, so the breaker tracks the right shared signal. Per-(source × operation) scoping would multiply state and would not be more correct in practice — when GCal returns 503 on one endpoint, the next endpoint will likely too.

**Trade-off accepted**: if a single backend has one chronically-broken endpoint among many healthy ones, all healthy endpoints stop after the breaker opens. Mitigation: that's what the user wants — a healthy backend isn't returning 503 in a tight loop on its calm endpoints. If this turns out wrong in P5/P14, override per-source via a custom breaker key passed into the decorator.

### D4 — Tenacity for retry, in-house for breaker

**Decision**: `pyproject.toml` adds `tenacity>=9.0,<10.0` as a runtime dep; the breaker is in-house.

**Why**: tenacity is the user's Q1 answer and the roadmap's P9 description. It does the hard part (composable retry / wait / stop policies, async support, jitter, exception filtering) correctly. The breaker layer wraps tenacity from the outside — tenacity sees only the function body that opted into retry; the breaker decides whether to invoke tenacity at all.

**Trade-off accepted**: one new runtime dep. ~30 KB pure Python, BSD-licensed, well-typed, transitively imported by langfuse already? No — verified independent. Net: small footprint, common Python library.

### D5 — Retry triggers explicitly enumerated, AND non-availability errors do not trip the breaker

**Decision (retry triggers)**: `RetryPolicy.retryable_status_codes = {408, 425, 429, 500, 502, 503, 504}` and `retryable_exceptions = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ConnectError, httpx.RemoteProtocolError)`. Anything else is terminal.

**Decision (breaker recording)**: only **availability failures** (errors that match `retryable_status_codes` or `retryable_exceptions`, plus `CircuitBreakerOpenError` from inner guarded calls) increment the breaker's consecutive-failure counter. A non-availability failure (e.g., HTTP 401 from one client's bad credentials, HTTP 422 from a malformed request) re-raises to the caller without affecting breaker state. **Why this matters**: without this rule, one client sending bad credentials could open the breaker for a healthy backend, blocking every other client of that backend — a denial-of-service-by-proxy. The breaker tracks **upstream availability**, not **caller correctness**.

**Why (retry triggers)**: a retry on auth failures (401) burns budget without recovery. A retry on a 400 validation error means the agent will keep replaying its own typo. Explicit triggers force the right errors onto the retry path and leave wrong errors alone. The `429` inclusion is intentional — backends use it for rate limiting and the retry-after-with-jitter behavior is exactly the right response.

**Trade-off accepted (timeouts)**: `WriteTimeout` retries on non-idempotent POST/PUT requests can result in double-create if the backend received-and-processed the body but the response was lost. We accept this for v1: bounded by `max_attempts=3` and the agent's typical workload (read-heavy tool surface). Method-aware retry policies (retry idempotent methods on all timeouts; retry non-idempotent methods only on `ConnectTimeout`) is documented as a future enhancement, not v1 scope.

**Trade-off accepted (custom backends)**: if a backend returns a non-standard status code for a transient condition, we miss it. Mitigation: `RetryPolicy` is a dataclass; per-call-site overrides add a status to the set without forking the default.

### D6 — `httpx.HTTPStatusError` re-raised, not wrapped in `RetryError`

**Decision**: on terminal retry exhaustion, the original exception (e.g., `httpx.HTTPStatusError`) is re-raised. Tests that previously asserted `HTTPStatusError` propagation continue to assert `HTTPStatusError`.

**Why**: tenacity's default is to wrap in `tenacity.RetryError` with `__cause__` chaining. That breaks `except httpx.HTTPStatusError` blocks throughout the call stack. Spec calls this out explicitly to keep the existing P3 builder tests honest after the policy change — only the **timing** of the raise changes, not the **type**.

**Implementation**: `tenacity.retry(reraise=True, ...)`.

### D7 — Stub `default_health_status_for_unimplemented(name)` helper

**Decision**: a single helper produces the standard `HealthStatus(state=UNKNOWN, reason="extension is a stub", ...)` so each of the seven stub `health_check()` methods can be one line.

**Why**: replacing seven separate `return True` statements with seven separate constructed `HealthStatus(...)` blocks would be the same line-count win in seven places — but each one a place a maintainer might forget to update when P5/P14 wires real probes. Helper is a single seam.

### D8 — `HealthStatus` carries `breaker_key`, not the breaker itself

**Decision**: `HealthStatus` holds the **string key** of the breaker (e.g., `"extension:gmail"`) instead of a reference to the `CircuitBreaker` object.

**Why**: `HealthStatus` flows through telemetry attribute payloads, possibly serialized to JSON. A live breaker reference would either fail serialization or accidentally leak runtime state into logs. The string key is sufficient for an agent or operator to look up the breaker on demand via `get_circuit_breaker_registry()[key]`.

### D9 — Composition order at the decorator boundary; per-attempt visibility via start_span

**Decision**: at `_build_tool()`, the composition is `wrap_http_tool(StructuredTool.from_function(coroutine=resilient_http(breaker_key=f"http_tools:{source_name}")(_coroutine), ...))`. Reading outside-in: observability → resilience → HTTP coroutine.

**Why this ordering**: the outer `wrap_http_tool` already emits exactly one `trace_tool_call` per outer await — that is the user-level summary span the existing `extension-registry` and `http-tools` specs require. Putting resilience inside this wrapper means the **single** `trace_tool_call` span covers the whole resilient operation (which is the right shape for cost-attribution and "did this tool call succeed?" dashboards). The resilience layer adds **per-attempt visibility** by emitting `start_span("resilience.http_attempt", ...)` events from inside its retry loop, plus `start_span("resilience.breaker_transition", ...)` events on state changes. This goes through the existing `start_span` escape hatch and does NOT require a new first-class method on the `ObservabilityProvider` Protocol.

**Why not the inverse (resilience outside observability)**: that would emit one `trace_tool_call` per attempt — three spans for one logical tool invocation. Cost-attribution would double- or triple-count. Dashboards would lose the "one tool call = one trace_tool_call" invariant. The observability layer asserts a stable user-level contract; resilience exposes its own retry timeline through the dedicated `start_span` escape hatch.

**Operational consequence for telemetry consumers**: a retry timeline shows up as one `trace_tool_call` with duration covering all attempts, plus N child `resilience.http_attempt` spans. A short-circuit shows up as one `trace_tool_call(error="CircuitBreakerOpenError")` with a child `resilience.short_circuit` span carrying breaker metadata.

### D10 — Discovery preserves the existing graceful-skip contract (D4 from P3)

**Decision**: `discovery.py` continues to return `None` on terminal failure — both retry exhaustion and breaker-open. The graceful-skip behavior is preserved exactly; only the **resilience before the skip** is new.

**Why**: P3's D4 (Source-level failure skipped with warning) is a public contract scenario in the existing http-tools spec. Breaking it would silently flip the bootstrap behavior of every persona that has ever configured a tool source. Resilience is additive: same outcome on terminal failure, just with retries before throwing in the towel.

### D11 — Hard protocol break with runtime conformance check, not a deprecation shim

**Decision**: the `health_check() -> bool` to `health_check() -> HealthStatus` change ships as a hard protocol break with **two** enforcement layers:

1. **Static (mypy)**: every internal stub is updated in this same change so `mypy src tests` catches type errors at CI time.
2. **Runtime guard at the first consumption point**: the persona registry (`src/assistant/core/persona.py` extension-loading path) MUST validate the awaited return value of `health_check()` is a `HealthStatus` instance the first time each extension is probed. On mismatch, raise `TypeError` with the extension's `name`, the actual return type, and the migration recipe (`return default_health_status_for_unimplemented(self.name)`), citing `docs/gotchas.md`.

**Why both layers**: mypy alone is insufficient because (a) `Protocol` with `@runtime_checkable` does not validate return types at runtime — only attribute existence; (b) extension instances are loaded dynamically from persona config (`importlib`-based) and the registry returns `list[Any]`, so static type checking doesn't see them; (c) out-of-tree private extensions in submodules are not part of the public mypy run. The runtime guard catches a private-submodule extension that was missed by the migration scan and surfaces a clear, actionable error instead of a confusing AttributeError later.

**Why not a deprecation shim**: (1) two valid return types in the protocol means mypy stops catching mistakes at the boundary; (2) every internal stub already gets updated in this same change; (3) out-of-tree extensions need a clear, mechanical fix — `return default_health_status_for_unimplemented(self.name)` — which is one line. Hiding that behind a deprecation makes adopters delay; an upfront error makes them act.

**Trade-off accepted**: a misbehaving private extension fails on first health-check call rather than gracefully. We prefer a clear early failure with a migration message over silent degradation.

### D12 — Sanitize and truncate error strings stored on breaker state

**Decision**: any error string flowing into `CircuitBreaker.last_error`, `CircuitBreakerOpenError.last_error_summary`, or `HealthStatus.last_error` MUST first pass through `assistant.telemetry.sanitize.sanitize` and MUST be truncated to ≤ 200 characters. The truncation MUST be lossy with a `"..."` suffix when the original string is longer.

**Why**: upstream HTTP errors stringify the response body for HTTPStatusError instances. That body can include auth tokens (in error messages from misconfigured backends), email addresses, or other user data. P4's existing observability sanitize chain at `src/assistant/telemetry/sanitize.py` solves this for span attributes — but the resilience module surfaces error strings via `CircuitBreakerOpenError.last_error_summary` (an exception attribute that gets stringified into logs via `repr()`) and `HealthStatus.last_error` (a value that may end up in a future agent prompt). Without explicit sanitization at the resilience layer, those paths bypass the existing protection. Truncation prevents disk-fill and log-injection from a verbose backend.

**Trade-off accepted**: a small import dependency from `core/resilience.py` to `telemetry/sanitize.py` (existing module). Not a circular import — `telemetry/` does not depend on `core/resilience.py`.

### D13 — Half-open admits exactly one probe; concurrent callers fail fast

**Decision**: when the breaker is `open` and the cooldown has elapsed, exactly **one** concurrent caller is admitted as the probe (transitioning the breaker to `half_open`). All other callers arriving while the probe is in flight raise `CircuitBreakerOpenError`. The breaker tracks an explicit "in-flight probe" boolean that is set when the probe enters and cleared when the probe completes (success or failure).

**Why**: without this rule, multiple concurrent tasks could each observe `state == "open"` and `now() >= next_probe_at`, each transition the breaker to `half_open`, and each issue a probe — defeating the breaker's purpose of testing the upstream **once** before re-opening the gate. The async-Lock-protected check-and-set pattern is required because Python's `asyncio` allows arbitrary task interleaving inside an `await`.

**Trade-off accepted**: a brief stall for non-probe callers (they get an immediate `CircuitBreakerOpenError`). This is the right behavior — they should not flood a probably-still-broken upstream with a thundering herd.

**Implementation note**: the in-flight-probe boolean lives inside the breaker's lock-protected state. Cleared in a `try/finally` so an unexpected exception in the wrapped coroutine does not leave the probe slot permanently held.

### D14 — Truncation uses Python str slicing (character-aware)

**Decision**: the 200-character truncation rule uses Python's standard `str[:N]` slicing, which is character-based (Unicode code points) rather than byte-based.

**Why**: byte-based truncation can split a multi-byte UTF-8 character mid-sequence, producing an invalid string. Python's native slicing on `str` operates on Unicode code points and never produces that hazard. The `"..."` suffix is appended after slicing.

**Concrete consequence**: a string with emoji or non-Latin scripts gets truncated cleanly to N code points. The byte length of the truncated string can exceed N for multi-byte content, but no resulting string will be invalid UTF-8.

### D15 — Retry-After header support deferred to a future enhancement

**Decision**: v1 of `resilient_http` uses fixed exponential backoff with jitter; it does **not** parse the `Retry-After` HTTP header that some backends return on `429 Too Many Requests` and `503 Service Unavailable`.

**Why deferred**: respecting `Retry-After` is the correct behavior eventually, but it requires (a) inspecting `response.headers` from inside the retry policy (tenacity's `wait` clauses are pure functions that don't see the response), (b) deciding what to do when the header is invalid or absurdly large (capped against `max_delay_s`?), (c) plumbing the response object through tenacity's retry-error wrapping. Each is a small problem; together they expand v1 scope. The fixed backoff is safe — it is bounded by `max_delay_s` and never violates rate limits worse than the current "no retry at all" behavior.

**Future shape**: when added, it lives behind a `RetryPolicy.respect_retry_after: bool = False` field so the v1 default behavior is preserved unless callers opt in.

## Risks not in proposal.md

### Risk: long-running process memory growth via breaker registry

The registry is `dict[str, CircuitBreaker]`. Keys accrete as new sources are seen but are never evicted. For any realistic deployment (~tens of sources per persona), this is bounded by the persona's tool source list. Worst case: the registry has 50 entries × ~200 bytes/breaker = 10 KB. Documented but not mitigated; revisit if a future phase adds dynamic source registration.

### Risk: breaker thresholds not tuned

Defaults (5 failures / 30s cooldown) are educated guesses, not measured. No production data exists to tune from. Mitigation: thresholds live on `RetryPolicy`/breaker constructor as override parameters, so a P5/P14 implementation can adjust per-backend without modifying core. Followup issue should be filed at archive time to gather measurements once real backends are wired.

### Risk: protocol break for extensions out-of-tree

Changing `health_check() -> bool` to `-> HealthStatus` is a breaking protocol change for any private-submodule extension. Internal scan: zero such extensions exist today. We log a migration note in `docs/gotchas.md`. If a private persona has an extension we don't know about, they'll get a single mypy error pointing at the protocol; the fix is mechanical (return `HealthStatus(...)`).
