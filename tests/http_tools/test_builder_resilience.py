"""Integration tests verifying ``builder._build_tool`` is wrapped with
``resilient_http`` correctly. Drives a fake httpx transport that returns
programmable status sequences.

Spec coverage: http-tools.HttpToolInvocationsAreResilient.{1,2,3,4}.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from assistant.core.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    get_circuit_breaker_registry,
)
from assistant.http_tools.builder import _build_tool
from assistant.http_tools.openapi import ParsedOperation


def _operation() -> ParsedOperation:
    """Minimal ParsedOperation for a GET /ping endpoint."""
    return ParsedOperation(
        method="GET",
        path="/ping",
        operation_id="ping",
        summary="ping",
        description="ping the backend",
        parameters=[],
        request_body_schema=None,
    )


def _fresh_breaker(key: str) -> CircuitBreaker:
    reg = get_circuit_breaker_registry()
    reg._breakers[key] = CircuitBreaker(
        key=key,
        failure_threshold=2,
        cooldown_seconds=0.0,
    )
    return reg._breakers[key]


class _SequenceTransport(httpx.AsyncBaseTransport):
    """Mock transport returning a programmable sequence of status codes."""

    def __init__(self, status_sequence: list[int]) -> None:
        self._sequence = list(status_sequence)
        self.calls = 0

    async def handle_async_request(
        self, request: httpx.Request,
    ) -> httpx.Response:
        self.calls += 1
        if not self._sequence:
            return httpx.Response(500, json={})
        status = self._sequence.pop(0)
        if 200 <= status < 300:
            return httpx.Response(status, json={"ok": True})
        return httpx.Response(
            status,
            json={"error": "synthetic"},
            headers={"Content-Type": "application/problem+json"},
        )


@pytest.mark.anyio
class TestBuilderResilience:
    @pytest.fixture
    def anyio_backend(self) -> str:
        return "asyncio"

    async def _build_test_tool(
        self,
        source_name: str,
        status_sequence: list[int],
    ) -> tuple[Any, _SequenceTransport, CircuitBreaker]:
        transport = _SequenceTransport(status_sequence)
        client = httpx.AsyncClient(transport=transport)
        breaker = _fresh_breaker(f"http_tools:{source_name}")
        tool = _build_tool(
            source_name=source_name,
            base_url="http://test",
            operation=_operation(),
            client=client,
            auth_headers={},
        )
        return tool, transport, breaker

    async def test_tool_retries_on_503_then_succeeds(self) -> None:
        # Spec: HttpToolInvocationsAreResilient.RetryOn503ThenSucceeds
        tool, transport, breaker = await self._build_test_tool(
            "backend-success", [503, 503, 200],
        )
        result = await tool.ainvoke({})
        assert result == {"ok": True}
        assert transport.calls == 3
        assert breaker.state == "closed"

    async def test_tool_fails_terminally_after_retries_exhausted(self) -> None:
        # Spec: HttpToolInvocationsAreResilient.FailsTerminallyAfterRetries
        tool, transport, breaker = await self._build_test_tool(
            "backend-fail", [503, 503, 503],
        )
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await tool.ainvoke({})
        # Crucial: NOT a tenacity.RetryError.
        import tenacity

        assert not isinstance(exc_info.value, tenacity.RetryError)
        assert transport.calls == 3
        # Breaker recorded ONE terminal failure, not one per retry.
        assert breaker.consecutive_failures == 1

    async def test_open_breaker_short_circuits_tool_call(self) -> None:
        # Spec: HttpToolInvocationsAreResilient.OpenBreakerShortCircuits
        tool, transport, breaker = await self._build_test_tool(
            "backend-circuit", [],
        )
        # Force the breaker open with a future cooldown.
        from datetime import UTC, datetime, timedelta

        await breaker.record_failure("seed1")
        await breaker.record_failure("seed2")
        breaker._st.next_probe_at = datetime.now(UTC) + timedelta(seconds=60)
        assert breaker.state == "open"
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await tool.ainvoke({})
        assert exc_info.value.breaker_key == "http_tools:backend-circuit"
        assert transport.calls == 0  # no HTTP request was sent

    async def test_4xx_does_not_trip_breaker(self) -> None:
        # Spec: HttpToolInvocationsAreResilient.4xxNotRetriedNoTrip
        tool, transport, breaker = await self._build_test_tool(
            "backend-401", [401],
        )
        with pytest.raises(httpx.HTTPStatusError):
            await tool.ainvoke({})
        assert transport.calls == 1
        assert breaker.consecutive_failures == 0
        assert breaker.state == "closed"
