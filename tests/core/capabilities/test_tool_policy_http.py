"""Tests for ``DefaultToolPolicy`` integration with ``HttpToolRegistry`` — Task 7.1.

Covers the tool-policy spec MODIFIED requirement scenarios:
- HTTP tools merged with extension tools.
- ``preferred_tools`` filter works across both sources by exact name
  match against either the extension tool's ``name`` or the HTTP tool's
  ``"{source}:{op_id}"`` registry key.
- ``http_tool_registry=None`` preserves pre-P3 extension-only behavior.
- ``export_tool_manifest`` includes an ``"http_tools"`` key when a
  registry was supplied.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from assistant.core.capabilities.tools import DefaultToolPolicy
from assistant.http_tools import HttpToolRegistry


class _EmptyArgs(BaseModel):
    """Minimal args schema — not exercised at runtime."""


def _make_http_tool(name: str) -> StructuredTool:
    """Build a ``StructuredTool`` whose ``name`` equals the registry key."""

    async def _noop(**_: object) -> None:  # pragma: no cover - unused
        return None

    return StructuredTool.from_function(
        coroutine=_noop,
        name=name,
        description=f"HTTP tool {name}",
        args_schema=_EmptyArgs,
    )


def _make_ext_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


def _make_extension(tools: list) -> MagicMock:
    ext = MagicMock()
    ext.as_langchain_tools.return_value = tools
    return ext


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


# ── 7.1a authorized_tools merges both sources ────────────────────────


def test_http_registry_merged_into_authorized_tools() -> None:
    """Extension tools and HTTP registry tools are both returned."""
    registry = HttpToolRegistry()
    http_a = _make_http_tool("backend:list_items")
    http_b = _make_http_tool("backend:create_item")
    registry.register("backend", "list_items", http_a)
    registry.register("backend", "create_item", http_b)

    ext_tool = _make_ext_tool("ext_tool_a")
    extension = _make_extension([ext_tool])

    policy = DefaultToolPolicy(http_tool_registry=registry)
    persona = _make_persona()
    role = _make_role(preferred_tools=[])

    tools = policy.authorized_tools(
        persona, role, loaded_extensions=[extension]
    )

    assert ext_tool in tools
    assert http_a in tools
    assert http_b in tools
    assert len(tools) == 3


# ── 7.1b preferred_tools filter spans extensions + registry ──────────


def test_preferred_tools_filters_across_sources() -> None:
    """``preferred_tools`` filters by exact name across both sources."""
    registry = HttpToolRegistry()
    http_list = _make_http_tool("backend:list_items")
    http_create = _make_http_tool("backend:create_item")
    registry.register("backend", "list_items", http_list)
    registry.register("backend", "create_item", http_create)

    ext_a = _make_ext_tool("ext_tool_a")
    ext_b = _make_ext_tool("ext_tool_b")
    extension = _make_extension([ext_a, ext_b])

    policy = DefaultToolPolicy(http_tool_registry=registry)
    persona = _make_persona()
    role = _make_role(preferred_tools=["backend:list_items", "ext_tool_a"])

    tools = policy.authorized_tools(
        persona, role, loaded_extensions=[extension]
    )

    assert ext_a in tools
    assert http_list in tools
    assert ext_b not in tools
    assert http_create not in tools
    assert len(tools) == 2


# ── 7.1c None registry preserves prior behavior ──────────────────────


def test_none_registry_preserves_prior_behavior() -> None:
    """With ``http_tool_registry=None`` only extension tools are returned."""
    ext_a = _make_ext_tool("tool_a")
    ext_b = _make_ext_tool("tool_b")
    extension = _make_extension([ext_a, ext_b])

    policy = DefaultToolPolicy(http_tool_registry=None)
    persona = _make_persona()
    role = _make_role(preferred_tools=[])

    tools = policy.authorized_tools(
        persona, role, loaded_extensions=[extension]
    )

    assert tools == [ext_a, ext_b]


def test_default_construction_preserves_prior_behavior() -> None:
    """Default ``DefaultToolPolicy()`` (no kwarg) still works pre-P3."""
    ext_a = _make_ext_tool("tool_a")
    extension = _make_extension([ext_a])

    policy = DefaultToolPolicy()
    persona = _make_persona()
    role = _make_role(preferred_tools=[])

    tools = policy.authorized_tools(
        persona, role, loaded_extensions=[extension]
    )

    assert tools == [ext_a]


# ── 7.1d manifest export includes http_tools ─────────────────────────


def test_export_tool_manifest_includes_http_tools() -> None:
    """Manifest carries ``http_tools`` entries when a registry is supplied."""
    registry = HttpToolRegistry()
    registry.register(
        "backend", "list_items", _make_http_tool("backend:list_items")
    )
    registry.register(
        "backend", "create_item", _make_http_tool("backend:create_item")
    )

    policy = DefaultToolPolicy(http_tool_registry=registry)
    persona = _make_persona(
        extensions=[{"module": "gmail", "config": {}}],
        tool_sources={"backend": {"base_url_env": "URL"}},
    )
    role = _make_role()

    manifest = policy.export_tool_manifest(persona, role)

    assert "http_tools" in manifest
    entries = manifest["http_tools"]
    assert isinstance(entries, list)
    names = [e["name"] for e in entries]
    assert "backend:list_items" in names
    assert "backend:create_item" in names
    # Pre-existing keys are preserved.
    assert "extensions" in manifest
    assert "tool_sources" in manifest


def test_manifest_omits_http_tools_when_registry_none() -> None:
    """Without a registry the manifest omits ``http_tools`` (or empty)."""
    policy = DefaultToolPolicy()
    persona = _make_persona(
        extensions=[{"module": "gmail", "config": {}}],
    )
    role = _make_role()

    manifest = policy.export_tool_manifest(persona, role)

    # Per spec: key may be absent or mapped to an empty list.
    assert manifest.get("http_tools", []) == []
