# observability Specification Delta

## ADDED Requirements

### Requirement: Resilience Composes With Tool-Call Tracing

The system SHALL ensure that retry and circuit-breaker behavior introduced by the `error-resilience` capability composes with the existing observability `wrap_http_tool` wrapper at `src/assistant/telemetry/tool_wrap.py` without adding any first-class method to the `ObservabilityProvider` Protocol.

**Composition order**: outer `wrap_http_tool(...)` → inner `resilient_http(breaker_key=...)` → innermost HTTP coroutine.

**Span emission contract**:

1. **One `trace_tool_call` per user-level tool invocation.** `wrap_http_tool` continues to emit exactly one `trace_tool_call` span per outer await — covering the whole resilient operation including retries. This preserves the existing `extension-registry` and `http-tools` "one trace per tool invocation" contract.
2. **Per-attempt visibility via `start_span`.** `resilient_http` MUST emit one `start_span` event per retry attempt (named `"resilience.http_attempt"`) with attributes `breaker_key`, `attempt_number`, `delay_before_attempt_s`, and on failure `error_type`. This makes silent retries visible to the telemetry timeline without changing the `ObservabilityProvider` Protocol surface.
3. **Per-state-transition visibility via `start_span`.** Circuit-breaker state transitions (`closed → open`, `open → half_open`, `half_open → closed`, `half_open → open`) MUST emit a `start_span` event named `"resilience.breaker_transition"` with attributes `breaker_key`, `from_state`, `to_state`, and `last_error_summary` (sanitized).
4. **`CircuitBreakerOpenError` is a tool-call outcome.** When `resilient_http` short-circuits with `CircuitBreakerOpenError`, the outer `wrap_http_tool` MUST emit `trace_tool_call` with `error="CircuitBreakerOpenError"` and a `start_span` event named `"resilience.short_circuit"` carrying `breaker_key`, `opened_at`, and `next_probe_at` attributes — so dashboards see the open-breaker event distinctly from upstream HTTP failures.

The `error-resilience` capability MUST NOT introduce its own observability provider, its own logger hierarchy outside `assistant.resilience`, or its own span emission path that bypasses the established telemetry contract. Per-attempt and per-state-transition spans MUST go through the existing `ObservabilityProvider.start_span(...)` escape hatch.

#### Scenario: Successful retry emits one trace_tool_call plus per-attempt spans

- **WHEN** an http tool wrapped by both `wrap_http_tool` and `resilient_http` is invoked
- **AND** the underlying coroutine fails with HTTP 503 twice and succeeds on the third attempt
- **THEN** `trace_tool_call` MUST have been called **exactly once** for the user-level invocation
- **AND** the `trace_tool_call` `error` argument MUST be `None` (the call ultimately succeeded)
- **AND** **three** `start_span("resilience.http_attempt", ...)` events MUST have been emitted (one per attempt)
- **AND** the first two attempt spans MUST carry `error_type="HTTPStatusError"` in their attributes
- **AND** the third attempt span MUST have no `error_type` attribute

#### Scenario: Open breaker emits trace_tool_call plus short-circuit span

- **WHEN** the breaker for an http tool is `open` and the cooldown has not elapsed
- **AND** the wrapped tool is invoked
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the `trace_tool_call` `error` argument MUST equal `"CircuitBreakerOpenError"`
- **AND** a `start_span("resilience.short_circuit", ...)` event MUST have been emitted with attributes including the canonical `breaker_key`
- **AND** the underlying HTTP coroutine MUST NOT have been entered

#### Scenario: Breaker transition emits start_span event

- **WHEN** the breaker transitions from `closed` to `open` because a third consecutive availability failure was recorded
- **THEN** a `start_span("resilience.breaker_transition", ...)` event MUST have been emitted
- **AND** the event attributes MUST include `from_state="closed"`, `to_state="open"`, and the canonical `breaker_key`
- **AND** any `last_error_summary` attribute on the event MUST already be sanitized per the "Error Strings Are Sanitized And Truncated" requirement

#### Scenario: No new ObservabilityProvider Protocol method

- **WHEN** the `ObservabilityProvider` Protocol surface is inspected after the `error-resilience` change is applied
- **THEN** it MUST contain exactly the methods specified by the `observability` capability (`name`, `setup`, `trace_llm_call`, `trace_delegation`, `trace_tool_call`, `trace_memory_op`, `start_span`, `flush`, `shutdown`)
- **AND** no additional first-class methods specific to retry or circuit breaking SHALL be present
