"""Behavioral tests for ``resilient_http`` decorator — retry semantics,
breaker integration, non-availability classification, and async-non-blocking
delay.

Spec coverage: error-resilience.ResilientDecorator.{1,2,3,4,5,6,7}.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from assistant.core.resilience import (
    DEFAULT_HTTP_RETRY_POLICY,
    CircuitBreaker,
    CircuitBreakerOpenError,
    RetryPolicy,
    get_circuit_breaker_registry,
    resilient_http,
)


def _make_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/api")
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


# Tight policy (no real sleep) for fast tests.
_TEST_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay_s=0.0,  # zero base delay — jittered to ~0 for test speed
    max_delay_s=0.0,
    jitter_factor=0.0,
    retryable_status_codes=DEFAULT_HTTP_RETRY_POLICY.retryable_status_codes,
    retryable_exceptions=DEFAULT_HTTP_RETRY_POLICY.retryable_exceptions,
)


def _fresh_breaker(key: str) -> CircuitBreaker:
    """Force a breaker reset by replacing the registry entry."""
    reg = get_circuit_breaker_registry()
    reg._breakers[key] = CircuitBreaker(
        key=key,
        failure_threshold=2,
        cooldown_seconds=0.0,
    )
    return reg._breakers[key]


@pytest.mark.anyio
class TestResilientDecorator:
    @pytest.fixture
    def anyio_backend(self) -> str:
        return "asyncio"

    async def test_retry_then_success_returns_payload(self) -> None:
        # Spec: ResilientDecorator.RetryThenSuccess
        breaker = _fresh_breaker("test:rty-success")
        attempts = {"n": 0}

        @resilient_http(breaker_key=breaker.key, policy=_TEST_POLICY)
        async def _call() -> dict[str, bool]:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _make_status_error(503)
            return {"ok": True}

        result = await _call()
        assert result == {"ok": True}
        assert breaker.state == "closed"

    async def test_non_retryable_status_does_not_trip_breaker(self) -> None:
        # Spec: ResilientDecorator.NonRetryableStatusDoesNotTripBreaker
        breaker = _fresh_breaker("test:non-retryable")

        @resilient_http(breaker_key=breaker.key, policy=_TEST_POLICY)
        async def _call() -> None:
            raise _make_status_error(401)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await _call()
        assert exc_info.value.response.status_code == 401
        # Breaker counter MUST be unchanged for a non-availability failure.
        assert breaker.consecutive_failures == 0
        assert breaker.state == "closed"

    async def test_open_breaker_short_circuits(self) -> None:
        # Spec: ResilientDecorator.OpenBreakerShortCircuits
        breaker = _fresh_breaker("test:open-sc")
        # Force the breaker into open state by recording threshold failures.
        await breaker.record_failure(_make_status_error(503))
        await breaker.record_failure(_make_status_error(503))
        # Set cooldown far in the future so admission is rejected.
        # cooldown_seconds=0 means it would re-admit immediately; freeze it:
        from datetime import UTC, datetime, timedelta

        breaker._st.next_probe_at = datetime.now(UTC) + timedelta(seconds=60)
        assert breaker.state == "open"

        invoked = {"n": 0}

        @resilient_http(breaker_key=breaker.key, policy=_TEST_POLICY)
        async def _call() -> str:
            invoked["n"] += 1
            return "should not be called"

        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await _call()
        assert invoked["n"] == 0
        assert exc_info.value.breaker_key == "test:open-sc"

    async def test_terminal_retry_exhaustion_raises_original(self) -> None:
        # Spec: ResilientDecorator.TerminalRetryExhaustion
        breaker = _fresh_breaker("test:exhaust")

        @resilient_http(breaker_key=breaker.key, policy=_TEST_POLICY)
        async def _call() -> None:
            raise _make_status_error(503)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await _call()
        # Crucial: NOT a tenacity.RetryError.
        import tenacity

        assert not isinstance(exc_info.value, tenacity.RetryError)
        assert exc_info.value.response.status_code == 503

    async def test_retries_429_with_backoff(self) -> None:
        # Spec: ResilientDecorator.Retries429
        breaker = _fresh_breaker("test:429")
        attempts = {"n": 0}

        @resilient_http(breaker_key=breaker.key, policy=_TEST_POLICY)
        async def _call() -> str:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise _make_status_error(429)
            return "ok"

        result = await _call()
        assert result == "ok"
        assert breaker.state == "closed"

    async def test_async_retry_does_not_block_event_loop(self) -> None:
        # Spec: ResilientDecorator.AsyncRetryUsesAsyncSleep
        # Use a real (small) base_delay so the wait actually triggers
        # asyncio.sleep instead of being jittered to ~0.
        slow_policy = RetryPolicy(
            max_attempts=2,
            base_delay_s=0.05,
            max_delay_s=0.05,
            jitter_factor=0.0,
            retryable_status_codes=DEFAULT_HTTP_RETRY_POLICY.retryable_status_codes,
            retryable_exceptions=DEFAULT_HTTP_RETRY_POLICY.retryable_exceptions,
        )
        breaker = _fresh_breaker("test:async")

        @resilient_http(breaker_key=breaker.key, policy=slow_policy)
        async def _failing_call() -> None:
            raise _make_status_error(503)

        # Set up a side task that should make progress during the retry delay.
        progress = {"ticks": 0}

        async def _ticker() -> None:
            for _ in range(5):
                await asyncio.sleep(0.01)
                progress["ticks"] += 1

        ticker_task = asyncio.create_task(_ticker())
        with pytest.raises(httpx.HTTPStatusError):
            await _failing_call()
        # Make sure the ticker has had a chance to advance.
        await ticker_task
        assert progress["ticks"] >= 3

    async def test_write_timeout_is_retried(self) -> None:
        # Spec: ResilientDecorator.WriteTimeoutRetried
        breaker = _fresh_breaker("test:write-timeout")
        attempts = {"n": 0}

        @resilient_http(breaker_key=breaker.key, policy=_TEST_POLICY)
        async def _call() -> str:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.WriteTimeout("simulated write timeout")
            return "ok"

        result = await _call()
        assert result == "ok"
        assert breaker.state == "closed"
