"""Tests for ToolPolicy protocol — Task 1.9.

Covers: protocol conformance, DefaultToolPolicy behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _make_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


def _make_persona(
    extensions: list | None = None,
    tool_sources: dict | None = None,
) -> MagicMock:
    persona = MagicMock()
    persona.extensions = extensions or []
    persona.tool_sources = tool_sources or {}
    return persona


def _make_role(preferred_tools: list | None = None) -> MagicMock:
    role = MagicMock()
    role.preferred_tools = preferred_tools or []
    return role


def _make_extension(tools: list) -> MagicMock:
    ext = MagicMock()
    ext.as_langchain_tools.return_value = tools
    return ext


def test_stub_satisfies_protocol() -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy, ToolPolicy

    assert isinstance(DefaultToolPolicy(), ToolPolicy)


def test_all_tools_when_preferred_empty() -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy

    tool_a = _make_tool("tool_a")
    tool_b = _make_tool("tool_b")
    ext = _make_extension([tool_a, tool_b])

    policy = DefaultToolPolicy()
    persona = _make_persona()
    role = _make_role(preferred_tools=[])

    tools = policy.authorized_tools(persona, role, loaded_extensions=[ext])
    assert tool_a in tools
    assert tool_b in tools


def test_filtered_by_preferred_tools() -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy

    tool_a = _make_tool("tool_a")
    tool_b = _make_tool("tool_b")
    ext = _make_extension([tool_a, tool_b])

    policy = DefaultToolPolicy()
    persona = _make_persona()
    role = _make_role(preferred_tools=["tool_a"])

    tools = policy.authorized_tools(persona, role, loaded_extensions=[ext])
    assert tool_a in tools
    assert tool_b not in tools


def test_authorized_extensions() -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy

    ext1 = _make_extension([])
    ext2 = _make_extension([])

    policy = DefaultToolPolicy()
    persona = _make_persona()
    role = _make_role()

    exts = policy.authorized_extensions(persona, role, loaded_extensions=[ext1, ext2])
    assert ext1 in exts
    assert ext2 in exts


def test_manifest_includes_extension_metadata() -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy

    persona = _make_persona(
        extensions=[{"module": "gmail", "config": {"scopes": ["read"]}}]
    )
    role = _make_role()
    policy = DefaultToolPolicy()

    manifest = policy.export_tool_manifest(persona, role)
    assert "extensions" in manifest
    assert "gmail" in manifest["extensions"]


def test_manifest_includes_tool_sources() -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy

    persona = _make_persona(
        tool_sources={"backend": {"base_url_env": "URL"}}
    )
    role = _make_role()
    policy = DefaultToolPolicy()

    manifest = policy.export_tool_manifest(persona, role)
    assert "tool_sources" in manifest
    assert "backend" in manifest["tool_sources"]
