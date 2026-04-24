"""Integration tests for :mod:`assistant.http_tools.discovery`.

Uses ``pytest-httpserver`` to exercise the full HTTP stack — discovery
fetches the OpenAPI document over real sockets, parses it, builds
tools, and applies the D9 security posture (timeout, no-redirect,
10 MiB cap, credential redaction in logs).

Covers the "HTTP Tool Discovery" and "HTTP Client Security Posture"
requirement scenarios.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pytest_httpserver import HTTPServer

from assistant.http_tools.discovery import discover_tools


@pytest.fixture
async def client() -> Any:
    """Shared httpx client mirroring the D9 posture (short read timeout)."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(2.0, connect=1.0),
        follow_redirects=False,
        verify=True,
    ) as c:
        yield c


# ── Successful discovery builds registry ─────────────────────────────


async def test_successful_discovery_builds_registry(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    load_fixture: Callable[[str], dict[str, Any]],
) -> None:
    """GET /openapi.json returns v3.1 fixture → three tools registered."""
    spec = load_fixture("sample_openapi_v3_1.json")
    httpserver.expect_request("/openapi.json").respond_with_json(spec)

    registry = await discover_tools(
        {"backend": {"base_url": httpserver.url_for(""), "auth_header": None}},
        client=client,
    )
    names = sorted(t.name for t in registry.list_all())
    assert names == ["backend:create_item", "backend:get_item", "backend:list_items"]


# ── 404 on /openapi.json → fallback to /help ─────────────────────────


async def test_openapi_404_falls_back_to_help(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    load_fixture: Callable[[str], dict[str, Any]],
) -> None:
    spec = load_fixture("sample_openapi_v3_1.json")
    httpserver.expect_request("/openapi.json").respond_with_data("", status=404)
    httpserver.expect_request("/help").respond_with_json(spec)

    registry = await discover_tools(
        {"backend": {"base_url": httpserver.url_for(""), "auth_header": None}},
        client=client,
    )
    assert len(registry) == 3


# ── Source 5xx → skipped with warning, others succeed ────────────────


