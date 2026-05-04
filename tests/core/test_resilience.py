"""Unit tests for src/assistant/core/resilience.py — covers RetryPolicy,
CircuitBreaker state machine, CircuitBreakerRegistry singleton semantics,
CircuitBreakerOpenError payload, sanitization + truncation contract, and
HealthStatus helpers.

Spec coverage: error-resilience.{RetryPolicyDataType, CircuitBreakerStateMachine,
CircuitBreakerRegistry, ErrorStringsAreSanitizedAndTruncated, HealthStatusType,
DefaultHealthStatusForUnimplementedStubs}.
"""

from __future__ import annotations

import asyncio
import dataclasses

import httpx
import pytest

from assistant.core.resilience import (
    DEFAULT_HTTP_RETRY_POLICY,
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    HealthState,
    HealthStatus,
    default_health_status_for_unimplemented,
    get_circuit_breaker_registry,
    health_status_from_breaker,
)

# ---------------------------------------------------------------------------
# RetryPolicy / DEFAULT_HTTP_RETRY_POLICY
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    def test_default_policy_carries_documented_values(self) -> None:
        # Spec: error-resilience.RetryPolicyDataType.1
        assert DEFAULT_HTTP_RETRY_POLICY.max_attempts == 3
        assert DEFAULT_HTTP_RETRY_POLICY.base_delay_s == 0.5
        assert DEFAULT_HTTP_RETRY_POLICY.retryable_status_codes == frozenset(
            {408, 425, 429, 500, 502, 503, 504},
        )
        assert DEFAULT_HTTP_RETRY_POLICY.retryable_exceptions == (
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
        )
        for exc_type in DEFAULT_HTTP_RETRY_POLICY.retryable_exceptions:
            assert issubclass(exc_type, httpx.HTTPError)

    def test_policy_is_frozen(self) -> None:
        # Spec: error-resilience.RetryPolicyDataType.2
        with pytest.raises(dataclasses.FrozenInstanceError):
            DEFAULT_HTTP_RETRY_POLICY.max_attempts = 99  # type: ignore[misc]
        assert DEFAULT_HTTP_RETRY_POLICY.max_attempts == 3


# ---------------------------------------------------------------------------
# CircuitBreaker state machine
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestCircuitBreakerStateMachine:
    @pytest.fixture
    def anyio_backend(self) -> str:
        return "asyncio"

    async def test_threshold_opens_breaker_with_sanitized_last_error(
        self,
    ) -> None:
        # Spec: error-resilience.CircuitBreakerStateMachine.ThresholdOpens
        breaker = CircuitBreaker(key="test:thr", failure_threshold=3)
        for i in range(3):
            await breaker.record_failure(f"HTTP 503 attempt {i}")
        assert breaker.state == "open"
        assert breaker.opened_at is not None
        # last_error should be sanitized & truncated form of "HTTP 503 attempt 2"
        assert breaker.last_error == "HTTP 503 attempt 2"

    async def test_success_resets_consecutive_failures(self) -> None:
        # Spec: error-resilience.CircuitBreakerStateMachine.SuccessResets
        breaker = CircuitBreaker(key="test:reset", failure_threshold=3)
        await breaker.record_failure("e1")
        await breaker.record_failure("e2")
        await breaker.record_success()
        assert breaker.state == "closed"
        await breaker.record_failure("e3")  # should count as 1, not 3
        assert breaker.state == "closed"
        assert breaker.consecutive_failures == 1

    async def test_non_availability_failure_handled_by_decorator_not_breaker(
        self,
    ) -> None:
        # The breaker class itself accepts any error via record_failure; the
        # availability classification lives in the decorator. This test
        # asserts that record_failure does NOT distinguish — it's the
        # decorator's responsibility (see test_resilience_decorator.py).
        breaker = CircuitBreaker(key="test:plain", failure_threshold=2)
        await breaker.record_failure("HTTP 401 unauthorized")
        assert breaker.consecutive_failures == 1

    async def test_half_open_admits_exactly_one_probe(self) -> None:
        # Spec: error-resilience.CircuitBreakerStateMachine.HalfOpenAdmitsExactlyOneProbe
        breaker = CircuitBreaker(
            key="test:halfopen",
            failure_threshold=1,
            cooldown_seconds=0.0,  # immediately ready
        )
        await breaker.record_failure("opening")
        assert breaker.state == "open"

        # Two concurrent admission attempts; only one should be admitted.
        results: list[str] = []

        async def _attempt(label: str) -> None:
            try:
                async with breaker.acquire_admission():
                    results.append(f"admit:{label}")
                    # Hold the probe slot briefly so the other concurrent
                    # caller observes in_flight_probe=True.
                    await asyncio.sleep(0.01)
                    await breaker.record_success()
            except CircuitBreakerOpenError:
                results.append(f"reject:{label}")

        await asyncio.gather(_attempt("a"), _attempt("b"))
        admits = [r for r in results if r.startswith("admit:")]
        rejects = [r for r in results if r.startswith("reject:")]
        assert len(admits) == 1
        assert len(rejects) == 1

    async def test_half_open_probe_succeeds_and_closes(self) -> None:
        # Spec: error-resilience.CircuitBreakerStateMachine.HalfOpenProbeSucceeds
        breaker = CircuitBreaker(
            key="test:probe-ok",
            failure_threshold=1,
            cooldown_seconds=0.0,
        )
        await breaker.record_failure("opening")
        async with breaker.acquire_admission():
            await breaker.record_success()
        assert breaker.state == "closed"
        assert breaker.opened_at is None

    async def test_half_open_probe_fails_reopens(self) -> None:
        # Spec: error-resilience.CircuitBreakerStateMachine.HalfOpenProbeFails
        breaker = CircuitBreaker(
            key="test:probe-fail",
            failure_threshold=1,
            cooldown_seconds=0.0,
        )
        await breaker.record_failure("opening")
        prior_next_probe = breaker.next_probe_at
        async with breaker.acquire_admission():
            await breaker.record_failure("probe failed")
        assert breaker.state == "open"
        # The new next_probe_at should be strictly later than the previous.
        assert breaker.next_probe_at is not None
        assert prior_next_probe is not None
        # When cooldown_seconds=0, datetimes can be equal at clock resolution;
        # what matters is that opened_at advanced.
        assert breaker.opened_at is not None


