"""Integration tests for the resilient discovery path.

Spec coverage: http-tools.DiscoveryRetriesBeforeSkip.{1,2,3}.
"""

from __future__ import annotations

import json

import httpx
import pytest

from assistant.core.resilience import (
    CircuitBreaker,
    get_circuit_breaker_registry,
)
from assistant.http_tools.discovery import _fetch_openapi


def _fresh_breaker(key: str) -> CircuitBreaker:
    reg = get_circuit_breaker_registry()
    reg._breakers[key] = CircuitBreaker(
        key=key,
        failure_threshold=2,
        cooldown_seconds=0.0,
    )
    return reg._breakers[key]


_VALID_OPENAPI = {
    "openapi": "3.0.0",
    "info": {"title": "test", "version": "1"},
    "paths": {},
}


class _PathStatusTransport(httpx.AsyncBaseTransport):
    """Mock transport whose response depends on (path, call-count)."""

    def __init__(self, sequence: list[tuple[str, int]]) -> None:
        # Each entry is (path-substring, status_code). Returns the first
        # matching entry in order on every call.
        self._sequence = list(sequence)
        self.calls: list[tuple[str, int]] = []

    async def handle_async_request(
        self, request: httpx.Request,
    ) -> httpx.Response:
        path = request.url.path
        idx = next(
            (
                i
                for i, (substr, _) in enumerate(self._sequence)
                if substr in path
            ),
            None,
        )
        if idx is None:
            self.calls.append((path, 500))
            return httpx.Response(500)
        _substr, status = self._sequence.pop(idx)
        self.calls.append((path, status))
        if status == 200:
            return httpx.Response(
                200,
                content=json.dumps(_VALID_OPENAPI).encode(),
                headers={"Content-Type": "application/json"},
            )
        return httpx.Response(status)


@pytest.mark.anyio
class TestDiscoveryResilience:
    @pytest.fixture
    def anyio_backend(self) -> str:
        return "asyncio"

    async def test_discovery_retries_transient_503_before_skipping(self) -> None:
        # Spec: DiscoveryRetriesBeforeSkip.RetriesTransient503
        # Three 503s for /openapi.json followed by a 200. Should retry.
        _fresh_breaker("http_tools_discovery:disc-retry")
        transport = _PathStatusTransport(
            [
                ("/openapi.json", 503),
                ("/openapi.json", 503),
                ("/openapi.json", 200),
            ],
        )
        client = httpx.AsyncClient(transport=transport)
        result = await _fetch_openapi(
            client=client,
            base_url="http://test",
            auth_headers={},
            source_name="disc-retry",
        )
        assert result is not None
        assert result["info"]["title"] == "test"
        # max_attempts=3 in default policy → exactly 3 calls before success.
        assert len(transport.calls) == 3

    async def test_discovery_skips_after_exhausting_retries(self) -> None:
        # Spec: DiscoveryRetriesBeforeSkip.SkipsAfterExhausted
        _fresh_breaker("http_tools_discovery:disc-exhaust")
        transport = _PathStatusTransport(
            [
                ("/openapi.json", 503),
                ("/openapi.json", 503),
                ("/openapi.json", 503),
                ("/help", 503),
                ("/help", 503),
                ("/help", 503),
            ],
        )
        client = httpx.AsyncClient(transport=transport)
        result = await _fetch_openapi(
            client=client,
            base_url="http://test",
            auth_headers={},
            source_name="disc-exhaust",
        )
        # graceful skip — discovery returns None, does not raise.
        assert result is None

    async def test_discovery_treats_circuit_breaker_open_as_skip(self) -> None:
        # Spec: DiscoveryRetriesBeforeSkip.CircuitBreakerOpenIsSkip
        breaker = _fresh_breaker("http_tools_discovery:disc-cbe")
        # Force the breaker open with a future cooldown.
        from datetime import UTC, datetime, timedelta

        await breaker.record_failure("seed1")
        await breaker.record_failure("seed2")
        breaker._st.next_probe_at = datetime.now(UTC) + timedelta(seconds=60)
        assert breaker.state == "open"

        transport = _PathStatusTransport([])
        client = httpx.AsyncClient(transport=transport)
        result = await _fetch_openapi(
            client=client,
            base_url="http://test",
            auth_headers={},
            source_name="disc-cbe",
        )
        assert result is None
        # No HTTP request was made — short-circuited at the breaker.
        assert len(transport.calls) == 0
