## MODIFIED Requirements

### Requirement: ObservabilityProvider Protocol

The system SHALL define an `ObservabilityProvider` Protocol at `src/assistant/telemetry/providers/base.py` that every concrete provider (`noop`, `langfuse`, and any future adapter) MUST implement. The Protocol SHALL expose exactly these methods:

- `trace_llm_call(*, model, persona, role, messages, input_tokens, output_tokens, duration_ms, metadata=None)` recording a harness invocation as an LLM call.
- `trace_tool_call(*, tool_name, tool_kind, persona, role, duration_ms, error=None, metadata=None)` recording any LangChain StructuredTool or HTTP-discovered tool invocation. The `tool_kind` parameter MUST be one of `"extension"`, `"http"`, or `"graph"`.
- `trace_graph_call(*, extension_name, method, path, status_code, duration_ms, breaker_key, request_id=None, retry_attempt=0, bytes_streamed=None, error=None, metadata=None)` recording a single outbound HTTP request to a Microsoft Graph endpoint (or any `CloudGraphClient`-shaped backend in P14+). The `method` parameter MUST be one of `"GET"`, `"POST"`, `"PUT"`, `"PATCH"`, `"DELETE"`. The `path` parameter MUST be the request path with sensitive ID values redacted to placeholders (e.g., `/users/<user_id>/messages/<message_id>`). The `breaker_key` parameter is the P9 circuit breaker key (e.g., `"graph:ms_graph"`) and is included so spans can be correlated with breaker state events. The `request_id` parameter is the Microsoft Graph `request-id` response header value, included for correlation with Entra ID and Graph audit logs. The `retry_attempt` parameter is the zero-indexed retry count (0 = original attempt). The `bytes_streamed` parameter is non-None only for `get_bytes` invocations and carries the cumulative byte count read from the streamed body (used by ops dashboards to flag large-download patterns). On failure, `error` MUST be the exception class name (e.g., `"GraphAPIError"`).
- `trace_extension_init(*, extension_name, persona, success, duration_ms, error=None)` recording extension construction.
- `start_span(name, *, attributes=None)` returning a context-manager span for arbitrary scoped instrumentation (used by `error-resilience` per-attempt visibility per the existing `Resilience-Observability Composition` requirement).
- `set_metadata(*, key, value)` recording metadata on the current trace.
- `flush()` flushing any buffered spans.

The Protocol SHALL be decorated with `@runtime_checkable` so `isinstance(obj, ObservabilityProvider)` checks work at runtime.

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

### Requirement: Resilience-Observability Composition

The system SHALL ensure that retry and circuit-breaker behavior introduced by the `error-resilience` capability composes with the new `trace_graph_call` Protocol method without double-counting spans. For Graph HTTP calls wrapped by `@resilient_http`, exactly one `trace_graph_call` span MUST be emitted per HTTP attempt (not per user-level operation), and the `retry_attempt` field on each span MUST monotonically increase across retries of a single user-level operation. The `error-resilience` capability's existing `start_span("resilience.http_attempt", ...)` events MUST continue to be emitted for retries — these provide retry-loop visibility independently of `trace_graph_call`, which provides per-HTTP-request visibility.

#### Scenario: Successful retry emits one trace_graph_call per attempt

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
