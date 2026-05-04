# http-tools Specification Delta

## ADDED Requirements

### Requirement: HTTP Tool Invocations Are Resilient

The system SHALL wrap every HTTP tool coroutine produced by `_build_tool()` in `src/assistant/http_tools/builder.py` with the `resilient_http(breaker_key=f"http_tools:{source_name}")` decorator from the `error-resilience` capability. The wrapping SHALL compose **inside** the existing `wrap_http_tool(tool)` observability wrapper so the user-level `trace_tool_call` summary remains a single span per tool invocation while the per-attempt visibility is delivered through `start_span` events emitted from inside `resilient_http` (see the `observability` capability delta for the composition rule).

The retry policy applied SHALL be `DEFAULT_HTTP_RETRY_POLICY` unless a per-source override is supplied at registration time. Tools that previously raised `httpx.HTTPStatusError` on a transient 5xx response SHALL now raise the same exception only after retries are exhausted or after the breaker for that source short-circuits with `CircuitBreakerOpenError`.

The breaker key passed to the decorator MUST be the canonical, fully-namespaced string `f"http_tools:{source_name}"` so all tools belonging to the same OpenAPI source share one breaker, and so the namespace appears explicitly at the call site (no implicit prefixing inside the decorator).

#### Scenario: Tool retries on 503 then succeeds

- **WHEN** a tool registered for source `"backend"` calls an endpoint that returns HTTP 503 twice and HTTP 200 with JSON body `{"ok": true}` on the third attempt
- **THEN** the tool's `ainvoke({...})` MUST return `{"ok": true}`
- **AND** the breaker for `"http_tools:backend"` MUST be in state `"closed"` after the call

#### Scenario: Tool fails terminally after retries exhausted

- **WHEN** a tool registered for source `"backend"` calls an endpoint that returns HTTP 503 on every attempt
- **THEN** the tool's `ainvoke({...})` MUST raise `httpx.HTTPStatusError`
- **AND** the raised exception MUST NOT be a `tenacity.RetryError`
- **AND** the breaker for `"http_tools:backend"` MUST record exactly one terminal failure (not one per retry)

#### Scenario: Open breaker short-circuits future tool calls

- **WHEN** the breaker for `"http_tools:backend"` is `open` and the cooldown has not elapsed
- **AND** any tool registered for source `"backend"` is invoked
- **THEN** `CircuitBreakerOpenError` MUST be raised
- **AND** the underlying HTTP request MUST NOT be sent
- **AND** the raised error's `breaker_key` attribute MUST equal `"http_tools:backend"`

#### Scenario: 4xx auth error is not retried and does not trip breaker

- **WHEN** a tool calls an endpoint that returns HTTP 401 on the first attempt
- **THEN** the tool MUST raise `httpx.HTTPStatusError` after exactly one attempt
- **AND** no further requests SHALL be sent
- **AND** the breaker for `"http_tools:backend"` MUST remain in state `"closed"` (the consecutive-failure counter MUST be unchanged)

### Requirement: Discovery Retries Before Skip

The system SHALL wrap the OpenAPI document fetch implemented in `src/assistant/http_tools/discovery.py::_fetch_openapi` with `resilient_http(breaker_key=f"http_tools_discovery:{source_name}")` so a single transient blip during startup no longer permanently drops a tool source for the session. Discovery's existing graceful-skip contract — log a warning and exclude the source from the registry on terminal failure — SHALL be preserved, but only after retries are exhausted.

`CircuitBreakerOpenError` raised during discovery (e.g., when a chronically-failing source has been seen multiple times during a long-running process that re-runs discovery) SHALL be caught at the discovery layer and treated identically to the existing graceful-skip outcome: warning logged, source omitted, no exception propagated to `discover_tools`.

#### Scenario: Discovery retries transient 503 before skipping

- **WHEN** `GET {base_url}/openapi.json` returns HTTP 503 twice and HTTP 200 with a valid OpenAPI document on the third attempt
- **THEN** the source MUST be included in the returned registry with all its operations

#### Scenario: Discovery skips after exhausting retries

- **WHEN** `GET {base_url}/openapi.json` returns HTTP 503 on every attempt for the configured `max_attempts`
- **AND** the `/help` fallback also returns HTTP 503 on every attempt
- **THEN** a warning MUST be logged identifying the source
- **AND** the source MUST be omitted from the returned registry
- **AND** `discover_tools` MUST NOT raise

#### Scenario: Discovery treats CircuitBreakerOpenError as skip

- **WHEN** the discovery breaker for `"http_tools_discovery:backend"` is open at the time `discover_tools` runs
- **THEN** a warning MUST be logged identifying the source as circuit-broken
- **AND** the source MUST be omitted from the returned registry
- **AND** `discover_tools` MUST NOT raise
