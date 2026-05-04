# Tasks — error-resilience

Tasks are ordered TDD-style: tests precede their implementation within each phase.

## Phase 1 — Core resilience module

- [x] 1.1 Write `tests/core/test_resilience.py` covering `RetryPolicy` defaults / immutability, `CircuitBreaker` state-machine transitions (closed→open→half_open→closed and ←open paths), `CircuitBreakerRegistry` singleton semantics, `CircuitBreakerOpenError` payload fields, and the sanitization + 200-char truncation contract for error strings stored on the breaker
  **Spec scenarios**: error-resilience.RetryPolicyDataType.{1,2}, error-resilience.CircuitBreakerStateMachine.{1,2,3,4}, error-resilience.CircuitBreakerRegistry.{1,2}, error-resilience.ErrorStringsAreSanitizedAndTruncated.{1,2,3}
  **Design decisions**: D1, D2, D3, D5, D12
  **Dependencies**: None

- [x] 1.2 Write `tests/core/test_resilience_decorator.py` covering `resilient_http(breaker_key=...)` retry-then-success, retry-then-fail with original exception preserved, breaker short-circuit, half-open recovery (single-probe semantics under concurrent callers), jitter range bounds, 429 retry-with-backoff, asyncio-non-blocking retry delay, WriteTimeout retried, **non-availability error (401) does NOT trip breaker**, and per-attempt + breaker-transition `start_span` emission
  **Spec scenarios**: error-resilience.ResilientDecorator.{1,2,3,4,5,6,7}, error-resilience.CircuitBreakerStateMachine.NonAvailabilityFailure, error-resilience.CircuitBreakerStateMachine.HalfOpenAdmitsExactlyOneProbe, observability.ResilienceComposesWithToolCallTracing.{1,2,3}
  **Design decisions**: D4, D5, D6, D9, D13
  **Dependencies**: 1.1

- [x] 1.3 Add `tenacity>=9.0,<10.0` to `pyproject.toml` under `[project] dependencies`; run `uv sync` and verify lockfile updates atomically (no extras change)
  **Design decisions**: D4
  **Dependencies**: None

- [x] 1.4 Implement `src/assistant/core/resilience.py`: `RetryPolicy` (frozen dataclass with `httpx.ConnectTimeout`/`ReadTimeout`/`WriteTimeout`/`PoolTimeout`/`ConnectError`/`RemoteProtocolError` retryable defaults), `DEFAULT_HTTP_RETRY_POLICY`, `CircuitBreaker` with `asyncio.Lock`, in-flight-probe tracking (D13), char-aware truncation + sanitize for `last_error` (D12, D14), availability-vs-non-availability classification on failure (D5), `CircuitBreakerRegistry` singleton, `CircuitBreakerOpenError` (with sanitized `last_error_summary`), `resilient_http(*, breaker_key, policy=None)` decorator with `tenacity.retry(reraise=True, ...)` and per-attempt + per-state-transition `start_span` emission (D9), `HealthState` enum, `HealthStatus` dataclass (with sanitized `last_error`), `health_status_from_breaker(...)`, `default_health_status_for_unimplemented(...)`
  **Spec scenarios**: all of error-resilience.*
  **Design decisions**: D1, D2, D5, D6, D7, D8, D9, D12, D13, D14
  **Dependencies**: 1.1, 1.2, 1.3

- [x] 1.5 Run `uv run pytest tests/core/test_resilience.py tests/core/test_resilience_decorator.py` — all pass
  **Dependencies**: 1.4

## Phase 2 — Apply at http_tools call sites

- [x] 2.1 Write `tests/http_tools/test_builder_resilience.py` covering retry-then-success with payload returned, retry-exhausted with original `httpx.HTTPStatusError` raised (not `RetryError`), breaker-open short-circuit, observability span emitted per retry attempt
  **Spec scenarios**: http-tools.HttpToolInvocationsAreResilient.{1,2,3,4}, observability.ResilienceComposesInsideToolCallTracing.{1,2}
  **Design decisions**: D6, D9
  **Dependencies**: 1.5

- [x] 2.2 Write `tests/http_tools/test_openapi_discovery_resilience.py` covering retry-then-success path adds source to registry, retry-exhausted causes graceful skip preserving D10, breaker-open also yields skip
  **Spec scenarios**: http-tools.DiscoveryRetriesBeforeSkip.{1,2,3}
  **Design decisions**: D10
  **Dependencies**: 1.5

- [x] 2.3 Modify `src/assistant/http_tools/builder.py` `_build_tool()` to wrap the inner `_coroutine` with `resilient_http(breaker_key=f"http_tools:{source_name}")` BEFORE passing to `StructuredTool.from_function(...)` and BEFORE the outer `wrap_http_tool(...)` call, preserving the composition order specified in design D9 (note: pass the canonical fully-namespaced key explicitly — no implicit prefixing)
  **Spec scenarios**: http-tools.HttpToolInvocationsAreResilient.{1,2,3,4}
  **Design decisions**: D9
  **Dependencies**: 2.1

