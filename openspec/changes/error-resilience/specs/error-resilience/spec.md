# error-resilience Specification Delta

## ADDED Requirements

### Requirement: Retry Policy Data Type

The system SHALL define a `RetryPolicy` frozen dataclass at `src/assistant/core/resilience.py` capturing every parameter that governs a retried operation: `max_attempts: int`, `base_delay_s: float`, `max_delay_s: float`, `jitter_factor: float`, `retryable_status_codes: frozenset[int]`, and `retryable_exceptions: tuple[type[BaseException], ...]`.

The module SHALL expose `DEFAULT_HTTP_RETRY_POLICY: RetryPolicy` configured for HTTP tool invocations: `max_attempts=3`, `base_delay_s=0.5`, `max_delay_s=8.0`, `jitter_factor=0.25`, retryable status codes `{408, 425, 429, 500, 502, 503, 504}`, retryable exceptions `(httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ConnectError, httpx.RemoteProtocolError)`.

`RetryPolicy` instances MUST be immutable (frozen dataclass) so callers cannot mutate a shared default.

#### Scenario: Default policy carries documented values

- **WHEN** `DEFAULT_HTTP_RETRY_POLICY` is imported and inspected
- **THEN** `max_attempts` MUST equal `3`
- **AND** `base_delay_s` MUST equal `0.5`
- **AND** `retryable_status_codes` MUST equal `frozenset({408, 425, 429, 500, 502, 503, 504})`
- **AND** `retryable_exceptions` MUST be a tuple containing exactly `(httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ConnectError, httpx.RemoteProtocolError)`
- **AND** every member of `retryable_exceptions` MUST be a subclass of `httpx.HTTPError`

#### Scenario: Policy is frozen

- **WHEN** code attempts to assign `DEFAULT_HTTP_RETRY_POLICY.max_attempts = 99`
- **THEN** a `dataclasses.FrozenInstanceError` MUST be raised
- **AND** the original `max_attempts` value MUST remain unchanged

### Requirement: Circuit Breaker State Machine

The system SHALL provide a `CircuitBreaker` class at `src/assistant/core/resilience.py` implementing a three-state machine: `closed`, `open`, `half_open`. The breaker SHALL transition between states under these rules:

- **closed → open**: `failure_threshold` consecutive **availability failures** (default 5) move the breaker to `open` and record `opened_at` and `next_probe_at = opened_at + cooldown_seconds` (default 30 seconds). An "availability failure" is one of (a) a retryable status code from the active `RetryPolicy`, (b) a retryable exception type from the active `RetryPolicy`, or (c) `CircuitBreakerOpenError` raised by an inner guarded call. **Non-availability** failures (e.g., HTTP 401 / 403 / 404 / 422) MUST NOT increment the consecutive-failure counter — they re-raise to the caller without affecting breaker state.
- **open → half_open**: a guarded call attempted at or after `next_probe_at` MUST be allowed through as **exactly one** probe, transitioning the breaker to `half_open`. The breaker MUST track an in-flight-probe state so that any additional concurrent call arriving while the probe is in flight is short-circuited with `CircuitBreakerOpenError` instead of issuing a second probe.
- **half_open → closed**: a successful probe call MUST reset the breaker to `closed`, zero the failure counter, and clear the in-flight-probe state.
- **half_open → open**: a failed probe call MUST move the breaker back to `open` with a new `opened_at` and `next_probe_at`, and clear the in-flight-probe state.
- **closed → closed**: any successful call SHALL reset the consecutive-failure counter to zero.

Each `CircuitBreaker` instance SHALL be safe for concurrent use by multiple `asyncio` tasks; concurrent calls observing the breaker state MUST do so under an `asyncio.Lock` private to the breaker. The breaker SHALL expose read-only attributes `state`, `last_error: str | None`, `opened_at: datetime | None`, and `next_probe_at: datetime | None`.

#### Scenario: Threshold opens the breaker (availability failures only)

