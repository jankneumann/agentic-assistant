"""Tests for ``core/graph_client.py`` covering every spec scenario.

Uses ``respx`` to mock httpx at the wire level — no real Graph calls.
``MockMSALStrategy`` substitutes for the auth tier; per-test
``CircuitBreakerRegistry`` reset prevents breaker bleed across tests.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import pytest
import respx

from assistant.core.cloud_client import CloudGraphClient
from assistant.core.graph_client import (
    DEFAULT_TRUSTED_HOSTS,
    GraphAPIError,
    GraphClient,
    _normalize_path,
    _parse_retry_after,
)
from assistant.core.msal_auth import MSALAuthenticationError
from assistant.core.resilience import (
    CircuitBreakerRegistry,
    HealthState,
    get_circuit_breaker_registry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _MockStrategy:
    """Minimal ``MSALStrategy`` impl returning configurable tokens."""

    def __init__(self, *, tokens: list[str] | None = None) -> None:
        self.tokens = list(tokens or ["MOCK_TOKEN_VALUE"])
        self.calls: list[dict[str, Any]] = []
        self._idx = 0

    async def acquire_token(
        self,
        scopes: list[str],
        *,
        force_refresh: bool = False,
    ) -> str:
        self.calls.append({"scopes": scopes, "force_refresh": force_refresh})
        token = self.tokens[min(self._idx, len(self.tokens) - 1)]
        self._idx += 1
        return token


@pytest.fixture(autouse=True)
def _fresh_breaker_registry(monkeypatch: pytest.MonkeyPatch) -> CircuitBreakerRegistry:
    fresh = CircuitBreakerRegistry()
    monkeypatch.setattr("assistant.core.resilience._REGISTRY", fresh, raising=False)
    return fresh


@pytest.fixture
def strategy() -> _MockStrategy:
    return _MockStrategy()


@pytest.fixture
async def client(strategy: _MockStrategy):
    c = GraphClient(
        extension_name="outlook",
        strategy=strategy,
        scopes=["Mail.Read"],
    )
    yield c
    await c.aclose()


# ---------------------------------------------------------------------------
# Protocol satisfaction — Requirement: CloudGraphClient Protocol.
# ---------------------------------------------------------------------------


def test_graph_client_satisfies_protocol(strategy: _MockStrategy) -> None:
    """Spec: graph-client / "Custom GraphClient satisfies Protocol"."""
    c = GraphClient(extension_name="ms_graph", strategy=strategy)
    assert isinstance(c, CloudGraphClient)


# ---------------------------------------------------------------------------
# Constructor — Requirement: Microsoft Graph Custom Implementation.
# ---------------------------------------------------------------------------


def test_constructor_stores_extension_name_and_strategy(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Constructor stores extension_name and strategy"."""
    c = GraphClient(
        extension_name="outlook",
        strategy=strategy,
        scopes=["Mail.Read"],
    )
    assert c.extension_name == "outlook"
    assert c._strategy is strategy
    assert c._scopes == ["Mail.Read"]


# ---------------------------------------------------------------------------
# GET — Requirement: Microsoft Graph Custom Implementation.
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_attaches_bearer_header(
    client: GraphClient, strategy: _MockStrategy
) -> None:
    """Spec: graph-client / "GET request attaches Authorization Bearer header"."""
    route = respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "1"}]})
    )
    await client.get("/me/messages")
    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer MOCK_TOKEN_VALUE"


@respx.mock
async def test_get_returns_parsed_json_body(client: GraphClient) -> None:
    """Spec: graph-client / "GET request returns parsed JSON body"."""
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "1"}]})
    )
    result = await client.get("/me/messages")
    assert result == {"value": [{"id": "1"}]}


# ---------------------------------------------------------------------------
# POST — Requirement: Microsoft Graph Custom Implementation.
# ---------------------------------------------------------------------------


@respx.mock
async def test_post_sends_json_body_and_returns_dict(client: GraphClient) -> None:
    """Spec: graph-client / "POST request sends JSON body and returns parsed response"."""
    route = respx.post("https://graph.microsoft.com/v1.0/me/sendMail").mock(
        return_value=httpx.Response(201, json={"id": "msg-1"})
    )
    result = await client.post(
        "/me/sendMail", json={"message": {"subject": "x"}}
    )
    assert result == {"id": "msg-1"}
    assert route.called
    req = route.calls.last.request
    assert req.headers["Content-Type"].startswith("application/json")
    import json as _json
    assert _json.loads(req.content) == {"message": {"subject": "x"}}


