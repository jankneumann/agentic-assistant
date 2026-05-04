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

### D5 — Retry triggers explicitly enumerated, not "any failure"

**Decision**: `RetryPolicy.retryable_status_codes = {408, 425, 429, 500, 502, 503, 504}` and `retryable_exceptions = (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError, httpx.PoolTimeout)`. Anything else is terminal.

**Why**: a retry on auth failures (401) burns budget without recovery. A retry on a 400 validation error means the agent will keep replaying its own typo. Explicit triggers force the right errors onto the retry path and leave wrong errors alone. The `429` inclusion is intentional — backends use it for rate limiting and the retry-after-with-jitter behavior is exactly the right response.

**Trade-off accepted**: if a backend returns a non-standard status code for a transient condition, we miss it. Mitigation: `RetryPolicy` is a dataclass; per-call-site overrides add a status to the set without forking the default.

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

### D9 — Composition order at the decorator boundary

**Decision**: at `_build_tool()`, the composition is `wrap_http_tool(StructuredTool.from_function(coroutine=resilient_http(...)(_coroutine), ...))`. Reading outside-in: observability → resilience → HTTP coroutine.

**Why**: putting resilience inside observability means each retry attempt emits its own `trace_tool_call` span, so the timeline shows attempts. Putting observability inside resilience would emit a single span for the whole decorated call — retries would be invisible. The roadmap's "Observability" cross-cutting theme means we never want the resilience layer to silently swallow span counts.

### D10 — Discovery preserves the existing graceful-skip contract (D4 from P3)

**Decision**: `discovery.py` continues to return `None` on terminal failure — both retry exhaustion and breaker-open. The graceful-skip behavior is preserved exactly; only the **resilience before the skip** is new.

**Why**: P3's D4 (Source-level failure skipped with warning) is a public contract scenario in the existing http-tools spec. Breaking it would silently flip the bootstrap behavior of every persona that has ever configured a tool source. Resilience is additive: same outcome on terminal failure, just with retries before throwing in the towel.

## Risks not in proposal.md

### Risk: long-running process memory growth via breaker registry

The registry is `dict[str, CircuitBreaker]`. Keys accrete as new sources are seen but are never evicted. For any realistic deployment (~tens of sources per persona), this is bounded by the persona's tool source list. Worst case: the registry has 50 entries × ~200 bytes/breaker = 10 KB. Documented but not mitigated; revisit if a future phase adds dynamic source registration.

### Risk: breaker thresholds not tuned

Defaults (5 failures / 30s cooldown) are educated guesses, not measured. No production data exists to tune from. Mitigation: thresholds live on `RetryPolicy`/breaker constructor as override parameters, so a P5/P14 implementation can adjust per-backend without modifying core. Followup issue should be filed at archive time to gather measurements once real backends are wired.

### Risk: protocol break for extensions out-of-tree

Changing `health_check() -> bool` to `-> HealthStatus` is a breaking protocol change for any private-submodule extension. Internal scan: zero such extensions exist today. We log a migration note in `docs/gotchas.md`. If a private persona has an extension we don't know about, they'll get a single mypy error pointing at the protocol; the fix is mechanical (return `HealthStatus(...)`).
