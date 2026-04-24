# http-tools Specification Delta

## ADDED Requirements

### Requirement: HTTP Tool Invocations Emit Observability Span

The system SHALL wrap every HTTP tool constructed by `src/assistant/http_tools/builder.py` such that each invocation emits a `trace_tool_call` observability span with `tool_kind="http"`. The wrapping SHALL happen inside `_build_structured_tool` (or its successor in the builder) so the observability integration is transparent to `discover_tools` consumers.

The emitted call MUST include `tool_name` (the builder-assigned tool name, typically `<source>.<operationId>`), `tool_kind="http"`, `persona`, `role`, and `duration_ms`. When the underlying HTTPX call raises, the span MUST be emitted with `error=<exception type name>` before the exception propagates. The sanitization requirement (see `observability` capability, Requirement "Secret Sanitization") SHALL apply to every error message and metadata field before the span is emitted. That Requirement already covers `Bearer`, `Authorization: Basic`, `Authorization: Digest`, and `Cookie` patterns; this Requirement reiterates the cross-reference so implementers wrapping HTTP tools do not miss it.

#### Scenario: HTTP tool invocation emits trace_tool_call

- **WHEN** an HTTP-discovered tool `linear.listIssues` is invoked with persona `personal` and role `assistant`
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include `tool_name="linear.listIssues"`, `tool_kind="http"`, `persona="personal"`, and `role="assistant"`

#### Scenario: HTTP error propagates with trace emitted

- **WHEN** the HTTP call raises `httpx.HTTPStatusError` with a 503 status
- **THEN** `trace_tool_call` MUST be called with `error="HTTPStatusError"`
- **AND** the exception MUST propagate to the caller

#### Scenario: Authorization header does not leak into span metadata

- **WHEN** an HTTP tool invocation raises with a message that contains `Authorization: Bearer eyJhbGciOi...`
- **THEN** the emitted span's `metadata` string representation MUST contain `Bearer REDACTED`
- **AND** MUST NOT contain any portion of the original JWT value
