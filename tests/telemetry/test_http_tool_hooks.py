"""Tests for HTTP tool tracing in ``http_tools/builder.py``.

Per spec ``http-tools`` "HTTP Tool Invocations Emit Observability
Span", every StructuredTool produced by ``_build_tool`` MUST be
wrapped so each invocation emits one ``trace_tool_call`` span with
``tool_kind="http"``. Authorization headers and other secrets in
error messages MUST flow through the sanitizer (req observability.5).

These tests use the spy provider + a stubbed httpx client so no real
HTTP traffic is made.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from assistant.http_tools.builder import _build_tool
from assistant.http_tools.openapi import ParsedOperation
from assistant.telemetry import factory
from assistant.telemetry.context import set_assistant_ctx
from assistant.telemetry.sanitize import sanitize


@pytest.fixture(autouse=True)
def _bind_ctx() -> None:
    set_assistant_ctx("personal", "assistant")


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


def _make_op(operation_id: str = "listIssues") -> ParsedOperation:
    return ParsedOperation(
        operation_id=operation_id,
        method="get",
        path="/issues",
        summary="List issues.",
        description="",
        parameters=[
            {
                "name": "query",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": "Search query.",
            }
        ],
        request_body_schema=None,
    )


def _make_client(handler: Any) -> httpx.AsyncClient:
    """Construct an httpx.AsyncClient with a MockTransport handler."""
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_http_tool_emits_trace_with_kind_http(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    _install_spy(monkeypatch, spy_provider)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"ok": True}, headers={"Content-Type": "application/json"}
        )

    async with _make_client(_handler) as client:
        tool = _build_tool(
            source_name="linear",
            base_url="https://api.example.com",
            operation=_make_op(),
            client=client,
            auth_headers={},
        )
        out = await tool.ainvoke({"query": "open"})
    assert out == {"ok": True}
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "linear:listIssues"
    assert calls[0]["tool_kind"] == "http"
    assert calls[0]["persona"] == "personal"
    assert calls[0]["role"] == "assistant"
    assert calls[0].get("error") is None


@pytest.mark.asyncio
async def test_http_tool_error_emits_trace_then_propagates(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    _install_spy(monkeypatch, spy_provider)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with _make_client(_handler) as client:
        tool = _build_tool(
            source_name="linear",
            base_url="https://api.example.com",
            operation=_make_op(),
            client=client,
            auth_headers={},
        )
        with pytest.raises(httpx.HTTPStatusError):
            await tool.ainvoke({"query": "open"})
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["tool_kind"] == "http"
    assert calls[0]["error"] == "HTTPStatusError"


def test_authorization_header_sanitization_in_error_string() -> None:
    """Spec http-tools "Authorization header does not leak into span metadata".

    The sanitizer is applied at the provider boundary; this test
    asserts the regex chain itself redacts ``Authorization: Bearer
    ...`` regardless of how an error message is later attached to a
    span.
    """
    raw = "boom: Authorization: Bearer eyJhbGciOi.signed"
    cleaned = sanitize(raw)
    # Order matters: "Authorization: Basic" runs before "Bearer", but the
    # input is "Authorization: Bearer ..." which the bare ``Bearer +``
    # rule catches.
    assert "Bearer REDACTED" in cleaned
    assert "eyJhbGciOi" not in cleaned
