# observability Specification (delta)

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
- `trace_memory_op(*, op, target, persona, duration_ms, metadata=None)` recording any `MemoryManager` method call. The `op` parameter MUST be one of `"context"`, `"snippets"`, `"fact_write"`, `"fact_list"`, `"preference_list"`, `"fact_delete"`, `"preference_write"`, `"interaction_write"`, `"interaction_list"`, `"episode_write"`, `"search"`, or `"export"` — each corresponding to a `MemoryManager` method on `src/assistant/core/memory.py`. (`fact_list`, `preference_list`, and `fact_delete` were added by knowledge-clean-room (P26) for the declassification gateway's structured reads and revocation purges, following the `interaction_list` precedent from eval-simulation-loop; `preference_write` was added by continual-learning (P28) for `MemoryManager.store_preference`, the write surface behind applied `preference` proposals.)
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

- **WHEN** `trace_memory_op(op="CONTEXT", ...)` is invoked on any provider (any value outside the fixed set `{"context", "snippets", "fact_write", "fact_list", "preference_list", "fact_delete", "preference_write", "interaction_write", "interaction_list", "episode_write", "search", "export"}`, including wrong-case variants)
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
