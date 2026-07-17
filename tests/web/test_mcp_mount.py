"""make_app(enable_mcp=True) integration — MCP mounted alongside AG-UI.

Spec scenarios: mcp-server + web-server (P17 mcp-server-exposure).
Exercises the real streamable-HTTP transport (stateless, JSON
responses) end to end: tools/list, tools/call happy path, error
mapping (unknown tool / unknown context / schema violation), and
session multiplexing across requests.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from tests.a2a.helpers import (
    FakeHarness,
    fixture_persona,
    fixture_roles,
    text_events,
)

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


async def _trivial_agent_factory(
    harness: Any, pc: Any, rc: Any, persona_reg: Any, http_client: Any = None
) -> Any:
    return await harness.create_agent(tools=[], extensions=[])


@contextmanager
def _mcp_client(**make_app_kwargs):
    """Yield (client, created_harnesses) with the harness factory patched
    for the WHOLE client lifetime — MCP session factories run
    create_harness lazily per tools/call, so the patch must outlive app
    construction (same pattern as the A2A mount test)."""
    from assistant.web.app import make_app

    created: list[FakeHarness] = []

    def _harness_factory(persona, role, harness_name):
        harness = FakeHarness(events=text_events("ok"))
        created.append(harness)
        return harness

    pc = fixture_persona()
    roles = {r.name: r for r in fixture_roles()}

    with (
        patch("assistant.web.app.create_harness", side_effect=_harness_factory),
        patch("assistant.web.app.PersonaRegistry") as mock_pr,
        patch("assistant.web.app.RoleRegistry") as mock_rr,
    ):
        mock_pr.return_value.load.return_value = pc
        mock_pr.return_value.shutdown_extensions = AsyncMock()
        mock_rr.return_value.load.side_effect = (
            lambda name, persona: roles[name]
        )
        mock_rr.return_value.available_for_persona.return_value = list(roles)
        app = make_app(
            "fixture",
            "coder",
            "deep_agents",
            _agent_factory=_trivial_agent_factory,
            **make_app_kwargs,
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, created


def _rpc(client, method: str, params: dict | None = None, req_id: int = 1):
    return client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        },
    )


def _call_tool(client, name: str, arguments: dict, req_id: int = 2):
    resp = _rpc(
        client,
        "tools/call",
        {"name": name, "arguments": arguments},
        req_id=req_id,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


# ── tools/list ───────────────────────────────────────────────────────


def test_tools_list_exposes_one_ask_tool_per_role_plus_ask():
    with _mcp_client(enable_mcp=True) as (client, _):
        resp = _rpc(client, "tools/list")
        assert resp.status_code == 200, resp.text
        tools = resp.json()["result"]["tools"]
        names = [t["name"] for t in tools]
        assert names == ["ask_coder", "ask_researcher", "ask"]
        for t in tools:
            assert t["inputSchema"]["required"] == ["message"]
            assert "context_id" in t["inputSchema"]["properties"]


# ── tools/call happy path + session multiplexing ─────────────────────


def test_tools_call_happy_path_returns_response_and_context_id():
    with _mcp_client(enable_mcp=True) as (client, created):
        # Startup built exactly one (AG-UI) harness; MCP sessions are
        # created lazily per contextless call.
        assert len(created) == 1
        result = _call_tool(client, "ask_coder", {"message": "hello"})
        assert result["isError"] is False
        structured = result["structuredContent"]
        assert structured["response"] == "ok"
        assert len(created) == 2
        assert structured["context_id"] == created[1].thread_id
        assert created[1].invocations == ["hello"]
        # The AG-UI harness was untouched.
        assert created[0].invocations == []


def test_tools_call_with_context_id_continues_the_session():
    with _mcp_client(enable_mcp=True) as (client, created):
        first = _call_tool(client, "ask", {"message": "hello"})
        ctx = first["structuredContent"]["context_id"]
        second = _call_tool(
            client, "ask", {"message": "again", "context_id": ctx}, req_id=3
        )
        assert second["structuredContent"]["context_id"] == ctx
        # One MCP session total (plus the AG-UI harness at index 0).
        assert len(created) == 2
        assert created[1].invocations == ["hello", "again"]


def test_tools_call_distinct_contexts_use_distinct_sessions():
    with _mcp_client(enable_mcp=True) as (client, created):
        a = _call_tool(client, "ask", {"message": "one"})
        b = _call_tool(client, "ask", {"message": "two"}, req_id=3)
        assert (
            a["structuredContent"]["context_id"]
            != b["structuredContent"]["context_id"]
        )
        assert len(created) == 3  # AG-UI + two MCP sessions


# ── error mapping ────────────────────────────────────────────────────


def test_tools_call_unknown_tool_maps_to_tool_error():
    with _mcp_client(enable_mcp=True) as (client, _):
        result = _call_tool(client, "nope", {"message": "hi"})
        assert result["isError"] is True
        assert "unknown tool" in result["content"][0]["text"]


def test_tools_call_unknown_context_maps_to_tool_error():
    with _mcp_client(enable_mcp=True) as (client, created):
        result = _call_tool(
            client,
            "ask",
            {"message": "hi", "context_id": "never-created"},
        )
        assert result["isError"] is True
        assert "unknown context_id" in result["content"][0]["text"]
        # Rejection — no session was created for the unknown context.
        assert len(created) == 1


def test_tools_call_schema_violation_maps_to_tool_error():
    """The SDK validates arguments against inputSchema before dispatch."""
    with _mcp_client(enable_mcp=True) as (client, _):
        result = _call_tool(client, "ask", {})  # missing required message
        assert result["isError"] is True
        assert "message" in result["content"][0]["text"]


# ── mount composition ────────────────────────────────────────────────


def test_ag_ui_surface_still_live_with_mcp_enabled():
    with _mcp_client(enable_mcp=True) as (client, _):
        assert client.get("/health").status_code == 200


def test_mcp_mount_absent_by_default():
    with _mcp_client() as (client, _):
        resp = _rpc(client, "tools/list")
        assert resp.status_code == 404
