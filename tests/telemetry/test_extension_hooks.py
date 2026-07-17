"""End-to-end tests for the single extension-tool aggregation site.

Per spec ``capability-resolver`` "Aggregated Extension Tools Are
Traced", the SINGLE aggregation site — the
``DefaultToolPolicy.authorized_tools`` loop in
``src/assistant/core/capabilities/tools.py`` — MUST call the shared
``wrap_extension_tool_specs`` helper so the wrapping policy stays in
one place. This file exercises the site with a fake extension and
verifies that invoking the resulting ToolSpec handlers (directly, and
through the LangChain rendering a harness would use) emits one
``trace_tool_call`` per call with ``tool_kind="extension"``.

The former second aggregation site
(``DeepAgentsHarness.create_agent``) was removed by the P17 tool-spec
migration — the harness consumes the already-wrapped list and renders
it via the per-harness adapter without re-wrapping.
"""

from __future__ import annotations

from typing import Any

import pytest

from assistant.core.toolspec import ToolSpec
from assistant.telemetry import factory
from assistant.telemetry.context import set_assistant_ctx


@pytest.fixture(autouse=True)
def _bind_ctx() -> None:
    set_assistant_ctx("personal", "assistant")


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


def _make_spec(name: str) -> ToolSpec:
    async def _handler(query: str) -> str:
        return f"hit:{query}"

    return ToolSpec(
        name=name,
        description="A tool.",
        input_schema=dict(_SCHEMA),
        handler=_handler,
        source="extension:gmail",
    )


class _FakeExtension:
    name = "gmail"

    def __init__(self, tool_names: list[str]) -> None:
        self._specs = [_make_spec(n) for n in tool_names]

    def tool_specs(self) -> list[ToolSpec]:
        return self._specs

    async def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# The single aggregation site: capabilities/tools.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_resolver_aggregation_wraps_each_tool(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """``DefaultToolPolicy.authorized_tools`` wraps every extension spec."""
    from assistant.core.capabilities.tools import DefaultToolPolicy

    _install_spy(monkeypatch, spy_provider)

    ext1 = _FakeExtension(["gmail.search", "gmail.send"])
    ext2 = _FakeExtension(["gmail.archive"])
    persona = type("P", (), {})()
    role = type("R", (), {"preferred_tools": []})()
    policy = DefaultToolPolicy()
    tools = policy.authorized_tools(persona, role, loaded_extensions=[ext1, ext2])
    assert len(tools) == 3

    # Invoke each — verify one trace per call with kind="extension".
    for t in tools:
        await t.handler(query="x")
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 3
    assert all(c["tool_kind"] == "extension" for c in calls)
    assert {c["tool_name"] for c in calls} == {
        "gmail.search",
        "gmail.send",
        "gmail.archive",
    }


def test_capability_resolver_imports_shared_helper() -> None:
    """Static check: tools.py imports wrap_extension_tool_specs.

    Spec capability-resolver "Helper is the single source of truth"
    requires the aggregation site to import the shared helper rather
    than constructing its own wrapping closure.
    """
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "assistant"
        / "core"
        / "capabilities"
        / "tools.py"
    )
    text = src.read_text()
    assert (
        "from assistant.telemetry.tool_wrap import wrap_extension_tool_specs"
        in text
    )


def test_deep_agents_does_not_rewrap_extension_tools() -> None:
    """The former second aggregation site is gone: deep_agents.py must
    not import any tool_wrap helper (spec capability-resolver — the
    tool policy is the sole tool aggregator)."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "assistant"
        / "harnesses"
        / "sdk"
        / "deep_agents.py"
    )
    text = src.read_text()
    assert "tool_wrap" not in text
    assert "render_langchain_tools" in text


# ---------------------------------------------------------------------------
# Harness path: rendered tools trace exactly once (no double wrapping)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rendered_authorized_tools_trace_exactly_once(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy
    from assistant.harnesses.tool_adapters import render_langchain_tools

    _install_spy(monkeypatch, spy_provider)
    ext = _FakeExtension(["gmail.search"])
    persona = type("P", (), {})()
    role = type("R", (), {"preferred_tools": []})()
    policy = DefaultToolPolicy()
    authorized = policy.authorized_tools(
        persona, role, loaded_extensions=[ext]
    )
    [rendered] = render_langchain_tools(authorized)
    out = await rendered.ainvoke({"query": "x"})
    assert out == "hit:x"
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "gmail.search"


# ---------------------------------------------------------------------------
# Spec: extension-registry "Tool metadata passthrough is preserved"
# ---------------------------------------------------------------------------


def test_aggregation_preserves_name_description_input_schema(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy

    _install_spy(monkeypatch, spy_provider)
    ext = _FakeExtension(["gmail.search"])
    persona = type("P", (), {})()
    role = type("R", (), {"preferred_tools": []})()
    policy = DefaultToolPolicy()
    [wrapped] = policy.authorized_tools(persona, role, loaded_extensions=[ext])
    assert wrapped.name == "gmail.search"
    assert wrapped.description == "A tool."
    assert wrapped.input_schema == _SCHEMA