# ---------------------------------------------------------------------------
# Pagination — Requirement: OData Pagination.
# ---------------------------------------------------------------------------


@respx.mock
async def test_paginate_yields_until_no_nextlink(client: GraphClient) -> None:
    """Spec: graph-client / "Paginate yields successive pages until nextLink absent"."""
    page1 = {
        "value": [{"id": "1"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=25",
    }
    page2 = {"value": [{"id": "2"}]}
    # Order: more-specific (params) first, so it matches before the
    # general route catches the same URL prefix.
    respx.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        params={"$skip": "25"},
    ).mock(return_value=httpx.Response(200, json=page2))
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json=page1)
    )
    pages = [p async for p in client.paginate("/me/messages")]
    assert len(pages) == 2
    assert "@odata.nextLink" not in pages[1]


@respx.mock
async def test_paginate_preserves_bearer_on_nextlink(
    client: GraphClient, strategy: _MockStrategy
) -> None:
    """Spec: graph-client / "nextLink chase preserves header and base URL"."""
    page1 = {
        "value": [{"id": "1"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=25",
    }
    page2 = {"value": [{"id": "2"}]}
    r2 = respx.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        params={"$skip": "25"},
    ).mock(return_value=httpx.Response(200, json=page2))
    r1 = respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json=page1)
    )
    [_ async for _ in client.paginate("/me/messages")]
    assert r1.calls.last.request.headers["Authorization"] == "Bearer MOCK_TOKEN_VALUE"
    assert r2.calls.last.request.headers["Authorization"] == "Bearer MOCK_TOKEN_VALUE"


# ---------------------------------------------------------------------------
# Page-ceiling — Requirement: Pagination Page Ceiling Raises Instead of Truncating.
# ---------------------------------------------------------------------------


@respx.mock
async def test_paginate_raises_on_page_ceiling(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Page ceiling raises rather than terminates silently"."""
    c = GraphClient(
        extension_name="outlook", strategy=strategy, page_ceiling=2
    )
    page_loop = {
        "value": [{"id": "x"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=25",
    }
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json=page_loop)
    )
    respx.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        params={"$skip": "25"},
    ).mock(return_value=httpx.Response(200, json=page_loop))

    pages: list[dict[str, Any]] = []
    with pytest.raises(GraphAPIError) as ei:
        async for page in c.paginate("/me/messages"):
            pages.append(page)
    assert ei.value.error_code == "page_ceiling_exceeded"
    assert len(pages) == 2
    await c.aclose()


@respx.mock
async def test_page_ceiling_is_configurable(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Page ceiling is configurable"."""
    c = GraphClient(
        extension_name="outlook", strategy=strategy, page_ceiling=5
    )
    page_loop = {
        "value": [{"id": "x"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=25",
    }
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json=page_loop)
    )
    respx.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        params={"$skip": "25"},
    ).mock(return_value=httpx.Response(200, json=page_loop))

    pages: list[dict[str, Any]] = []
    with pytest.raises(GraphAPIError):
        async for page in c.paginate("/me/messages"):
            pages.append(page)
    assert len(pages) == 5
    await c.aclose()


# ---------------------------------------------------------------------------
# Cross-domain redirect rejection — Requirement: Cross-Domain Redirect Rejection.
# ---------------------------------------------------------------------------


@respx.mock
async def test_paginate_follows_trusted_host(client: GraphClient) -> None:
    """Spec: graph-client / "Pagination nextLink to graph.microsoft.com is followed"."""
    page1 = {
        "value": [{"id": "1"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=10",
    }
    page2 = {"value": [{"id": "2"}]}
    respx.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        params={"$skip": "10"},
    ).mock(return_value=httpx.Response(200, json=page2))
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json=page1)
    )
    pages = [p async for p in client.paginate("/me/messages")]
    assert len(pages) == 2


@respx.mock
async def test_paginate_rejects_untrusted_host(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Pagination nextLink to non-trusted host is rejected"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    page1 = {
        "value": [{"id": "1"}],
        "@odata.nextLink": "https://attacker.example.com/exfiltrate?token=abc",
    }
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json=page1)
    )
    # No mock for attacker.example.com — assertion that we never call it.
    pages: list[dict[str, Any]] = []
    with pytest.raises(GraphAPIError) as ei:
        async for page in c.paginate("/me/messages"):
            pages.append(page)
    assert ei.value.error_code == "invalid_redirect"
    # Bearer must NOT have been sent to attacker host.
    attacker_calls = [
        call
        for call in respx.calls
        if "attacker.example.com" in str(call.request.url)
    ]
    assert not attacker_calls
    await c.aclose()