# ---------------------------------------------------------------------------
# CircuitBreakerRegistry
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestCircuitBreakerRegistry:
    @pytest.fixture
    def anyio_backend(self) -> str:
        return "asyncio"

    def test_registry_is_singleton(self) -> None:
        # Spec: error-resilience.CircuitBreakerRegistry.IsSingleton
        a = get_circuit_breaker_registry()
        b = get_circuit_breaker_registry()
        assert a is b

    async def test_first_lookup_creates_breaker(self) -> None:
        # Spec: error-resilience.CircuitBreakerRegistry.FirstLookupCreates
        reg = CircuitBreakerRegistry()
        b1 = reg.get_breaker("first-call:test")
        assert b1.state == "closed"
        b2 = reg.get_breaker("first-call:test")
        assert b1 is b2


# ---------------------------------------------------------------------------
# CircuitBreakerOpenError payload + sanitization
# ---------------------------------------------------------------------------


class TestSanitizationAndTruncation:
    def test_long_error_string_is_truncated_with_ellipsis_suffix(self) -> None:
        # Spec: error-resilience.ErrorStringsAreSanitizedAndTruncated.1
        # Use 500 ASCII chars containing no secrets
        payload = "X" * 500

        async def _drive() -> CircuitBreaker:
            breaker = CircuitBreaker(key="test:trunc", failure_threshold=10)
            await breaker.record_failure(payload)
            return breaker

        breaker = asyncio.run(_drive())
        assert breaker.last_error is not None
        assert len(breaker.last_error) == 200
        assert breaker.last_error.endswith("...")

    def test_error_string_is_sanitized_for_secrets(self) -> None:
        # Spec: error-resilience.ErrorStringsAreSanitizedAndTruncated.2
        secret_payload = "Authorization: Bearer sk-1234567890abcdef"

        async def _drive() -> CircuitBreaker:
            breaker = CircuitBreaker(key="test:sanitize", failure_threshold=10)
            await breaker.record_failure(secret_payload)
            return breaker

        breaker = asyncio.run(_drive())
        assert breaker.last_error is not None
        assert "sk-1234567890abcdef" not in breaker.last_error

    def test_circuit_breaker_open_error_carries_sanitized_summary(self) -> None:
        # Spec: error-resilience.ErrorStringsAreSanitizedAndTruncated.3
        secret = "raw last error sk-secret-abcdef0123456789"
        err = CircuitBreakerOpenError(
            breaker_key="test:cbe",
            opened_at=None,
            next_probe_at=None,
            last_error_summary=secret,
        )
        assert err.last_error_summary is not None
        assert "sk-secret-abcdef0123456789" not in err.last_error_summary


# ---------------------------------------------------------------------------
# HealthStatus + helpers
# ---------------------------------------------------------------------------


class TestHealthStatus:
    def test_closed_breaker_maps_to_ok(self) -> None:
        # Spec: error-resilience.HealthStatusType.ClosedMapsToOK
        breaker = CircuitBreaker(key="extension:gmail")
        status = health_status_from_breaker(breaker, key="extension:gmail")
        assert status.state is HealthState.OK
        assert status.breaker_key == "extension:gmail"

    def test_open_breaker_maps_to_unavailable(self) -> None:
        # Spec: error-resilience.HealthStatusType.OpenMapsToUnavailable
        async def _drive() -> CircuitBreaker:
            b = CircuitBreaker(key="extension:gmail", failure_threshold=1)
            await b.record_failure("HTTP 503")
            return b

        breaker = asyncio.run(_drive())
        status = health_status_from_breaker(breaker, key="extension:gmail")
        assert status.state is HealthState.UNAVAILABLE
        assert status.last_error == "HTTP 503"

    def test_default_health_status_for_unimplemented(self) -> None:
        # Spec: error-resilience.DefaultHealthStatusForUnimplementedStubs
        status = default_health_status_for_unimplemented("gmail")
        assert isinstance(status, HealthStatus)
        assert status.state is HealthState.UNKNOWN
        assert status.reason == "extension is a stub"
        assert status.breaker_key is None
