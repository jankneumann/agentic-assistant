"""Per-harness ToolSpec adapters (spec ``tool-spec``).

Renders :class:`~assistant.core.toolspec.ToolSpec` to each harness's
native tool shape. Adapters are **pure renderings**: given N specs they
return exactly N rendered tools in the same order — they never filter,
re-order, re-aggregate, or re-wrap the tool set. Aggregation and
telemetry wrapping happen once, upstream, in ``ToolPolicy``
(``assistant.core.capabilities.tools``).

Three renderings ship in P17 ``mcp-server-exposure``:

- :func:`render_langchain_tools` — ``StructuredTool`` for
  LangChain-native harnesses (DeepAgents). The spec's JSON-Schema
  ``input_schema`` is passed as the dict-form ``args_schema``
  (supported since langchain-core 0.3); argument validation is owned
  by the ToolSpec handler itself, not by the rendering.
- :func:`render_msaf_tools` — ``agent_framework.FunctionTool`` for the
  MS Agent Framework harness (``input_model`` accepts a JSON-Schema
  mapping natively).
- :func:`render_mcp_tools` — ``mcp.types.Tool`` listing entries for
  the served MCP surface. Because ToolSpec is MCP-shaped this is a
  field-for-field copy, no translation layer.

Migration passthrough: items that are not ``ToolSpec`` instances pass
through unchanged. This keeps injected native tools (test fakes,
host-supplied tools) working while every in-tree source now emits
ToolSpec; the passthrough preserves count and order so the
"adapters do not change the tool set" contract holds either way.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from assistant.core.toolspec import ToolSpec


def render_langchain_tool(spec: ToolSpec) -> StructuredTool:
    """Render one ToolSpec as a LangChain ``StructuredTool``.

    Name, description, and argument schema match the spec fields;
    invoking the rendered tool calls ``spec.handler``.
    """
    return StructuredTool.from_function(
        coroutine=spec.handler,
        name=spec.name,
        description=spec.description,
        args_schema=spec.input_schema,
    )


def render_langchain_tools(specs: list[Any]) -> list[Any]:
    """Render a ToolSpec list to StructuredTools (N in → N out, ordered)."""
    return [
        render_langchain_tool(s) if isinstance(s, ToolSpec) else s
        for s in specs
    ]


def _msaf_function_tool_cls() -> Any:
    try:
        from agent_framework import FunctionTool
    except ImportError as exc:  # pragma: no cover — dependency is pinned
        raise RuntimeError(
            "render_msaf_tools: failed to import "
            "agent_framework.FunctionTool. Install with "
            "`pip install 'agent-framework-core>=1.10,<2.0'`."
        ) from exc
    return FunctionTool


def render_msaf_tool(spec: ToolSpec) -> Any:
    """Render one ToolSpec as an ``agent_framework.FunctionTool``.

    ``FunctionTool`` accepts a JSON-Schema mapping as ``input_model``,
    so the spec's ``input_schema`` flows through unchanged and the
    async handler is invoked directly by the SDK.
    """
    function_tool = _msaf_function_tool_cls()
    return function_tool(
        name=spec.name,
        description=spec.description,
        func=spec.handler,
        input_model=spec.input_schema,
    )


def render_msaf_tools(specs: list[Any]) -> list[Any]:
    """Render a ToolSpec list to MSAF FunctionTools (N in → N out, ordered)."""
    return [
        render_msaf_tool(s) if isinstance(s, ToolSpec) else s for s in specs
    ]


def render_mcp_tool(spec: ToolSpec) -> Any:
    """Render one ToolSpec as an ``mcp.types.Tool`` listing entry."""
    import mcp.types as mcp_types

    return mcp_types.Tool(
        name=spec.name,
        description=spec.description,
        inputSchema=spec.input_schema,
    )


def render_mcp_tools(specs: list[ToolSpec]) -> list[Any]:
    """Render a ToolSpec list to MCP Tool entries (N in → N out, ordered)."""
    return [render_mcp_tool(s) for s in specs]


__all__ = [
    "render_langchain_tool",
    "render_langchain_tools",
    "render_mcp_tool",
    "render_mcp_tools",
    "render_msaf_tool",
    "render_msaf_tools",
]