- **WHEN** a `CircuitBreaker` with `failure_threshold=3` records three consecutive availability failures via `record_failure(error)`
- **THEN** `state` MUST equal `"open"`
- **AND** `opened_at` MUST equal the timestamp of the third failure
- **AND** `last_error` MUST equal the **sanitized and truncated** string representation of the third error per the "Error Strings Are Sanitized And Truncated" requirement

#### Scenario: Non-availability failure does not affect breaker

- **WHEN** a `CircuitBreaker` with `failure_threshold=3` is `closed` with zero consecutive failures
- **AND** a guarded call fails with HTTP 401 (a status code outside `RetryPolicy.retryable_status_codes`)
- **THEN** the breaker MUST remain `closed`
- **AND** the consecutive-failure counter MUST remain `0`
- **AND** the original `httpx.HTTPStatusError` MUST be re-raised to the caller

#### Scenario: Half-open admits exactly one probe

- **WHEN** the breaker is `open` and the cooldown has elapsed
- **AND** two concurrent guarded calls arrive at approximately the same instant
- **THEN** exactly one of the two calls MUST be admitted as the probe (transitioning the breaker to `half_open`)
- **AND** the other call MUST raise `CircuitBreakerOpenError` without invoking the wrapped function
- **AND** the in-flight-probe state MUST be cleared once the probe completes (success or failure)

#### Scenario: Successful call resets the failure counter

- **WHEN** a breaker has recorded two consecutive failures
- **AND** `record_success()` is then called
- **THEN** the breaker MUST remain in state `"closed"`
- **AND** a subsequent failure MUST count as the first of a new failure run, not the third overall

#### Scenario: Half-open probe succeeds and closes

- **WHEN** a breaker is `open` and the cooldown has elapsed
- **AND** a guarded call is attempted and succeeds
- **THEN** the breaker MUST be `closed` after the call
- **AND** `opened_at` MUST be `None`

#### Scenario: Half-open probe fails and re-opens

- **WHEN** a breaker is `open` and the cooldown has elapsed
- **AND** a guarded call is attempted and fails
- **THEN** the breaker MUST be `open` after the call
- **AND** `next_probe_at` MUST be reset to a value strictly after the prior `next_probe_at`

### Requirement: Circuit Breaker Registry

The system SHALL provide a process-wide `CircuitBreakerRegistry` accessed via `get_circuit_breaker_registry()` returning a singleton `dict[str, CircuitBreaker]`. The registry SHALL key breakers by **backend identifier strings** following the namespace convention `"http_tools:<source_name>"`, `"http_tools_discovery:<source_name>"`, and `"extension:<extension_name>"`.

The accessor `get_breaker(key: str) -> CircuitBreaker` SHALL return the existing breaker for that key or, if absent, create one with default thresholds and insert it before returning. Lookup and insertion SHALL be safe under concurrent access from multiple `asyncio` tasks.

#### Scenario: Registry is process-singleton

- **WHEN** `get_circuit_breaker_registry()` is called twice in the same process
- **THEN** both calls MUST return the same object identity (same `id(...)`)

#### Scenario: First lookup creates the breaker

- **WHEN** `get_breaker("http_tools:gcal")` is called for the first time in the process
- **THEN** a fresh `CircuitBreaker` MUST be returned in `closed` state
- **AND** subsequent calls with the same key MUST return that same instance

### Requirement: Resilient Decorator

The system SHALL provide a decorator factory `resilient_http(*, breaker_key: str, policy: RetryPolicy | None = None)` at `src/assistant/core/resilience.py` that wraps an `async def` callable and applies retry-with-backoff plus circuit-breaker protection. The `breaker_key` argument is the **canonical, fully-namespaced** registry key (e.g., `"http_tools:gcal"`, `"http_tools_discovery:gcal"`, `"extension:gmail"`) — call sites MUST construct the key explicitly so that no namespace prefix is implicit in the decorator.

On each invocation the wrapper SHALL:

1. Look up the breaker for `breaker_key` (creating if absent).
2. If the breaker is `open` and the cooldown has not elapsed, **or** if the breaker is `half_open` with a probe already in flight, raise `CircuitBreakerOpenError(breaker_key, opened_at, next_probe_at, last_error_summary)` without calling the wrapped function.
3. Otherwise, execute the wrapped function under tenacity retry policy derived from `policy or DEFAULT_HTTP_RETRY_POLICY`. Retries MUST be triggered by:
   - any `httpx.HTTPStatusError` whose `response.status_code` is in `policy.retryable_status_codes`, **or**
   - any exception type in `policy.retryable_exceptions`.
4. Apply exponential backoff with jitter: delay between attempts MUST be `min(max_delay_s, base_delay_s * 2 ** (attempt-1))` multiplied by a uniform random factor in `[1 - jitter_factor, 1 + jitter_factor]`. The delay MUST be implemented via async sleep so the event loop is not blocked.
5. On success, call `breaker.record_success()`.
6. On terminal failure, classify before recording:
   - **Availability failure** (retries exhausted on a retryable error, OR the error matches `policy.retryable_status_codes` / `policy.retryable_exceptions`): call `breaker.record_failure(error)` and re-raise the **original** exception (NOT a tenacity `RetryError` wrapper).
   - **Non-availability failure** (error not in `retryable_status_codes` and not an instance of any `retryable_exceptions` type — e.g., HTTP 401 / 403 / 404 / 422, `ValueError` from the 10-MiB cap): re-raise the **original** exception **without** calling `breaker.record_failure(error)`. Non-availability errors MUST NOT trip the breaker.

`CircuitBreakerOpenError` SHALL inherit from `Exception` and carry the breaker key, opened-at timestamp, next-probe-at timestamp, and a sanitized string summary of the last error (per "Error Strings Are Sanitized And Truncated").

#### Scenario: Retry-then-success returns the wrapped result

- **WHEN** a wrapped coroutine fails with HTTP 503 on attempt 1, HTTP 503 on attempt 2, and succeeds with payload `{"ok": true}` on attempt 3
- **THEN** the wrapper MUST return `{"ok": true}`
- **AND** the breaker MUST be in state `"closed"` with failure counter zero

#### Scenario: Non-retryable status fails on first attempt and does not trip breaker

- **WHEN** a wrapped coroutine fails with HTTP 401 on the first attempt
- **THEN** the wrapper MUST raise the original `httpx.HTTPStatusError` after a single attempt
- **AND** no further attempts SHALL be made
- **AND** the breaker MUST NOT record a failure (consecutive-failure counter unchanged, state remains `closed`)

#### Scenario: WriteTimeout is retried by default policy

- **WHEN** a wrapped coroutine fails with `httpx.WriteTimeout` on attempt 1 and succeeds on attempt 2
- **THEN** the wrapper MUST return the attempt-2 result
- **AND** the breaker MUST be in state `"closed"`

#### Scenario: Open breaker short-circuits without invoking wrapped function

- **WHEN** a breaker is `open` and `next_probe_at` is in the future
- **AND** a wrapped coroutine is invoked
- **THEN** `CircuitBreakerOpenError` MUST be raised
- **AND** the wrapped coroutine MUST NOT be called
- **AND** the error MUST carry `breaker_key`, `opened_at`, `next_probe_at`, and `last_error_summary`

#### Scenario: Terminal retry exhaustion raises original exception

- **WHEN** a wrapped coroutine fails with HTTP 503 on every attempt up to `max_attempts`
- **THEN** the wrapper MUST raise the underlying `httpx.HTTPStatusError`
- **AND** the raised exception MUST NOT be a `tenacity.RetryError`

#### Scenario: Retries 429 Too Many Requests with backoff

- **WHEN** a wrapped coroutine fails with HTTP 429 on attempt 1 and HTTP 200 on attempt 2
- **THEN** the wrapper MUST return the attempt-2 response payload
- **AND** the delay between attempts MUST be at least `(1 - jitter_factor) * base_delay_s` seconds
- **AND** the breaker MUST be in state `"closed"` after the call

#### Scenario: Async retry uses asyncio sleep, not blocking sleep

