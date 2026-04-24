"""Unit tests for :mod:`assistant.http_tools.builder`.

Covers the "Tool Builder" Requirement scenarios from
``specs/http-tools/spec.md`` including POST/GET, content-type gate,
empty-body 204, tool naming, URL-encoded path parameters,
required/optional/typeless field handling, and invocation-side
security propagation.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pytest_httpserver import HTTPServer

from assistant.http_tools.builder import (
    _build_tool,
    _json_schema_to_python_type,
)
from assistant.http_tools.openapi import ParsedOperation


def _op(**kwargs: Any) -> ParsedOperation:
    """Build a ParsedOperation with sensible defaults."""
    return ParsedOperation(
        method=kwargs.pop("method", "get"),
        path=kwargs.pop("path", "/x"),
        operation_id=kwargs.pop("operation_id", "op"),
        parameters=kwargs.pop("parameters", []),
        request_body_schema=kwargs.pop("request_body_schema", None),
        summary=kwargs.pop("summary", "A test operation"),
        description=kwargs.pop("description", ""),
    )


@pytest.fixture
async def client() -> Any:
    """Shared httpx client mirroring the D9 posture."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(5.0, connect=2.0),
        follow_redirects=False,
        verify=True,
    ) as c:
        yield c


# ── POST with JSON body ──────────────────────────────────────────────


async def test_post_with_json_body(
    client: httpx.AsyncClient, httpserver: HTTPServer,
) -> None:
    """POST /items invoked with args is sent as JSON body."""
    httpserver.expect_request(
        "/items", method="POST", json={"name": "widget", "quantity": 3},
    ).respond_with_json({"ok": True})

    op = _op(
        method="post", path="/items", operation_id="create_item",
        request_body_schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
            },
        },
    )
    tool = _build_tool(
        source_name="backend", base_url=httpserver.url_for(""),
        operation=op, client=client, auth_headers={},
    )
    result = await tool.coroutine(name="widget", quantity=3)
    assert result == {"ok": True}


# ── GET with path + query ────────────────────────────────────────────


async def test_get_with_path_and_query(
    client: httpx.AsyncClient, httpserver: HTTPServer,
) -> None:
    """GET /items/{id}?verbose=true builds the correct URL."""
    httpserver.expect_request(
        "/items/42", method="GET", query_string="verbose=true",
    ).respond_with_json({"id": "42"})

    op = _op(
        method="get", path="/items/{id}", operation_id="get_item",
        parameters=[
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "verbose", "in": "query", "schema": {"type": "boolean", "default": False}},
        ],
    )
    tool = _build_tool(
        source_name="backend", base_url=httpserver.url_for(""),
        operation=op, client=client, auth_headers={},
    )
    result = await tool.coroutine(id="42", verbose=True)
    assert result == {"id": "42"}


# ── 5xx raises HTTPStatusError ───────────────────────────────────────


async def test_5xx_raises_http_status_error(
    client: httpx.AsyncClient, httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/fail", method="GET").respond_with_data(
        "boom", status=500,
    )
    op = _op(method="get", path="/fail", operation_id="fail_op")
    tool = _build_tool(
        source_name="backend", base_url=httpserver.url_for(""),
        operation=op, client=client, auth_headers={},
    )
    with pytest.raises(httpx.HTTPStatusError):
        await tool.coroutine()


# ── Non-JSON content-type raises ValueError ──────────────────────────


async def test_non_json_content_type_raises(
    client: httpx.AsyncClient, httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/html", method="GET").respond_with_data(
        "<html></html>", content_type="text/html",
    )
    op = _op(method="get", path="/html", operation_id="html_op")
    tool = _build_tool(
        source_name="backend", base_url=httpserver.url_for(""),
        operation=op, client=client, auth_headers={},
    )
    with pytest.raises(ValueError, match="non-JSON"):
        await tool.coroutine()


# ── 204 empty body returns None ──────────────────────────────────────


async def test_204_returns_none(
    client: httpx.AsyncClient, httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/nothing", method="DELETE").respond_with_data(
        "", status=204,
    )
    op = _op(method="delete", path="/nothing", operation_id="delete_op")
    tool = _build_tool(
        source_name="backend", base_url=httpserver.url_for(""),
        operation=op, client=client, auth_headers={},
    )
    assert await tool.coroutine() is None


