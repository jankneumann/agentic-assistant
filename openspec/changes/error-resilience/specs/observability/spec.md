# observability Specification Delta

## ADDED Requirements

### Requirement: Resilience Composes Inside Tool-Call Tracing

The system SHALL ensure that retry and circuit-breaker behavior introduced by the `error-resilience` capability composes **inside** the existing observability `wrap_http_tool` wrapper at `src/assistant/telemetry/tool_wrap.py`. The composition order MUST be: outer `wrap_http_tool(...)` → inner `@resilient_http(source=...)` → innermost HTTP coroutine. This ordering guarantees:

1. Every retry attempt — including the ones that succeed silently — emits exactly one `trace_tool_call` span per attempt, so retry behavior is visible to telemetry instead of being hidden inside a single observable span.
2. A `CircuitBreakerOpenError` short-circuit emits a `trace_tool_call` span with `error="CircuitBreakerOpenError"` so dashboards see the open-breaker event distinctly from upstream HTTP failures.
3. Breaker state transitions (`closed → open`, `open → half_open`, `half_open → closed`) MAY be recorded as additional named spans via the existing `start_span(name, attributes)` escape hatch but SHALL NOT require a new first-class method on the `ObservabilityProvider` Protocol.

The `error-resilience` capability SHALL NOT introduce its own observability provider, its own logger hierarchy outside `assistant.resilience`, or its own span emission path that bypasses the established telemetry contract.

#### Scenario: Retry attempt emits one trace span per attempt

- **WHEN** an http tool wrapped by both `wrap_http_tool` and `@resilient_http` is invoked
- **AND** the underlying coroutine fails with HTTP 503 twice and succeeds on the third attempt
- **THEN** `trace_tool_call` MUST have been called exactly three times for that single tool invocation
- **AND** the first two calls MUST carry `error="HTTPStatusError"` in their metadata
- **AND** the third call MUST have `error=None`

#### Scenario: Open breaker emits trace_tool_call with breaker error

- **WHEN** the breaker for an http tool is `open` and the cooldown has not elapsed
- **AND** the wrapped tool is invoked
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the call's `error` argument MUST equal `"CircuitBreakerOpenError"`
- **AND** the underlying HTTP coroutine MUST NOT have been entered

#### Scenario: No new ObservabilityProvider Protocol method

- **WHEN** the `ObservabilityProvider` Protocol surface is inspected after the `error-resilience` change is applied
- **THEN** it MUST contain exactly the methods specified by the `observability` capability (`name`, `setup`, `trace_llm_call`, `trace_delegation`, `trace_tool_call`, `trace_memory_op`, `start_span`, `flush`, `shutdown`)
- **AND** no additional first-class methods specific to retry or circuit breaking SHALL be present
