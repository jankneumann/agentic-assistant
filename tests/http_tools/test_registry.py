"""Unit tests for :mod:`assistant.http_tools.registry`.

Covers the "HttpToolRegistry API" requirement — deterministic ordering,
`by_source`, `by_preferred`, and the `tool_key` helper.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from assistant.http_tools.registry import HttpToolRegistry, tool_key


class _EmptyArgs(BaseModel):
    """Minimal args schema for tools under test."""


def _make_tool(name: str) -> StructuredTool:
    """Build a trivial ``StructuredTool`` whose ``name`` is the registry key.

    The tool's coroutine is never invoked in these tests — it exists only
    so the registry has a real ``StructuredTool`` to hold.
    """

    async def _noop(**kwargs: object) -> None:  # pragma: no cover - unused
        return None

    return StructuredTool.from_function(
        coroutine=_noop,
        name=name,
        description=f"Tool {name}",
        args_schema=_EmptyArgs,
    )


# ── tool_key helper ──────────────────────────────────────────────────


def test_tool_key_formats_source_and_op() -> None:
    """``tool_key`` concatenates ``source:op_id`` verbatim."""
    assert tool_key("backend", "list_items") == "backend:list_items"


# ── list_all ─────────────────────────────────────────────────────────


def test_list_all_returns_tools_sorted_lexicographically() -> None:
    """``list_all()`` must return tools sorted by registry key.

    Spec scenario: "list_all returns every tool in key order".
    """
    reg = HttpToolRegistry()
    # Register in deliberately reversed order so a naive implementation
    # that returns insertion order would fail.
    reg.register("backend", "list_items", _make_tool("backend:list_items"))
    reg.register("analyzer", "summarize", _make_tool("analyzer:summarize"))

    out = reg.list_all()
    assert [t.name for t in out] == ["analyzer:summarize", "backend:list_items"]


def test_list_all_is_byte_identical_across_calls() -> None:
    """Repeated ``list_all()`` calls produce the same key ordering."""
    reg = HttpToolRegistry()
    reg.register("zeta", "z", _make_tool("zeta:z"))
    reg.register("alpha", "a", _make_tool("alpha:a"))
    reg.register("beta", "b", _make_tool("beta:b"))

    first = [t.name for t in reg.list_all()]
    second = [t.name for t in reg.list_all()]
    assert first == second == ["alpha:a", "beta:b", "zeta:z"]


# ── by_source ────────────────────────────────────────────────────────


def test_by_source_filters_by_source_name() -> None:
    """``by_source`` returns only tools whose key starts with ``source:``."""
    reg = HttpToolRegistry()
    reg.register("backend", "list_items", _make_tool("backend:list_items"))
    reg.register("backend", "create_item", _make_tool("backend:create_item"))
    reg.register("analyzer", "summarize", _make_tool("analyzer:summarize"))

    backend_tools = reg.by_source("backend")
    assert sorted(t.name for t in backend_tools) == [
        "backend:create_item",
        "backend:list_items",
    ]


def test_by_source_unknown_returns_empty() -> None:
    """Unknown source name yields an empty list, not an error."""
    reg = HttpToolRegistry()
    reg.register("backend", "x", _make_tool("backend:x"))
    assert reg.by_source("nope") == []


# ── by_preferred ─────────────────────────────────────────────────────


def test_by_preferred_filters_to_listed_keys_only() -> None:
    """``by_preferred`` returns exactly the tools whose keys appear in the iterable.

    Spec scenario: "by_preferred filters by exact key match".
    """
    reg = HttpToolRegistry()
    reg.register("backend", "list_items", _make_tool("backend:list_items"))
    reg.register("analyzer", "summarize", _make_tool("analyzer:summarize"))

    picked = reg.by_preferred(["analyzer:summarize"])
    assert [t.name for t in picked] == ["analyzer:summarize"]


def test_by_preferred_ignores_unknown_keys() -> None:
    """Unknown keys in ``preferred`` are silently dropped."""
    reg = HttpToolRegistry()
    reg.register("backend", "list_items", _make_tool("backend:list_items"))

    picked = reg.by_preferred(["backend:list_items", "ghost:none"])
    assert [t.name for t in picked] == ["backend:list_items"]


def test_by_preferred_empty_iterable_returns_empty() -> None:
    """Empty ``preferred`` → empty result (no-op filter)."""
    reg = HttpToolRegistry()
    reg.register("backend", "x", _make_tool("backend:x"))
    assert reg.by_preferred([]) == []