- [x] 2.4 Modify `src/assistant/http_tools/discovery.py::_fetch_openapi` (line 27) to wrap the function body with `resilient_http(breaker_key=f"http_tools_discovery:{source_name}")`; catch `CircuitBreakerOpenError` in the `_discover_one`/`discover_tools` loop and treat as the existing graceful-skip outcome (warning + omission). Note: the wrapping target is `discovery.py` (where the network fetch lives), NOT `openapi.py` (which only does parsing).
  **Spec scenarios**: http-tools.DiscoveryRetriesBeforeSkip.{1,2,3}
  **Design decisions**: D10
  **Dependencies**: 2.2

- [x] 2.5 Update the four pre-existing P3 builder tests that assert raw `HTTPStatusError` propagation: change wording to "after configured retries exhausted" but keep the same exception assertion (D6 ensures the original exception type is what's raised)
  **Dependencies**: 2.3

- [x] 2.6 Run `uv run pytest tests/http_tools/` — all pass (new + updated)
  **Dependencies**: 2.3, 2.4, 2.5

## Phase 3 — Widen Extension protocol to HealthStatus

- [x] 3.1 Write `tests/extensions/test_health_status.py` asserting (a) every stub returns a `HealthStatus` instance from `await ext.health_check()`, (b) `state=HealthState.UNKNOWN` and `reason="extension is a stub"`, (c) `Extension.health_check.__annotations__["return"]` resolves to `HealthStatus` under typing introspection, (d) the runtime-conformance check raises `TypeError` with a migration message when an extension returns `True` instead of `HealthStatus`
  **Spec scenarios**: extension-registry.ExtensionHealthCheckReturnsHealthStatus.{1,2,3,4}, extension-registry.StubImplementations.StubHealthCheckReturnsUNKNOWN
  **Design decisions**: D7, D11
  **Dependencies**: 1.5

- [x] 3.2 Modify `src/assistant/extensions/base.py`: change `Extension.health_check` return annotation from `bool` to `HealthStatus` (importing from `assistant.core.resilience`)
  **Spec scenarios**: extension-registry.ExtensionHealthCheckReturnsHealthStatus.1
  **Dependencies**: 3.1

- [x] 3.3 Modify all seven stub modules (`src/assistant/extensions/{ms_graph,teams,sharepoint,outlook,gmail,gcal,gdrive}.py`) to return `default_health_status_for_unimplemented(<name>)` from their `health_check()` method. If a shared stub base in `extensions/_stub.py` exists, update it once; otherwise update each module
  **Spec scenarios**: extension-registry.StubImplementations.StubHealthCheckReturnsUNKNOWN
  **Design decisions**: D7
  **Dependencies**: 3.1, 3.2

- [x] 3.5 Add runtime-conformance check in `src/assistant/core/persona.py` extension-loading path: validate `await ext.health_check()` returns a `HealthStatus` instance the first time each extension is probed; on mismatch raise `TypeError` naming the extension, the actual return type, and the migration recipe (`return default_health_status_for_unimplemented(self.name)`) with a citation to `docs/gotchas.md`
  **Spec scenarios**: extension-registry.ExtensionHealthCheckReturnsHealthStatus.4
  **Design decisions**: D11
  **Dependencies**: 3.2, 3.3

- [x] 3.4 Run `uv run pytest tests/extensions/` and `uv run mypy src tests` — all pass; mypy must not flag any extension stub as a Protocol mismatch
  **Dependencies**: 3.3

## Phase 4 — Cross-cutting integration & validation

- [x] 4.1 Run full suite `uv run pytest tests/` — all pass
  **Dependencies**: 1.5, 2.6, 3.4

- [x] 4.2 Run `uv run ruff check src tests` — no violations
  **Dependencies**: 4.1

- [x] 4.3 Run `uv run mypy src tests` — no errors (matches CI scope per CLAUDE.md G8)
  **Dependencies**: 4.1

- [x] 4.4 Run `openspec validate error-resilience --strict` — passes
  **Dependencies**: All phases

- [x] 4.5 Update `openspec/roadmap.md` row P9 status from `pending` to `in-progress` (will flip to `archived` at archive time)
  **Dependencies**: None (pre-PR doc update)

- [x] 4.6 Update `docs/gotchas.md` with a migration note for any out-of-tree extension adopters: `health_check() -> bool` is now `-> HealthStatus`; one-line fix is `return default_health_status_for_unimplemented(self.name)`
  **Design decisions**: D11 (hard protocol break + doc-note migration recipe instead of deprecation shim)
  **Dependencies**: 3.3