# ── Tool name = {source}:{op_id} ─────────────────────────────────────


def test_tool_name_matches_registry_key(client: httpx.AsyncClient) -> None:
    op = _op(method="get", path="/x", operation_id="list_items")
    tool = _build_tool(
        source_name="backend", base_url="http://example.com",
        operation=op, client=client, auth_headers={},
    )
    assert tool.name == "backend:list_items"


# ── Path parameter URL-encoded ───────────────────────────────────────


async def test_path_param_url_encoded() -> None:
    """``foo/bar`` in a path param is encoded to ``foo%2Fbar`` on the wire.

    Uses ``httpx.MockTransport`` rather than ``pytest-httpserver`` because
    werkzeug URL-decodes request paths before the matcher runs, making
    it impossible to assert on the encoded form via the server side.
    """
    captured: dict[str, Any] = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler),
        follow_redirects=False,
    ) as mock_client:
        op = _op(
            method="get", path="/items/{id}", operation_id="get_item",
            parameters=[
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
            ],
        )
        tool = _build_tool(
            source_name="backend", base_url="http://example.com",
            operation=op, client=mock_client, auth_headers={},
        )
        await tool.coroutine(id="foo/bar")

    assert captured["url"] == "http://example.com/items/foo%2Fbar"


# ── Required / Optional / Typeless field handling ────────────────────


def test_required_field_is_required(client: httpx.AsyncClient) -> None:
    op = _op(
        method="post", path="/x", operation_id="op",
        request_body_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
    )
    from pydantic import ValidationError

    tool = _build_tool(
        source_name="s", base_url="http://e",
        operation=op, client=client, auth_headers={},
    )
    with pytest.raises(ValidationError):
        tool.args_schema(**{})  # type: ignore[misc]


def test_optional_field_uses_declared_default(client: httpx.AsyncClient) -> None:
    op = _op(
        method="post", path="/x", operation_id="op",
        request_body_schema={
            "type": "object",
            "properties": {"n": {"type": "integer", "default": 7}},
        },
    )
    tool = _build_tool(
        source_name="s", base_url="http://e",
        operation=op, client=client, auth_headers={},
    )
    model = tool.args_schema()  # type: ignore[misc,call-arg]
    assert model.n == 7  # type: ignore[attr-defined]


def test_typeless_field_is_any(client: httpx.AsyncClient) -> None:
    """Schema with neither ``type`` nor ``$ref`` → ``Any``-typed field."""
    py_type = _json_schema_to_python_type({})
    assert py_type is Any  # type: ignore[comparison-overlap]


# ── Invocation-side security propagation ─────────────────────────────


async def test_oversized_response_raises(
    client: httpx.AsyncClient, httpserver: HTTPServer,
) -> None:
    """Body > 10 MiB raises ``ValueError`` via the streaming cap."""
    # 11 MiB of JSON-ish bytes
    big = b'{"x":"' + b"a" * (11 * 1024 * 1024) + b'"}'
    httpserver.expect_request("/big", method="GET").respond_with_data(
        big, content_type="application/json",
    )
    op = _op(method="get", path="/big", operation_id="big_op")
    tool = _build_tool(
        source_name="backend", base_url=httpserver.url_for(""),
        operation=op, client=client, auth_headers={},
    )
    with pytest.raises(ValueError, match="10MiB"):
        await tool.coroutine()


async def test_redirect_response_raises(
    client: httpx.AsyncClient, httpserver: HTTPServer,
) -> None:
    """3xx responses raise ``HTTPStatusError`` (follow_redirects=False)."""
    httpserver.expect_request("/moved", method="GET").respond_with_data(
        "", status=302, headers={"Location": "http://attacker.example.com/"},
    )
    op = _op(method="get", path="/moved", operation_id="moved_op")
    tool = _build_tool(
        source_name="backend", base_url=httpserver.url_for(""),
        operation=op, client=client, auth_headers={},
    )
    with pytest.raises(httpx.HTTPStatusError):
        await tool.coroutine()
