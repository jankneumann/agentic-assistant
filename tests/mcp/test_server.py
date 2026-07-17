"""Unit tests for the MCP server surface (P17 mcp-server-exposure).

Covers ask-tool construction (one per role + generic ask), session
multiplexing semantics over the SessionRegistry (fresh / reuse /
reject-unknown), and tool-name sanitization. Transport-level behavior
(tools/list + tools/call over streamable HTTP) is covered by
``tests/web/test_mcp_mount.py``.
"""

from __future__ import annotations

import pytest

from assistant.core.toolspec import ToolSpec
from assistant.mcp.server import (
    MCP_PATH,
    build_ask_tool_specs,
    build_mcp_state,
    sanitize_tool_name,
)
from tests.a2a.helpers import (
    FakeHarness,
    fixture_persona,
    fixture_roles,
    text_events,
)


def _state(events=None):
    created: list[FakeHarness] = []

    async def _session_factory(role_cfg):
        harness = FakeHarness(events=list(events or text_events("ok")))
        harness.role_name = role_cfg.name  # type: ignore[attr-defined]
        created.append(harness)
        agent = await harness.create_agent([], [])
        return harness, agent

    state = build_mcp_state(
        fixture_persona(),
        fixture_roles(),
        session_factory=_session_factory,
        default_role="coder",
    )
    return state, created


# ── tool construction ────────────────────────────────────────────────


def test_one_ask_tool_per_role_plus_generic_ask() -> None:
    state, _ = _state()
    names = [s.name for s in state.tool_specs]
    assert names == ["ask_coder", "ask_researcher", "ask"]
    assert all(isinstance(s, ToolSpec) for s in state.tool_specs)
    assert all(s.source == "mcp:serve" for s in state.tool_specs)


def test_ask_tools_declare_message_required_context_optional() -> None:
    state, _ = _state()
    for spec in state.tool_specs:
        assert spec.input_schema["required"] == ["message"]
        assert "context_id" in spec.input_schema["properties"]


def test_generic_ask_shares_default_role_registry() -> None:
    roles = fixture_roles()
    registries = {}
    state, _ = _state()
    # build_ask_tool_specs is deterministic over the same registries.
    registries = state.registries
    specs = build_ask_tool_specs(roles, registries, default_role="coder")
    assert [s.name for s in specs] == ["ask_coder", "ask_researcher", "ask"]


def test_sanitize_tool_name_maps_to_mcp_charset() -> None:
    assert sanitize_tool_name("my role.v2") == "my_role_v2"
    assert sanitize_tool_name("coder") == "coder"


def test_mcp_path_constant() -> None:
    assert MCP_PATH == "/mcp"


# ── session multiplexing through the ask handlers ────────────────────


@pytest.mark.asyncio
async def test_ask_without_context_creates_fresh_session() -> None:
    state, created = _state()
    ask = next(s for s in state.tool_specs if s.name == "ask")
    out1 = await ask.handler(message="hello")
    out2 = await ask.handler(message="again")
    assert out1["response"] == "ok"
    assert len(created) == 2  # one fresh session per contextless call
    assert out1["context_id"] != out2["context_id"]


@pytest.mark.asyncio
async def test_ask_with_known_context_reuses_the_session() -> None:
    state, created = _state()
    ask = next(s for s in state.tool_specs if s.name == "ask")
    first = await ask.handler(message="hello")
    second = await ask.handler(
        message="follow-up", context_id=first["context_id"]
    )
    assert second["context_id"] == first["context_id"]
    assert len(created) == 1
    assert created[0].invocations == ["hello", "follow-up"]


@pytest.mark.asyncio
async def test_ask_with_unknown_context_is_rejected() -> None:
    state, _ = _state()
    ask = next(s for s in state.tool_specs if s.name == "ask")
    with pytest.raises(ValueError, match="unknown context_id"):
        await ask.handler(message="hi", context_id="never-created")


@pytest.mark.asyncio
async def test_role_tools_use_role_bound_sessions() -> None:
    state, created = _state()
    ask_researcher = next(
        s for s in state.tool_specs if s.name == "ask_researcher"
    )
    await ask_researcher.handler(message="dig in")
    assert created[-1].role_name == "researcher"


@pytest.mark.asyncio
async def test_generic_ask_context_continues_via_default_role_tool() -> None:
    """ask and ask_<default-role> share one registry, so contexts are
    interchangeable between them."""
    state, created = _state()
    ask = next(s for s in state.tool_specs if s.name == "ask")
    ask_coder = next(s for s in state.tool_specs if s.name == "ask_coder")
    first = await ask.handler(message="hello")
    second = await ask_coder.handler(
        message="continue", context_id=first["context_id"]
    )
    assert second["context_id"] == first["context_id"]
    assert len(created) == 1