@respx.mock
async def test_paginate_rejects_non_https_scheme(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Pagination nextLink with non-https scheme is rejected"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    page1 = {
        "value": [{"id": "1"}],
        "@odata.nextLink": "http://graph.microsoft.com/v1.0/me/messages?$skip=10",
    }
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json=page1)
    )
    with pytest.raises(GraphAPIError) as ei:
        async for _ in c.paginate("/me/messages"):
            pass
    assert ei.value.error_code == "invalid_redirect"
    assert "non-https" in str(ei.value).lower() or "scheme" in str(ei.value).lower()
    await c.aclose()


@respx.mock
async def test_3xx_response_is_not_followed(client: GraphClient) -> None:
    """Spec: graph-client / "HTTP 3xx response is not auto-followed"."""
    respx.get("https://graph.microsoft.com/v1.0/me").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://attacker.example.com/"}
        )
    )
    # 302 is treated as non-2xx → GraphAPIError surfaces; no follow.
    with pytest.raises(GraphAPIError) as ei:
        await client.get("/me")
    # Status code carried through.
    assert ei.value.response.status_code == 302
    # Bearer was NOT sent to attacker.
    attacker_calls = [
        call
        for call in respx.calls
        if "attacker.example.com" in str(call.request.url)
    ]
    assert not attacker_calls


# ---------------------------------------------------------------------------
# Resilience integration — Requirement: Resilience Integration.
# ---------------------------------------------------------------------------


