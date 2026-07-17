# http-tools Specification (delta)

## RENAMED Requirements

- FROM: `### Requirement: Tool Builder Generates Typed StructuredTool`
- TO: `### Requirement: Tool Builder Generates a Typed ToolSpec`

## MODIFIED Requirements

### Requirement: Tool Builder Generates a Typed ToolSpec

The system SHALL provide a `_build_tool(source_name, base_url,
operation, client, auth_headers)` factory that returns a
harness-neutral `ToolSpec` (see the `tool-spec` capability) whose
`input_schema` is the JSON Schema of a Pydantic `BaseModel` subclass
generated at runtime (via `pydantic.create_model`) from the
operation's parameters + request body schema. The spec's async
`handler` SHALL validate incoming kwargs against that runtime model
(the same validation LangChain's `StructuredTool` previously applied)
before issuing the HTTP call, so every rendering surface receives
identical validation.

The returned spec's `name` SHALL equal the registry key
`"{source_name}:{operation_id}"` — identical to the key under which
the spec is registered in `HttpToolRegistry` — and its `source` SHALL
be `"http:{source_name}"`.

The spec's handler SHALL invoke
`client.request(method, path, params=..., json=..., headers=auth_headers)`,
substituting path parameters from the validated arguments into
`{placeholder}` path segments, and return the parsed JSON response
body.

Path parameter values SHALL be URL-encoded via
`urllib.parse.quote(value, safe="")` before substitution into the path
template. The explicit `safe=""` argument is required — the library
default `safe="/"` leaves `/` un-encoded, which would allow a
path-parameter value like `"foo/bar"` to alter the request path
structure.

If the 2xx response's `Content-Type` header is not `application/json`
(or a JSON-compatible variant such as `application/problem+json`), the
handler SHALL raise `ValueError` naming the source and operation.
Empty-body 2xx responses (HTTP 204 or `Content-Length: 0`) SHALL
return `None`.

Required JSON Schema fields SHALL produce required model fields.
Optional fields SHALL use the schema's declared `default` when
present, else `None`. Schemas with neither `type` nor `$ref` SHALL
produce `Any` typed fields.

#### Scenario: POST tool with JSON body

- **WHEN** `_build_tool` is called with a `POST /items` operation
  whose `requestBody` schema has fields `{name: str, quantity: int}`
- **AND** the returned spec's handler is awaited with
  `name="widget", quantity=3`
- **THEN** an HTTP `POST` to `{base_url}/items` MUST be issued
- **AND** the request JSON body MUST be `{"name": "widget", "quantity": 3}`

#### Scenario: GET tool with path + query parameters

- **WHEN** `_build_tool` wraps a `GET /items/{id}` operation with a
  query parameter `verbose: bool`
- **AND** the returned spec's handler is awaited with
  `id="42", verbose=True`
- **THEN** an HTTP `GET` to `{base_url}/items/42?verbose=true` MUST be
  issued

#### Scenario: Non-2xx response raises

- **WHEN** the handler's HTTP call returns status 500
- **THEN** the handler MUST raise `httpx.HTTPStatusError` (or a
  wrapping exception whose `__cause__` is an `HTTPStatusError`)

#### Scenario: Non-JSON 2xx content-type raises

- **WHEN** the handler's HTTP call returns status 200 with
  `Content-Type: text/html`
- **THEN** the handler MUST raise `ValueError` naming the source and
  operation

#### Scenario: Empty-body 2xx returns None

- **WHEN** the handler's HTTP call returns status 204 (No Content)
- **THEN** the handler MUST return `None`

#### Scenario: ToolSpec name matches registry key

- **WHEN** `_build_tool` wraps operation `list_items` from source
  `backend`
- **THEN** the returned spec's `name` attribute MUST equal
  `"backend:list_items"`
- **AND** its `input_schema` MUST be the JSON Schema derived from the
  operation's parameters and request body

#### Scenario: Path parameter URL-encoded

- **WHEN** `_build_tool` wraps `GET /items/{id}`
- **AND** the handler is awaited with `id="foo/bar"`
- **THEN** the request URL MUST be `{base_url}/items/foo%2Fbar`

#### Scenario: Required JSON Schema field is required at invocation

- **WHEN** an operation's `requestBody` schema declares
  `{"required": ["name"], "properties": {"name": {"type": "string"}}}`
- **THEN** the spec's `input_schema` MUST mark `name` required
- **AND** awaiting the handler without `name` MUST raise a Pydantic
  `ValidationError` before any HTTP request is issued

#### Scenario: Optional JSON Schema field uses declared default

- **WHEN** an operation's schema declares a property
  `{"type": "integer", "default": 1}` that is NOT in `required`
- **THEN** the spec's `input_schema` property MUST carry default `1`

#### Scenario: Typeless JSON Schema field is Any

- **WHEN** an operation's schema declares a property with neither
  `type` nor `$ref`
- **THEN** the generated model field type MUST be `Any`

#### Scenario: Oversized response at invocation time raises

- **WHEN** a handler's HTTP call returns a 2xx body exceeding 10 MiB
- **THEN** the handler MUST raise
  `ValueError("response exceeds 10MiB")`

#### Scenario: Redirect at invocation time raises

- **WHEN** a handler's HTTP call returns HTTP 302 with a `Location`
  header
- **THEN** the handler MUST raise `httpx.HTTPStatusError`
- **AND** no request to the redirect target MUST be issued

#### Scenario: Timeout at invocation time raises

- **WHEN** a handler's HTTP call exceeds the configured 10-second
  read timeout
- **THEN** the handler MUST raise `httpx.TimeoutException`
  (or a subclass thereof)

### Requirement: HTTP Tool Invocations Emit Observability Span

The system SHALL wrap every HTTP `ToolSpec` constructed by
`src/assistant/http_tools/builder.py` such that each handler
invocation emits a `trace_tool_call` observability span with
`tool_kind="http"`. The wrapping SHALL happen inside `_build_tool`
via `wrap_http_tool_spec` so the observability integration is
transparent to `discover_tools` consumers, and — because the
per-harness adapters are pure renderings that invoke `spec.handler` —
the span survives every rendering surface.

The emitted call MUST include `tool_name` (the builder-assigned
`"{source}:{operation_id}"` name), `tool_kind="http"`, `persona`,
`role`, and `duration_ms`. When the underlying HTTPX call raises, the
span MUST be emitted with `error=<exception type name>` before the
exception propagates. The sanitization requirement (see
`observability` capability, Requirement "Secret Sanitization") SHALL
apply to every error message and metadata field before the span is
emitted.

#### Scenario: HTTP tool invocation emits trace_tool_call

- **WHEN** an HTTP-discovered spec `linear:listIssues` has its handler
  awaited with persona `personal` and role `assistant`
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include
  `tool_name="linear:listIssues"`, `tool_kind="http"`,
  `persona="personal"`, and `role="assistant"`

#### Scenario: HTTP error propagates with trace emitted

- **WHEN** the HTTP call raises `httpx.HTTPStatusError` with a 503 status
- **THEN** `trace_tool_call` MUST be called with `error="HTTPStatusError"`
- **AND** the exception MUST propagate to the caller

#### Scenario: Authorization header does not leak into span metadata

- **WHEN** an HTTP tool invocation raises with a message that contains `Authorization: Bearer eyJhbGciOi...`
- **THEN** the emitted span's `metadata` string representation MUST contain `Bearer REDACTED`
- **AND** MUST NOT contain any portion of the original JWT value

### Requirement: HTTP Tool Invocations Are Resilient

The system SHALL wrap every HTTP tool coroutine produced by
`_build_tool()` in `src/assistant/http_tools/builder.py` with the
`resilient_http(breaker_key=f"http_tools:{source_name}")` decorator
from the `error-resilience` capability. The composition order
outside-in SHALL be: `wrap_http_tool_spec` (observability summary
span) → ToolSpec handler validation → `resilient_http` (retry +
breaker + per-attempt `start_span` events) → raw HTTP coroutine — so
the user-level `trace_tool_call` summary remains a single span per
tool invocation while per-attempt visibility is delivered through
`start_span` events emitted from inside `resilient_http`.

The retry policy applied SHALL be `DEFAULT_HTTP_RETRY_POLICY` unless a per-source override is supplied at registration time. Tools that previously raised `httpx.HTTPStatusError` on a transient 5xx response SHALL now raise the same exception only after retries are exhausted or after the breaker for that source short-circuits with `CircuitBreakerOpenError`.

The breaker key passed to the decorator MUST be the canonical, fully-namespaced string `f"http_tools:{source_name}"` so all tools belonging to the same OpenAPI source share one breaker, and so the namespace appears explicitly at the call site (no implicit prefixing inside the decorator).

#### Scenario: Tool retries on 503 then succeeds

- **WHEN** a spec registered for source `"backend"` calls an endpoint that returns HTTP 503 twice and HTTP 200 with JSON body `{"ok": true}` on the third attempt
- **THEN** awaiting the spec's handler MUST return `{"ok": true}`
- **AND** the breaker for `"http_tools:backend"` MUST be in state `"closed"` after the call

#### Scenario: Tool fails terminally after retries exhausted

- **WHEN** a spec registered for source `"backend"` calls an endpoint that returns HTTP 503 on every attempt
- **THEN** awaiting the spec's handler MUST raise `httpx.HTTPStatusError`
- **AND** the raised exception MUST NOT be a `tenacity.RetryError`
- **AND** the breaker for `"http_tools:backend"` MUST record exactly one terminal failure (not one per retry)

#### Scenario: Open breaker short-circuits future tool calls

- **WHEN** the breaker for `"http_tools:backend"` is `open` and the cooldown has not elapsed
- **AND** any spec registered for source `"backend"` is invoked
- **THEN** `CircuitBreakerOpenError` MUST be raised
- **AND** the underlying HTTP request MUST NOT be sent
- **AND** the raised error's `breaker_key` attribute MUST equal `"http_tools:backend"`

#### Scenario: 4xx auth error is not retried and does not trip breaker

- **WHEN** a spec's handler calls an endpoint that returns HTTP 401 on the first attempt
- **THEN** the handler MUST raise `httpx.HTTPStatusError` after exactly one attempt
- **AND** no further requests SHALL be sent
- **AND** the breaker for `"http_tools:backend"` MUST remain in state `"closed"` (the consecutive-failure counter MUST be unchanged)
