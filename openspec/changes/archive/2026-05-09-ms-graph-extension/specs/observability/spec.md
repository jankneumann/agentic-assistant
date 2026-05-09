## MODIFIED Requirements

### Requirement: Observability Provider Contract

The system SHALL define an `ObservabilityProvider` Protocol at `src/assistant/telemetry/providers/base.py` that every concrete provider (`noop`, `langfuse`, and any future adapter) MUST implement. The Protocol SHALL expose exactly these methods:

- `name` property returning the provider's registered string identifier.
- `setup(app=None)` called once during app startup to perform lazy provider initialization.
- `trace_llm_call(*, model, persona, role, messages, input_tokens, output_tokens, duration_ms, metadata=None)` recording a harness invocation as an LLM call.
- `trace_delegation(*, parent_role, sub_role, task, persona, duration_ms, outcome, metadata=None)` recording a delegation hop.
- `trace_tool_call(*, tool_name, tool_kind, persona, role, duration_ms, error=None, metadata=None)` recording any LangChain StructuredTool or HTTP-discovered tool invocation. The `tool_kind` parameter MUST be one of `"extension"`, `"http"`, or `"graph"`.
- `trace_graph_call(*, extension_name, method, path, status_code, duration_ms, breaker_key, request_id=None, retry_attempt=0, bytes_streamed=None, error=None, metadata=None)` recording a single outbound HTTP request to a Microsoft Graph endpoint (or any `CloudGraphClient`-shaped backend in P14+). The `method` parameter MUST be one of `"GET"`, `"POST"`, `"PUT"`, `"PATCH"`, `"DELETE"`. The `path` parameter MUST be the request path with sensitive ID values redacted to placeholders (e.g., `/users/<user_id>/messages/<message_id>`). The `breaker_key` parameter is the P9 circuit breaker key (e.g., `"graph:ms_graph"`) and is included so spans can be correlated with breaker state events. The `request_id` parameter is the Microsoft Graph `request-id` response header value, included for correlation with Entra ID and Graph audit logs. The `retry_attempt` parameter is the zero-indexed retry count (0 = original attempt). The `bytes_streamed` parameter is non-None only for `get_bytes` invocations and carries the cumulative byte count read from the streamed body (used by ops dashboards to flag large-download patterns). On failure, `error` MUST be the exception class name (e.g., `"GraphAPIError"`).
- `trace_extension_init(*, extension_name, persona, success, duration_ms, error=None)` recording extension construction.
- `trace_memory_op(*, op, target, persona, duration_ms, metadata=None)` recording any `MemoryManager` method call. The `op` parameter MUST be one of `"context"`, `"fact_write"`, `"interaction_write"`, `"episode_write"`, `"search"`, or `"export"` — each corresponding to a `MemoryManager` method on `src/assistant/core/memory.py`.
- `start_span(name, attributes=None)` returning a context manager for arbitrary named spans that do not fit any first-class method.
- `set_metadata(*, key, value)` recording metadata on the current trace.
- `flush()` triggering an immediate send of buffered events.
- `shutdown()` called during process exit to drain buffers and release resources.

The Protocol SHALL be decorated with `@runtime_checkable` so `isinstance(obj, ObservabilityProvider)` checks work at runtime.

#### Scenario: Noop implements the full Protocol surface

- **WHEN** `isinstance(NoopProvider(), ObservabilityProvider)` is evaluated
- **THEN** the result MUST be `True`
- **AND** every method listed above MUST be callable with valid arguments without raising

#### Scenario: Langfuse implements the full Protocol surface

- **WHEN** `isinstance(LangfuseProvider(), ObservabilityProvider)` is evaluated
- **THEN** the result MUST be `True`
- **AND** every Protocol method MUST be present on the instance

#### Scenario: Rejects mis-typed tool_kind

- **WHEN** `trace_tool_call(tool_kind="database", ...)` is invoked on any provider
- **THEN** a `ValueError` MUST be raised identifying the invalid `tool_kind`
- **AND** no span SHALL be emitted

#### Scenario: Rejects mis-typed op value

- **WHEN** `trace_memory_op(op="CONTEXT", ...)` is invoked on any provider (any value outside the fixed set `{"context", "fact_write", "interaction_write", "episode_write", "search", "export"}`, including wrong-case variants)
- **THEN** a `ValueError` MUST be raised identifying the invalid `op`
- **AND** no span SHALL be emitted

#### Scenario: NoopProvider implements trace_graph_call

- **WHEN** `NoopProvider().trace_graph_call(extension_name="ms_graph", method="GET", path="/me", status_code=200, duration_ms=42.0, breaker_key="graph:ms_graph")` is invoked
- **THEN** the call MUST return `None`
- **AND** the call MUST NOT raise

#### Scenario: LangfuseProvider implements trace_graph_call

- **WHEN** `LangfuseProvider().trace_graph_call(extension_name="ms_graph", method="GET", path="/me/messages", status_code=200, duration_ms=120.0, breaker_key="graph:ms_graph", request_id="abc-123", retry_attempt=0)` is invoked with Langfuse client mocked
- **THEN** the provider MUST emit one Langfuse trace span with `name="graph_call"` (or equivalent) carrying all kwargs as attributes
- **AND** the span attribute `tool_kind` MUST equal `"graph"` so existing dashboards filtering on `tool_kind` continue to work