async def test_source_5xx_skipped_with_warning(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    load_fixture: Callable[[str], dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    spec = load_fixture("sample_openapi_v3_1.json")
    # Single server: /api/openapi.json returns 500, /api2/openapi.json OK.
    httpserver.expect_request("/api/openapi.json").respond_with_data("x", status=500)
    httpserver.expect_request("/api/help").respond_with_data("x", status=500)
    httpserver.expect_request("/api2/openapi.json").respond_with_json(spec)

    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.discovery"):
        registry = await discover_tools(
            {
                "broken": {"base_url": httpserver.url_for("/api"), "auth_header": None},
                "good": {"base_url": httpserver.url_for("/api2"), "auth_header": None},
            },
            client=client,
        )
    assert sorted(t.name for t in registry.list_all()) == [
        "good:create_item", "good:get_item", "good:list_items",
    ]
    assert any(
        "broken" in rec.getMessage() and rec.levelname == "WARNING"
        for rec in caplog.records
    )


# ── Invalid JSON → skipped with warning ──────────────────────────────


async def test_invalid_json_skipped(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    httpserver.expect_request("/openapi.json").respond_with_data(
        "not json", content_type="application/json",
    )
    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.discovery"):
        registry = await discover_tools(
            {"s": {"base_url": httpserver.url_for(""), "auth_header": None}},
            client=client,
        )
    assert len(registry) == 0
    assert any("invalid JSON" in rec.getMessage() for rec in caplog.records)


# ── No tool_sources → empty registry (no-op) ─────────────────────────


async def test_no_tool_sources_returns_empty_registry(
    client: httpx.AsyncClient,
) -> None:
    registry = await discover_tools({}, client=client)
    assert len(registry) == 0


# ── Swagger 2.0 → skipped with warning ───────────────────────────────


async def test_swagger_2_0_skipped(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    load_fixture: Callable[[str], dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    spec = load_fixture("sample_swagger_v2_0.json")
    httpserver.expect_request("/openapi.json").respond_with_json(spec)

    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.discovery"):
        registry = await discover_tools(
            {"legacy": {"base_url": httpserver.url_for(""), "auth_header": None}},
            client=client,
        )
    assert len(registry) == 0
    messages = " ".join(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert "legacy" in messages
    assert "2.0" in messages or "swagger" in messages.lower()


# ── Missing auth env var → source skipped with warning ───────────────


async def test_missing_auth_env_skipped(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    load_fixture: Callable[[str], dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth resolution that raises KeyError → source omitted with warning."""
    monkeypatch.delenv("UNSET_DISCOVERY_VAR", raising=False)
    spec = load_fixture("sample_openapi_v3_1.json")
    httpserver.expect_request("/openapi.json").respond_with_json(spec)

    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.discovery"):
        registry = await discover_tools(
            {
                "broken": {
                    "base_url": httpserver.url_for(""),
                    "auth_header": {"type": "bearer", "env": "UNSET_DISCOVERY_VAR"},
                },
            },
            client=client,
        )
    assert len(registry) == 0
    messages = " ".join(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert "broken" in messages
    assert "UNSET_DISCOVERY_VAR" in messages


# ── Redirect refused (D9) ────────────────────────────────────────────


async def test_redirect_refused(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """3xx responses are treated as failed discovery (follow_redirects=False)."""
    httpserver.expect_request("/openapi.json").respond_with_data(
        "", status=302, headers={"Location": "http://attacker.example.com/fake.json"},
    )
    httpserver.expect_request("/help").respond_with_data(
        "", status=302, headers={"Location": "http://attacker.example.com/fake.json"},
    )
    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.discovery"):
        registry = await discover_tools(
            {"s": {"base_url": httpserver.url_for(""), "auth_header": None}},
            client=client,
        )
    assert len(registry) == 0
    assert any(
        "redirect" in rec.getMessage().lower() or "status 302" in rec.getMessage()
        for rec in caplog.records
    )


# ── Oversized response → skipped (D9 10 MiB cap) ─────────────────────


async def test_oversized_response_skipped(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 11 MiB blob
    big = b"{" + b" " * (11 * 1024 * 1024) + b"}"
    httpserver.expect_request("/openapi.json").respond_with_data(
        big, content_type="application/json",
    )
    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.discovery"):
        registry = await discover_tools(
            {"s": {"base_url": httpserver.url_for(""), "auth_header": None}},
            client=client,
        )
    assert len(registry) == 0
    assert any("10MiB" in rec.getMessage() for rec in caplog.records)


# ── Timeout → skipped (D9) ───────────────────────────────────────────


async def test_timeout_skipped(
    httpserver: HTTPServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A slow endpoint past the client's read timeout → skipped."""
    import time

    def _slow(request: Any) -> Any:
        from werkzeug.wrappers import Response
        time.sleep(3.0)  # longer than 1s test timeout below
        return Response("{}", content_type="application/json")

    httpserver.expect_request("/openapi.json").respond_with_handler(_slow)

    # Use a tight, scoped client so the sleep definitely exceeds it.
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(1.0, connect=1.0),
        follow_redirects=False,
    ) as tight_client:
        with caplog.at_level(logging.WARNING, logger="assistant.http_tools.discovery"):
            registry = await discover_tools(
                {"slow": {"base_url": httpserver.url_for(""), "auth_header": None}},
                client=tight_client,
            )
    assert len(registry) == 0
    assert any(
        "slow" in rec.getMessage() and "timeout" in rec.getMessage().lower()
        for rec in caplog.records
    )


# ── Auth header value absent from logs (D9 credential redaction) ─────


async def test_auth_value_absent_from_logs(
    client: httpx.AsyncClient,
    httpserver: HTTPServer,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warning logs MUST NOT leak the bearer token value or the word 'Bearer'."""
    monkeypatch.setenv("TEST_DISCOVERY_TOKEN", "s3cr3t-t0k3n-DO-NOT-LEAK")
    # Trigger a failure so WARNINGs are emitted.
    httpserver.expect_request("/openapi.json").respond_with_data("x", status=500)
    httpserver.expect_request("/help").respond_with_data("x", status=500)

    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.discovery"):
        await discover_tools(
            {
                "s": {
                    "base_url": httpserver.url_for(""),
                    "auth_header": {"type": "bearer", "env": "TEST_DISCOVERY_TOKEN"},
                },
            },
            client=client,
        )
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "s3cr3t-t0k3n-DO-NOT-LEAK" not in joined
    assert "Bearer" not in joined