@respx.mock
async def test_breaker_key_per_extension(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Breaker key derived from extension_name"."""
    c = GraphClient(extension_name="teams", strategy=strategy)
    assert c._breaker_key == "graph:teams"
    # Same registry returns the same breaker.
    breaker = get_circuit_breaker_registry().get_breaker("graph:teams")
    assert breaker.key == "graph:teams"
    await c.aclose()


@respx.mock
async def test_breaker_open_on_one_extension_does_not_affect_other(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Breaker open on one extension does not affect another"."""
    # Open the outlook breaker by recording 5 failures.
    outlook_breaker = get_circuit_breaker_registry().get_breaker("graph:outlook")
    for _ in range(5):
        await outlook_breaker.record_failure(RuntimeError("transient"))
    assert outlook_breaker.state == "open"

    # teams breaker is independent.
    teams_client = GraphClient(extension_name="teams", strategy=strategy)
    respx.get("https://graph.microsoft.com/v1.0/me").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    result = await teams_client.get("/me")
    assert result == {"id": "1"}
    await teams_client.aclose()


# ---------------------------------------------------------------------------
# Auth refresh — Requirement: Authentication Token Refresh on 401.
# ---------------------------------------------------------------------------


@respx.mock
async def test_401_triggers_force_refresh_and_retries(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "401 response triggers force_refresh and retry"."""
    strategy.tokens = ["TKN_OLD", "TKN_NEW"]
    c = GraphClient(extension_name="outlook", strategy=strategy)
    route = respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        side_effect=[
            httpx.Response(
                401,
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
                json={"error": {"code": "InvalidAuthenticationToken"}},
            ),
            httpx.Response(200, json={"value": [{"id": "1"}]}),
        ]
    )
    result = await c.get("/me/messages")
    assert result == {"value": [{"id": "1"}]}
    assert route.call_count == 2
    # second call carried the refreshed token.
    assert route.calls[-1].request.headers["Authorization"] == "Bearer TKN_NEW"
    # strategy was called with force_refresh=True.
    refresh_calls = [c for c in strategy.calls if c["force_refresh"]]
    assert refresh_calls, "expected one force_refresh call"
    await c.aclose()


@respx.mock
async def test_second_401_propagates_as_msal_error(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Second 401 propagates as MSALAuthenticationError"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        side_effect=[
            httpx.Response(
                401,
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            ),
            httpx.Response(
                401,
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            ),
        ]
    )
    with pytest.raises(MSALAuthenticationError):
        await c.get("/me/messages")
    await c.aclose()


# ---------------------------------------------------------------------------
# Error sanitization — Requirement: Error Sanitization on GraphAPIError.
# ---------------------------------------------------------------------------


@respx.mock
async def test_non2xx_raises_graph_api_error(client: GraphClient) -> None:
    """Spec: graph-client / "Non-2xx response raises GraphAPIError with status_code"."""
    respx.get("https://graph.microsoft.com/v1.0/me").mock(
        return_value=httpx.Response(
            403,
            json={"error": {"code": "Authorization_RequestDenied", "message": "no"}},
        )
    )
    with pytest.raises(GraphAPIError) as ei:
        await client.get("/me")
    err = ei.value
    assert err.response.status_code == 403
    assert err.error_code == "Authorization_RequestDenied"


def test_bearer_token_redacted_in_error_string() -> None:
    """Spec: graph-client / "Authorization header value is sanitized in error string"."""
    request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me")
    response = httpx.Response(500, request=request)
    err = GraphAPIError(
        message="upstream 500: Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.something",
        request=request,
        response=response,
    )
    rendered = str(err)
    assert "eyJ0eXAi" not in rendered
    assert "JWT-REDACTED" in rendered or "Bearer REDACTED" in rendered


def test_upn_local_redacted_in_error_string() -> None:
    """Spec: graph-client / "Parent-class URL is sanitized in error string"."""
    url = "https://graph.microsoft.com/v1.0/users/alice@example.com/messages"
    request = httpx.Request("GET", url)
    response = httpx.Response(404, request=request)
    err = GraphAPIError(
        message="not found",
        request=request,
        response=response,
    )
    rendered = str(err)
    # "alice@" portion must not survive.
    assert "alice@example.com" not in rendered
    # Domain may stay; placeholder must appear.
    assert "<upn_local>@example.com" in rendered or "<upn_local>" in rendered
    # The path's "messages" segment is preserved.
    assert "messages" in rendered


# ---------------------------------------------------------------------------
# GraphAPIError subclasses httpx.HTTPStatusError — Requirement.
# ---------------------------------------------------------------------------


def test_graph_api_error_is_httpx_status_error() -> None:
    """Spec: graph-client / "GraphAPIError is an httpx.HTTPStatusError"."""
    request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me")
    response = httpx.Response(500, request=request)
    err = GraphAPIError(
        message="boom", request=request, response=response, error_code="Z"
    )
    assert isinstance(err, httpx.HTTPStatusError)
    assert err.response.status_code == 500


@respx.mock
async def test_5xx_triggers_p9_retry(strategy: _MockStrategy) -> None:
    """Spec: graph-client / "5xx GraphAPIError triggers P9 retry"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    route = respx.get("https://graph.microsoft.com/v1.0/me").mock(
        side_effect=[
            httpx.Response(502, json={"error": {"code": "Bad"}}),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    result = await c.get("/me")
    assert result == {"id": "1"}
    assert route.call_count == 2
    await c.aclose()


# ---------------------------------------------------------------------------
# Health check — Requirement: Health Check Reports Breaker State.
# ---------------------------------------------------------------------------


async def test_health_check_closed_breaker_returns_ok(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "CLOSED breaker yields OK HealthStatus"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    health = await c.health_check()
    assert health.state == HealthState.OK
    assert health.breaker_key == "graph:outlook"
    await c.aclose()


async def test_health_check_open_breaker_returns_unavailable(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "OPEN breaker yields UNAVAILABLE HealthStatus"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    breaker = get_circuit_breaker_registry().get_breaker("graph:outlook")
    for _ in range(5):
        await breaker.record_failure(RuntimeError("transient"))
    health = await c.health_check()
    assert health.state == HealthState.UNAVAILABLE
    await c.aclose()


# ---------------------------------------------------------------------------
# Retry-After — Requirement: Retry-After Honoring on 429 and 503.
# ---------------------------------------------------------------------------


def test_parse_retry_after_delta_seconds() -> None:
    assert _parse_retry_after("5") == 5.0
    assert _parse_retry_after("0") == 0.0
    assert _parse_retry_after("-1") is None


def test_parse_retry_after_http_date_in_future() -> None:
    # Far future date — exact value not asserted, only "positive".
    val = _parse_retry_after("Wed, 21 Oct 2099 07:28:00 GMT")
    assert val is not None
    assert val > 0


def test_parse_retry_after_http_date_in_past() -> None:
    """Spec: graph-client / "Past HTTP-date Retry-After falls through to default backoff"."""
    val = _parse_retry_after("Wed, 21 Oct 2020 07:28:00 GMT")
    assert val is None


def test_parse_retry_after_malformed_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec: graph-client / "Malformed Retry-After is logged and ignored"."""
    import logging

    caplog.set_level(logging.WARNING, logger="assistant.graph_client")
    val = _parse_retry_after("not-a-number-or-date")
    assert val is None
    assert any("malformed Retry-After" in rec.message for rec in caplog.records)


def test_parse_retry_after_absent() -> None:
    """Spec: graph-client / "429 without Retry-After falls through to default backoff"."""
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None


@respx.mock
async def test_429_with_retry_after_delays_retry(
    strategy: _MockStrategy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: graph-client / "429 with delta-seconds Retry-After delays retry"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    sleeps: list[float] = []

    real_sleep = asyncio.sleep

    async def spy_sleep(delay: float) -> None:
        sleeps.append(delay)
        # Don't actually wait the indicated time — just record.
        await real_sleep(0)

    monkeypatch.setattr("assistant.core.graph_client.asyncio.sleep", spy_sleep)

    respx.get("https://graph.microsoft.com/v1.0/me").mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "5"},
                json={"error": {"code": "TooManyRequests"}},
            ),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    result = await c.get("/me")
    assert result == {"id": "1"}
    # We honored Retry-After: should have observed at least one sleep with
    # value >= 5.0 (capped at 60s).
    assert any(s >= 5.0 for s in sleeps), f"sleeps={sleeps}"
    await c.aclose()


# ---------------------------------------------------------------------------
# Per-request timeouts — Requirement: Per-Request Timeout Configuration.
# ---------------------------------------------------------------------------


def test_default_timeout_values(strategy: _MockStrategy) -> None:
    """Spec: graph-client / "Default timeout values applied"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    timeout = c._client.timeout
    assert timeout.connect == 10.0
    assert timeout.read == 30.0
    assert timeout.write == 30.0
    assert timeout.pool == 5.0


@respx.mock
async def test_read_timeout_raises_graph_api_error(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Read timeout raises GraphAPIError"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    respx.get("https://graph.microsoft.com/v1.0/me").mock(
        side_effect=httpx.ReadTimeout("simulated read timeout")
    )
    with pytest.raises(GraphAPIError) as ei:
        await c.get("/me")
    assert ei.value.status_code is None
    assert "read timeout" in ei.value.message.lower()
    await c.aclose()


# ---------------------------------------------------------------------------
# Empty-body handling — Requirement: Empty-Body Handling for 202 and 204.
# ---------------------------------------------------------------------------


@respx.mock
async def test_202_empty_body_returns_empty_dict(client: GraphClient) -> None:
    """Spec: graph-client / "202 empty body returns empty dict"."""
    respx.post("https://graph.microsoft.com/v1.0/me/sendMail").mock(
        return_value=httpx.Response(202, content=b"")
    )
    result = await client.post("/me/sendMail", json={"x": 1})
    assert result == {}


@respx.mock
async def test_204_empty_body_returns_empty_dict(client: GraphClient) -> None:
    """Spec: graph-client / "204 empty body returns empty dict"."""
    respx.get("https://graph.microsoft.com/v1.0/me").mock(
        return_value=httpx.Response(204, content=b"")
    )
    result = await client.get("/me")
    assert result == {}


@respx.mock
async def test_200_zero_length_body_returns_empty_dict(client: GraphClient) -> None:
    """Spec: graph-client / "200 with empty JSON-Content-Type body returns empty dict"."""
    respx.get("https://graph.microsoft.com/v1.0/me").mock(
        return_value=httpx.Response(
            200, content=b"", headers={"Content-Type": "application/json"}
        )
    )
    result = await client.get("/me")
    assert result == {}


# ---------------------------------------------------------------------------
# retry_safe — Requirement: Per-Method Retry Safety Control.
# ---------------------------------------------------------------------------


@respx.mock
async def test_retry_safe_false_does_not_retry(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "retry_safe=False bypasses P9 retry"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    route = respx.post("https://graph.microsoft.com/v1.0/me/sendMail").mock(
        return_value=httpx.Response(503, json={"error": {"code": "ServerBusy"}})
    )
    with pytest.raises(GraphAPIError):
        await c.post("/me/sendMail", json={"x": 1}, retry_safe=False)
    assert route.call_count == 1
    # Breaker should record the failure.
    breaker = get_circuit_breaker_registry().get_breaker("graph:outlook")
    assert breaker.consecutive_failures >= 1
    await c.aclose()


@respx.mock
async def test_retry_safe_true_retries(strategy: _MockStrategy) -> None:
    """Spec: graph-client / "retry_safe=True (default) retries on 5xx"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    route = respx.post("https://graph.microsoft.com/v1.0/me/messages").mock(
        side_effect=[
            httpx.Response(502, json={"error": {"code": "Bad"}}),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    result = await c.post("/me/messages", json={"x": 1})
    assert result == {"id": "1"}
    assert route.call_count == 2
    await c.aclose()


# ---------------------------------------------------------------------------
# get_bytes — Requirement: Binary Download via get_bytes.
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_bytes_returns_metadata_dict(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Successful download returns path + metadata dict"."""
    c = GraphClient(extension_name="sharepoint", strategy=strategy)
    body = b"x" * 12345
    respx.get(
        "https://graph.microsoft.com/v1.0/me/drive/items/abc/content"
    ).mock(
        return_value=httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/pdf",
                "request-id": "rq-1",
            },
        )
    )
    result = await c.get_bytes("/me/drive/items/abc/content")
    assert os.path.exists(result["path"])
    assert os.path.getsize(result["path"]) == 12345
    assert result["size_bytes"] == 12345
    assert result["content_type"] == "application/pdf"
    assert result["request_id"] == "rq-1"
    os.unlink(result["path"])
    await c.aclose()


@respx.mock
async def test_get_bytes_aborts_on_size_exceeded(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Download exceeding max_bytes aborts with size_exceeded"."""
    c = GraphClient(extension_name="sharepoint", strategy=strategy)
    body = b"x" * 5000  # exceeds max_bytes=1024
    respx.get("https://graph.microsoft.com/v1.0/large").mock(
        return_value=httpx.Response(
            200, content=body, headers={"Content-Type": "application/octet-stream"}
        )
    )
    with pytest.raises(GraphAPIError) as ei:
        await c.get_bytes("/large", max_bytes=1024)
    assert ei.value.error_code == "size_exceeded"
    await c.aclose()


# ---------------------------------------------------------------------------
# Lifecycle — Requirement: HTTP Client Lifecycle and Resource Cleanup.
# ---------------------------------------------------------------------------


async def test_async_context_closes_underlying_httpx_client(
    strategy: _MockStrategy,
) -> None:
    """Spec: graph-client / "Async context-manager closes the underlying httpx client"."""
    async with GraphClient(extension_name="outlook", strategy=strategy) as c:
        inner = c._client
        assert not inner.is_closed
    assert inner.is_closed


async def test_explicit_aclose_closes_client(strategy: _MockStrategy) -> None:
    """Spec: graph-client / "Explicit aclose closes the underlying httpx client"."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    inner = c._client
    await c.aclose()
    assert inner.is_closed


async def test_aclose_is_idempotent(strategy: _MockStrategy) -> None:
    """The Protocol mandates idempotent close so caller cleanup never raises."""
    c = GraphClient(extension_name="outlook", strategy=strategy)
    await c.aclose()
    await c.aclose()  # second call MUST NOT raise


# ---------------------------------------------------------------------------
# Path normalization — Requirement: Transport-Level Observability Span per Request.
# ---------------------------------------------------------------------------


def test_normalize_path_redacts_id_segments() -> None:
    """Spec: graph-client / "Path normalization redacts message_id-shaped segments"."""
    p = _normalize_path("/me/messages/AAMkAGI1this-is-a-long-id-here")
    assert "AAMkAGI1" not in p
    assert "{message_id}" in p


def test_normalize_path_preserves_short_segments() -> None:
    p = _normalize_path("/me/messages")
    assert p == "/me/messages"


def test_normalize_path_redacts_guid() -> None:
    p = _normalize_path("/users/12345678-1234-1234-1234-123456789012/messages")
    assert "{message_id}" in p


# ---------------------------------------------------------------------------
# Trusted hosts default — Requirement: Cross-Domain Redirect Rejection.
# ---------------------------------------------------------------------------


def test_default_trusted_hosts_set(strategy: _MockStrategy) -> None:
    c = GraphClient(extension_name="outlook", strategy=strategy)
    assert "graph.microsoft.com" in c._trusted_hosts
    assert "graph.microsoft.us" in c._trusted_hosts
    assert "microsoftgraph.chinacloudapi.cn" in c._trusted_hosts
    # Old sunset cloud is NOT in default.
    assert "graph.microsoft.de" not in DEFAULT_TRUSTED_HOSTS


def test_trusted_hosts_overridable(strategy: _MockStrategy) -> None:
    c = GraphClient(
        extension_name="outlook",
        strategy=strategy,
        trusted_hosts=["custom.example.com"],
    )
    assert c._trusted_hosts == ("custom.example.com",)
