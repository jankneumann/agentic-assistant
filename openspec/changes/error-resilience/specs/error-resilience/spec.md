# error-resilience Specification Delta

## ADDED Requirements

### Requirement: Retry Policy Data Type

The system SHALL define a `RetryPolicy` frozen dataclass at `src/assistant/core/resilience.py` capturing every parameter that governs a retried operation: `max_attempts: int`, `base_delay_s: float`, `max_delay_s: float`, `jitter_factor: float`, `retryable_status_codes: frozenset[int]`, and `retryable_exceptions: tuple[type[BaseException], ...]`.

The module SHALL expose `DEFAULT_HTTP_RETRY_POLICY: RetryPolicy` configured for HTTP tool invocations: `max_attempts=3`, `base_delay_s=0.5`, `max_delay_s=8.0`, `jitter_factor=0.25`, retryable status codes `{408, 425, 429, 500, 502, 503, 504}`, retryable exceptions `(httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError, httpx.PoolTimeout)`.

`RetryPolicy` instances MUST be immutable (frozen dataclass) so callers cannot mutate a shared default.

#### Scenario: Default policy carries documented values

- **WHEN** `DEFAULT_HTTP_RETRY_POLICY` is imported and inspected
- **THEN** `max_attempts` MUST equal `3`
- **AND** `base_delay_s` MUST equal `0.5`
- **AND** `retryable_status_codes` MUST equal `frozenset({408, 425, 429, 500, 502, 503, 504})`
- **AND** every member of `retryable_exceptions` MUST be a subclass of `httpx.HTTPError`

#### Scenario: Policy is frozen

- **WHEN** code attempts to assign `DEFAULT_HTTP_RETRY_POLICY.max_attempts = 99`
- **THEN** a `dataclasses.FrozenInstanceError` MUST be raised
- **AND** the original `max_attempts` value MUST remain unchanged

### Requirement: Circuit Breaker State Machine

The system SHALL provide a `CircuitBreaker` class at `src/assistant/core/resilience.py` implementing a three-state machine: `closed`, `open`, `half_open`. The breaker SHALL transition between states under these rules:

- **closed → open**: `failure_threshold` consecutive failures (default 5) move the breaker to `open` and record `opened_at` and `next_probe_at = opened_at + cooldown_seconds` (default 30 seconds).
- **open → half_open**: a guarded call attempted at or after `next_probe_at` MUST be allowed through as a single probe, transitioning the breaker to `half_open`.
- **half_open → closed**: a successful probe call MUST reset the breaker to `closed` and zero the failure counter.
- **half_open → open**: a failed probe call MUST move the breaker back to `open` with a new `opened_at` and `next_probe_at`.
- **closed → closed**: any successful call SHALL reset the consecutive-failure counter to zero.

Each `CircuitBreaker` instance SHALL be safe for concurrent use by multiple `asyncio` tasks; concurrent calls observing the breaker state MUST do so under an `asyncio.Lock` private to the breaker. The breaker SHALL expose read-only attributes `state`, `last_error: str | None`, `opened_at: datetime | None`, and `next_probe_at: datetime | None`.

#### Scenario: Threshold opens the breaker

- **WHEN** a `CircuitBreaker` with `failure_threshold=3` records three consecutive failures via `record_failure(error)`
- **THEN** `state` MUST equal `"open"`
- **AND** `opened_at` MUST equal the timestamp of the third failure
- **AND** `last_error` MUST equal the string representation of the third error

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

The system SHALL provide a decorator factory `resilient_http(*, source: str, policy: RetryPolicy | None = None)` at `src/assistant/core/resilience.py` that wraps an `async def` callable and applies retry-with-backoff plus circuit-breaker protection, scoped to the breaker key derived from `source`.

On each invocation the wrapper SHALL:

1. Look up the breaker for `source` (creating if absent).
2. If the breaker is `open` and the cooldown has not elapsed, raise `CircuitBreakerOpenError(breaker_key, opened_at, next_probe_at, last_error_summary)` without calling the wrapped function.
3. Otherwise, execute the wrapped function under tenacity retry policy derived from `policy or DEFAULT_HTTP_RETRY_POLICY`. Retries MUST be triggered by:
   - any `httpx.HTTPStatusError` whose `response.status_code` is in `policy.retryable_status_codes`, **or**
   - any exception type in `policy.retryable_exceptions`.
4. Apply exponential backoff with jitter: delay between attempts MUST be `min(max_delay_s, base_delay_s * 2 ** (attempt-1))` multiplied by a uniform random factor in `[1 - jitter_factor, 1 + jitter_factor]`.
5. On success, call `breaker.record_success()`.
6. On terminal failure (retries exhausted or non-retryable error), call `breaker.record_failure(error)` and re-raise the **original** exception (NOT a tenacity `RetryError` wrapper).

`CircuitBreakerOpenError` SHALL inherit from `Exception` and carry the breaker key, opened-at timestamp, next-probe-at timestamp, and a string summary of the last error.

#### Scenario: Retry-then-success returns the wrapped result

- **WHEN** a wrapped coroutine fails with HTTP 503 on attempt 1, HTTP 503 on attempt 2, and succeeds with payload `{"ok": true}` on attempt 3
- **THEN** the wrapper MUST return `{"ok": true}`
- **AND** the breaker MUST be in state `"closed"` with failure counter zero

#### Scenario: Non-retryable status fails on first attempt

- **WHEN** a wrapped coroutine fails with HTTP 401 on the first attempt
- **THEN** the wrapper MUST raise the original `httpx.HTTPStatusError` after a single attempt
- **AND** no further attempts SHALL be made
- **AND** the breaker MUST record one failure

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
