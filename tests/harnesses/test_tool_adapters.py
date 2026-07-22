"""Tests for the per-harness ToolSpec adapters (spec ``tool-spec``).

Scenarios: "LangChain adapter renders a ToolSpec", "Adapters do not
change the tool set", plus the MSAF and MCP renderings added by P17
``mcp-server-exposure``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.tools import StructuredTool

from assistant.core.toolspec import ToolSpec
from assistant.harnesses.tool_adapters import (
    render_langchain_tool,
    render_langchain_tools,
    render_mcp_tool,
    render_mcp_tools,
    render_msaf_tool,
    render_msaf_tools,
)

_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


def _spec(name: str = "gmail.search", calls: list | None = None) -> ToolSpec:
    async def _handler(query: str) -> str:
        if calls is not None:
            calls.append(query)
        return f"hit:{query}"

    return ToolSpec(
        name=name,
        description=f"desc for {name}",
        input_schema=dict(_SCHEMA),
        handler=_handler,
        source="extension:gmail",
    )


# ── LangChain rendering ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_langchain_adapter_renders_fields_and_invokes_handler() -> None:
    calls: list[str] = []
    spec = _spec(calls=calls)
    tool = render_langchain_tool(spec)
    assert isinstance(tool, StructuredTool)
    assert tool.name == spec.name
    assert tool.description == spec.description
    assert tool.args_schema == spec.input_schema
    out = await tool.ainvoke({"query": "foo"})
    assert out == "hit:foo"
    assert calls == ["foo"]


# ── MSAF rendering ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_msaf_adapter_renders_function_tool_and_invokes_handler() -> None:
    from agent_framework import FunctionTool

    calls: list[str] = []
    spec = _spec(calls=calls)
    tool = render_msaf_tool(spec)
    assert isinstance(tool, FunctionTool)
    assert tool.name == spec.name
    assert tool.description == spec.description
    await tool.invoke(arguments={"query": "bar"})
    assert calls == ["bar"]


# ── MCP rendering ────────────────────────────────────────────────────


def test_mcp_adapter_renders_tool_listing_entry() -> None:
    import mcp.types as mcp_types

    spec = _spec()
    tool = render_mcp_tool(spec)
    assert isinstance(tool, mcp_types.Tool)
    assert tool.name == spec.name
    assert tool.description == spec.description
    assert tool.inputSchema == spec.input_schema


# ── Purity: N in → N out, same order, no filtering/re-wrapping ───────


@pytest.mark.parametrize(
    "render",
    [render_langchain_tools, render_msaf_tools],
)
def test_adapters_do_not_change_the_tool_set(render) -> None:
    specs = [_spec(name=f"t.{i}") for i in range(4)]
    rendered = render(list(specs))
    assert len(rendered) == 4
    assert [t.name for t in rendered] == [s.name for s in specs]


def test_mcp_adapter_does_not_change_the_tool_set() -> None:
    specs = [_spec(name=f"t.{i}") for i in range(3)]
    rendered = render_mcp_tools(specs)
    assert [t.name for t in rendered] == [s.name for s in specs]


@pytest.mark.parametrize(
    "render",
    [render_langchain_tools, render_msaf_tools],
)
def test_non_toolspec_items_pass_through_unchanged(render) -> None:
    """Migration passthrough: injected native tools keep flowing."""
    native = MagicMock(name="native_tool")
    spec = _spec()
    rendered = render([native, spec])
    assert rendered[0] is native
    assert rendered[1] is not spec  # rendered, not passed through
