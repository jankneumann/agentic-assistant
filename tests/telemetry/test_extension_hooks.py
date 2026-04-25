"""End-to-end tests for the two extension-tool aggregation sites.

Per spec ``capability-resolver`` "Aggregated Extension Tools Are
Traced", both aggregation sites MUST call the shared
``wrap_extension_tools`` helper so the wrapping policy stays in one
place. This file exercises both sites with a fake extension and
verifies that invoking the resulting tools emits one
``trace_tool_call`` per call with ``tool_kind="extension"``.

Aggregation sites:

1. ``src/assistant/core/capabilities/tools.py`` — the
   ``DefaultToolPolicy.authorized_tools`` loop.
2. ``src/assistant/harnesses/sdk/deep_agents.py`` —
   ``DeepAgentsHarness.create_agent`` ext-tool aggregation.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from assistant.telemetry import factory
from assistant.telemetry.context import set_assistant_ctx


@pytest.fixture(autouse=True)
def _bind_ctx() -> None:
    set_assistant_ctx("personal", "assistant")


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


class _Args(BaseModel):
    query: str = Field(..., description="Query.")


def _make_tool(name: str) -> StructuredTool:
    async def _coro(query: str) -> str:
        return f"hit:{query}"

    return StructuredTool.from_function(
        coroutine=_coro, name=name, description="A tool.", args_schema=_Args
    )


class _FakeExtension:
    name = "gmail"

    def __init__(self, tool_names: list[str]) -> None:
        self._tools = [_make_tool(n) for n in tool_names]

    def as_langchain_tools(self) -> list[StructuredTool]:
        return self._tools

    def as_ms_agent_tools(self) -> list[Any]:
        return []

    async def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Aggregation site 1: capabilities/tools.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_resolver_aggregation_wraps_each_tool(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """``DefaultToolPolicy.authorized_tools`` wraps every extension tool."""
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
        await t.ainvoke({"query": "x"})
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 3
    assert all(c["tool_kind"] == "extension" for c in calls)
    assert {c["tool_name"] for c in calls} == {
        "gmail.search",
        "gmail.send",
        "gmail.archive",
    }


def test_capability_resolver_imports_shared_helper() -> None:
    """Static check: tools.py imports wrap_extension_tools (single source).

    Spec capability-resolver "Helper is the single source of truth"
    requires both aggregation sites to import the shared helper rather
    than constructing their own wrapping closures.
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
    assert "from assistant.telemetry.tool_wrap import wrap_extension_tools" in text


# ---------------------------------------------------------------------------
# Aggregation site 2: harnesses/sdk/deep_agents.py
# ---------------------------------------------------------------------------


def test_deep_agents_imports_shared_helper() -> None:
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
    assert "from assistant.telemetry.tool_wrap import wrap_extension_tools" in text


# ---------------------------------------------------------------------------
# Spec: extension-registry "Tool metadata passthrough is preserved"
# ---------------------------------------------------------------------------


def test_aggregation_preserves_name_description_args_schema(
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
    assert wrapped.args_schema is _Args
