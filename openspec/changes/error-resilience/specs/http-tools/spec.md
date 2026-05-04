# http-tools Specification Delta

## ADDED Requirements

### Requirement: HTTP Tool Invocations Are Resilient

The system SHALL wrap every HTTP tool coroutine produced by `_build_tool()` in `src/assistant/http_tools/builder.py` with the `@resilient_http(source=source_name)` decorator from the `error-resilience` capability. The wrapping SHALL compose **inside** the existing `wrap_http_tool(tool)` observability wrapper so retry attempts and circuit-breaker state transitions are visible to telemetry.

The retry policy applied SHALL be `DEFAULT_HTTP_RETRY_POLICY` unless a per-source override is supplied at registration time. Tools that previously raised `httpx.HTTPStatusError` on a transient 5xx response SHALL now raise the same exception only after retries are exhausted or after the breaker for that source short-circuits with `CircuitBreakerOpenError`.

The breaker key SHALL be `f"http_tools:{source_name}"` so all tools belonging to the same OpenAPI source share one breaker.

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

#### Scenario: 4xx auth error is not retried

- **WHEN** a tool calls an endpoint that returns HTTP 401 on the first attempt
- **THEN** the tool MUST raise `httpx.HTTPStatusError` after exactly one attempt
- **AND** no further requests SHALL be sent

### Requirement: Discovery Retries Before Skip

The system SHALL wrap the OpenAPI document fetch in `src/assistant/http_tools/openapi.py` (and the `/help` fallback) with `@resilient_http(source=f"http_tools_discovery:{source_name}")` so a single transient blip during startup no longer permanently drops a tool source for the session. Discovery's existing graceful-skip contract — log a warning and exclude the source from the registry on terminal failure — SHALL be preserved, but only after retries are exhausted.

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
