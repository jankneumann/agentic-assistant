# Tasks — error-resilience

Tasks are ordered TDD-style: tests precede their implementation within each phase.

## Phase 1 — Core resilience module

- [ ] 1.1 Write `tests/core/test_resilience.py` covering `RetryPolicy` defaults / immutability, `CircuitBreaker` state-machine transitions (closed→open→half_open→closed and ←open paths), `CircuitBreakerRegistry` singleton semantics, and `CircuitBreakerOpenError` payload fields
  **Spec scenarios**: error-resilience.RetryPolicyDataType.{1,2}, error-resilience.CircuitBreakerStateMachine.{1,2,3,4}, error-resilience.CircuitBreakerRegistry.{1,2}
  **Design decisions**: D1, D2, D3, D5
  **Dependencies**: None

- [ ] 1.2 Write `tests/core/test_resilience_decorator.py` covering `@resilient_http` retry-then-success, retry-then-fail with original exception preserved, breaker short-circuit, half-open recovery, jitter range bounds
  **Spec scenarios**: error-resilience.ResilientDecorator.{1,2,3,4}
  **Design decisions**: D4, D5, D6
  **Dependencies**: 1.1

- [ ] 1.3 Add `tenacity>=9.0,<10.0` to `pyproject.toml` under `[project] dependencies`; run `uv sync` and verify lockfile updates atomically (no extras change)
  **Design decisions**: D4
  **Dependencies**: None

- [ ] 1.4 Implement `src/assistant/core/resilience.py`: `RetryPolicy` (frozen dataclass), `DEFAULT_HTTP_RETRY_POLICY`, `CircuitBreaker` with `asyncio.Lock`, `CircuitBreakerRegistry` singleton, `CircuitBreakerOpenError`, `resilient_http(*, source, policy=None)` decorator with `tenacity.retry(reraise=True, ...)`, `HealthState` enum, `HealthStatus` dataclass, `health_status_from_breaker(...)`, `default_health_status_for_unimplemented(...)`
  **Spec scenarios**: all of error-resilience.*
  **Design decisions**: D1, D2, D5, D6, D7, D8
  **Dependencies**: 1.1, 1.2, 1.3

- [ ] 1.5 Run `uv run pytest tests/core/test_resilience.py tests/core/test_resilience_decorator.py` — all pass
  **Dependencies**: 1.4

## Phase 2 — Apply at http_tools call sites

- [ ] 2.1 Write `tests/http_tools/test_builder_resilience.py` covering retry-then-success with payload returned, retry-exhausted with original `httpx.HTTPStatusError` raised (not `RetryError`), breaker-open short-circuit, observability span emitted per retry attempt
  **Spec scenarios**: http-tools.HttpToolInvocationsAreResilient.{1,2,3,4}, observability.ResilienceComposesInsideToolCallTracing.{1,2}
  **Design decisions**: D6, D9
  **Dependencies**: 1.5

- [ ] 2.2 Write `tests/http_tools/test_openapi_discovery_resilience.py` covering retry-then-success path adds source to registry, retry-exhausted causes graceful skip preserving D10, breaker-open also yields skip
  **Spec scenarios**: http-tools.DiscoveryRetriesBeforeSkip.{1,2,3}
  **Design decisions**: D10
  **Dependencies**: 1.5

- [ ] 2.3 Modify `src/assistant/http_tools/builder.py` `_build_tool()` to wrap the inner `_coroutine` with `@resilient_http(source=source_name)` BEFORE passing to `StructuredTool.from_function(...)` and BEFORE the outer `wrap_http_tool(...)` call, preserving the composition order specified in design D9
  **Spec scenarios**: http-tools.HttpToolInvocationsAreResilient.{1,2,3,4}
  **Design decisions**: D9
  **Dependencies**: 2.1

- [ ] 2.4 Modify `src/assistant/http_tools/openapi.py` (or wherever `discover_tools` issues the OpenAPI fetch) to wrap the discovery client call with `@resilient_http(source=f"http_tools_discovery:{source_name}")`; catch `CircuitBreakerOpenError` at the discover-source loop and treat as the existing graceful-skip outcome (warning + omission)
  **Spec scenarios**: http-tools.DiscoveryRetriesBeforeSkip.{1,2,3}
  **Design decisions**: D10
  **Dependencies**: 2.2

- [ ] 2.5 Update the four pre-existing P3 builder tests that assert raw `HTTPStatusError` propagation: change wording to "after configured retries exhausted" but keep the same exception assertion (D6 ensures the original exception type is what's raised)
  **Dependencies**: 2.3

- [ ] 2.6 Run `uv run pytest tests/http_tools/` — all pass (new + updated)
  **Dependencies**: 2.3, 2.4, 2.5

## Phase 3 — Widen Extension protocol to HealthStatus

- [ ] 3.1 Write `tests/extensions/test_health_status.py` asserting (a) every stub returns a `HealthStatus` instance from `await ext.health_check()`, (b) `state=HealthState.UNKNOWN` and `reason="extension is a stub"`, (c) `Extension.health_check.__annotations__["return"]` resolves to `HealthStatus` under typing introspection
  **Spec scenarios**: extension-registry.ExtensionHealthCheckReturnsHealthStatus.{1,2,3}, extension-registry.StubImplementations.StubHealthCheckReturnsUNKNOWN
  **Design decisions**: D7
  **Dependencies**: 1.5

- [ ] 3.2 Modify `src/assistant/extensions/base.py`: change `Extension.health_check` return annotation from `bool` to `HealthStatus` (importing from `assistant.core.resilience`)
  **Spec scenarios**: extension-registry.ExtensionHealthCheckReturnsHealthStatus.1
  **Dependencies**: 3.1

- [ ] 3.3 Modify all seven stub modules (`src/assistant/extensions/{ms_graph,teams,sharepoint,outlook,gmail,gcal,gdrive}.py`) to return `default_health_status_for_unimplemented(<name>)` from their `health_check()` method. If a shared stub base in `extensions/_stub.py` exists, update it once; otherwise update each module
  **Spec scenarios**: extension-registry.StubImplementations.StubHealthCheckReturnsUNKNOWN
  **Design decisions**: D7
  **Dependencies**: 3.1, 3.2

- [ ] 3.4 Run `uv run pytest tests/extensions/` and `uv run mypy src tests` — all pass; mypy must not flag any extension stub as a Protocol mismatch
  **Dependencies**: 3.3

## Phase 4 — Cross-cutting integration & validation

- [ ] 4.1 Run full suite `uv run pytest tests/` — all pass
  **Dependencies**: 1.5, 2.6, 3.4

- [ ] 4.2 Run `uv run ruff check src tests` — no violations
  **Dependencies**: 4.1

- [ ] 4.3 Run `uv run mypy src tests` — no errors (matches CI scope per CLAUDE.md G8)
  **Dependencies**: 4.1

- [ ] 4.4 Run `openspec validate error-resilience --strict` — passes
  **Dependencies**: All phases

- [ ] 4.5 Update `openspec/roadmap.md` row P9 status from `pending` to `in-progress` (will flip to `archived` at archive time)
  **Dependencies**: None (pre-PR doc update)

- [ ] 4.6 Update `docs/gotchas.md` with a migration note for any out-of-tree extension adopters: `health_check() -> bool` is now `-> HealthStatus`; one-line fix is `return default_health_status_for_unimplemented(self.name)`
  **Design decisions**: D11 (gotchas-table addition)
  **Dependencies**: 3.3