- **WHEN** a wrapped coroutine fails on the first attempt and the wrapper schedules a retry delay
- **THEN** during that delay, other `asyncio` tasks scheduled on the same event loop MUST be able to make progress (the delay MUST NOT block the event loop)

### Requirement: Error Strings Are Sanitized And Truncated

The system SHALL sanitize and truncate every error string before storing it on `CircuitBreaker.last_error`, `CircuitBreakerOpenError.last_error_summary`, or `HealthStatus.last_error`. Sanitization MUST be performed by routing the string through `assistant.telemetry.sanitize.sanitize` (the secret-redaction chain established by the `observability` capability). Truncation MUST cap the resulting string at 200 characters; truncated values MUST end with the literal three-character suffix `"..."`.

This rule prevents upstream response bodies — which may contain authentication tokens, email addresses, or other sensitive content from misconfigured backends — from leaking into logs, telemetry attributes, or future agent prompts via the resilience module.

#### Scenario: Long error string is truncated with ellipsis suffix

- **WHEN** an error message of 500 characters is recorded via `breaker.record_failure(error)`
- **THEN** `breaker.last_error` MUST have length 200
- **AND** `breaker.last_error` MUST end with `"..."`

#### Scenario: Error string is sanitized for secrets

- **WHEN** an error message containing `"Authorization: Bearer sk-1234567890abcdef"` is recorded via `breaker.record_failure(error)`
- **THEN** `breaker.last_error` MUST NOT contain the literal substring `"sk-1234567890abcdef"`
- **AND** the redacted form produced by the sanitize chain MUST be present in its place

#### Scenario: CircuitBreakerOpenError carries sanitized last_error_summary

- **WHEN** the breaker is `open` after recording a failure with `"Authorization: Bearer sk-secret"` in the error string
- **AND** a guarded call attempts to invoke the wrapped function
- **THEN** the raised `CircuitBreakerOpenError.last_error_summary` MUST NOT contain the literal substring `"sk-secret"`

### Requirement: Health Status Type

The system SHALL define a `HealthState` enum and a `HealthStatus` frozen dataclass at `src/assistant/core/resilience.py`. `HealthState` SHALL have exactly four members: `OK`, `DEGRADED`, `UNAVAILABLE`, `UNKNOWN`. `HealthStatus` SHALL carry: `state: HealthState`, `reason: str | None`, `last_error: str | None`, `checked_at: datetime`, `breaker_key: str | None`.

The module SHALL expose a helper `health_status_from_breaker(breaker: CircuitBreaker, *, key: str) -> HealthStatus` that produces a `HealthStatus` from runtime breaker state: `closed → OK`, `half_open → DEGRADED`, `open → UNAVAILABLE`, with `last_error` and `breaker_key` populated and `checked_at` set to the current time.

#### Scenario: Closed breaker maps to OK

- **WHEN** `health_status_from_breaker(breaker, key="extension:gmail")` is called and the breaker is `closed`
- **THEN** the returned `HealthStatus.state` MUST equal `HealthState.OK`
- **AND** `breaker_key` MUST equal `"extension:gmail"`

#### Scenario: Open breaker maps to UNAVAILABLE with reason

- **WHEN** the breaker is `open` with `last_error="HTTP 503"`
- **THEN** the returned `HealthStatus.state` MUST equal `HealthState.UNAVAILABLE`
- **AND** `last_error` MUST equal `"HTTP 503"`

### Requirement: Default Health Status For Unimplemented Stubs

The system SHALL provide a helper `default_health_status_for_unimplemented(extension_name: str) -> HealthStatus` returning `HealthStatus(state=HealthState.UNKNOWN, reason="extension is a stub", last_error=None, checked_at=<now>, breaker_key=None)` so each extension stub can return a single line of code from `health_check()` until its real backend probe is wired.

#### Scenario: Stub helper produces UNKNOWN status

- **WHEN** `default_health_status_for_unimplemented("gmail")` is called
- **THEN** the returned `HealthStatus.state` MUST equal `HealthState.UNKNOWN`
- **AND** `reason` MUST equal `"extension is a stub"`
- **AND** `breaker_key` MUST be `None`