#### Scenario: trace_graph_call records error class on failure

- **WHEN** `provider.trace_graph_call(..., error="GraphAPIError")` is invoked
- **THEN** the recorded span MUST carry the error class name as an attribute
- **AND** subsequent retries MUST emit additional `trace_graph_call` invocations with incremented `retry_attempt`

### Requirement: Resilience Composes With Tool-Call Tracing

The system SHALL ensure that retry and circuit-breaker behavior introduced by the `error-resilience` capability composes with both observability paths:

- The outer `wrap_http_tool` wrapper at `src/assistant/telemetry/tool_wrap.py` for HTTP tools (one trace per user-level invocation).
- The new `trace_graph_call` first-class method for Graph HTTP requests (one trace per HTTP attempt).

**Composition order for HTTP tools**: outer `wrap_http_tool(...)` → inner `resilient_http(breaker_key=...)` → innermost HTTP coroutine.

**Composition order for Graph calls**: outer `resilient_http(breaker_key=...)` → inner per-request `trace_graph_call` → innermost httpx call.

**Span emission contract for HTTP tools**:

1. **One `trace_tool_call` per user-level tool invocation.** `wrap_http_tool` continues to emit exactly one `trace_tool_call` span per outer await — covering the whole resilient operation including retries. This preserves the existing `extension-registry` and `http-tools` "one trace per tool invocation" contract.
2. **Per-attempt visibility via `start_span`.** `resilient_http` MUST emit one `start_span` event per retry attempt (named `"resilience.http_attempt"`) with attributes `breaker_key`, `attempt_number`, `delay_before_attempt_s`, and on failure `error_type`. This makes silent retries visible to the telemetry timeline.
3. **Per-state-transition visibility via `start_span`.** Circuit-breaker state transitions (`closed → open`, `open → half_open`, `half_open → closed`, `half_open → open`) MUST emit a `start_span` event named `"resilience.breaker_transition"` with attributes `breaker_key`, `from_state`, `to_state`, and `last_error_summary` (sanitized).
4. **`CircuitBreakerOpenError` is a tool-call outcome.** When `resilient_http` short-circuits with `CircuitBreakerOpenError`, the outer `wrap_http_tool` MUST emit `trace_tool_call` with `error="CircuitBreakerOpenError"` and a `start_span` event named `"resilience.short_circuit"` carrying `breaker_key`, `opened_at`, and `next_probe_at` attributes — so dashboards see the open-breaker event distinctly from upstream HTTP failures.

**Span emission contract for Graph calls**:

5. **One `trace_graph_call` per HTTP attempt.** For Graph HTTP calls wrapped by `@resilient_http`, exactly one `trace_graph_call` span MUST be emitted per HTTP attempt (not per user-level operation), and the `retry_attempt` field on each span MUST monotonically increase across retries of a single user-level operation.
6. **Per-attempt `start_span` continues for Graph paths.** The `error-resilience` capability's existing `start_span("resilience.http_attempt", ...)` events MUST continue to be emitted for retries on the Graph path — these provide retry-loop visibility independently of `trace_graph_call`, which provides per-HTTP-request visibility.
7. **Open breaker on Graph path emits `start_span` only.** When the breaker for `"graph:<extension>"` is open, no `trace_graph_call` MUST be emitted (the request never reached httpx); the existing `start_span("resilience.short_circuit", ...)` event MUST be emitted instead.

The `error-resilience` capability MUST NOT introduce its own observability provider, its own logger hierarchy outside `assistant.resilience`, or its own span emission path that bypasses the established telemetry contract. Per-attempt and per-state-transition spans MUST go through the existing `ObservabilityProvider.start_span(...)` escape hatch. The `trace_graph_call` first-class method coexists with `start_span` for Graph paths to provide both per-request and per-retry-attempt visibility.

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

#### Scenario: Successful Graph retry emits one trace_graph_call per attempt

- **WHEN** `GraphClient.get("/me")` is awaited
- **AND** the first attempt fails with HTTP 503 and the second attempt succeeds with HTTP 200
- **THEN** `trace_graph_call` MUST be called exactly twice
- **AND** the first call MUST have `status_code=503, retry_attempt=0, error="GraphAPIError"` (or the appropriate transient error class)
- **AND** the second call MUST have `status_code=200, retry_attempt=1, error=None`

#### Scenario: Open breaker emits no trace_graph_call

- **WHEN** the breaker for `"graph:ms_graph"` is OPEN
- **AND** `GraphClient.get("/me")` is awaited
- **THEN** `trace_graph_call` MUST NOT be called (the request never reached httpx)
- **AND** the existing `start_span("resilience.short_circuit", ...)` event MUST be emitted instead

#### Scenario: Protocol surface includes both legacy and graph methods

- **WHEN** the `ObservabilityProvider` Protocol surface is inspected after the `error-resilience` and `ms-graph-extension` changes are applied
- **THEN** it MUST contain at minimum the methods specified by the `observability` capability (`name`, `setup`, `trace_llm_call`, `trace_delegation`, `trace_tool_call`, `trace_memory_op`, `start_span`, `flush`, `shutdown`) plus the Graph-specific additions (`trace_graph_call`, `trace_extension_init`, `set_metadata`)
- **AND** retry and circuit-breaking specifics MUST continue to be expressed via the `start_span` escape hatch rather than additional first-class retry methods
