"""Cross-cutting dual-format parity test (D11 / task 7.5).

Each of the four real Microsoft 365 extensions emits its tools twice
— once as LangChain ``StructuredTool`` for the DeepAgents harness,
once as MSAF-compatible callables for the MSAgentFrameworkHarness.
The two formats are *siblings*, not derived from one another (D11),
so the only mechanical check that catches drift is a parametrized
parity test:

- Same number of tools across formats.
- Same tool names at the same index across formats.

The per-extension tests cover wire-shape semantics; this file is the
last-line defense against an extension author adding a tool to one
format and forgetting the other.

Risk this catches: the IMPL_REVIEW round-1 finding from PLAN_REVIEW
that motivated D11 — "if as_langchain_tools is updated but
as_ms_agent_tools forgets, one harness sees stale tools".
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.mocks.graph_client import MockGraphClient


def _build_extension(name: str) -> Any:
    """Construct a real extension instance with MockGraphClient injected."""
    from importlib import import_module

    mod = import_module(f"assistant.extensions.{name}")
    cls_name = {
        "ms_graph": "MsGraphExtension",
        "outlook": "OutlookExtension",
        "teams": "TeamsExtension",
        "sharepoint": "SharepointExtension",
    }[name]
    cls = getattr(mod, cls_name)
    return cls({}, client=MockGraphClient())


REAL_EXTENSION_NAMES: list[str] = [
    "ms_graph",
    "outlook",
    "teams",
    "sharepoint",
]


@pytest.mark.parametrize("name", REAL_EXTENSION_NAMES)
def test_dual_format_tool_count_parity(name: str) -> None:
    """Each real extension MUST emit the same number of tools per format.

    Spec scenario: ms-extensions / "Tool counts match across formats".
    """
    ext = _build_extension(name)
    langchain_tools = ext.as_langchain_tools()
    ms_agent_tools = ext.as_ms_agent_tools()
    assert len(langchain_tools) == len(ms_agent_tools), (
        f"{name}: tool count drift — "
        f"as_langchain_tools={len(langchain_tools)} "
        f"vs as_ms_agent_tools={len(ms_agent_tools)}. "
        "Adding a tool to one format MUST add it to the other (D11)."
    )


@pytest.mark.parametrize("name", REAL_EXTENSION_NAMES)
def test_dual_format_tool_name_parity_by_index(name: str) -> None:
    """Each real extension's tool names MUST match index-for-index.

    Spec scenario: ms-extensions / "Tool names match by index".

    LangChain ``StructuredTool`` exposes ``name`` directly. MSAF tools
    expose either an ``__ai_name__`` attribute (set by ``ai_function``
    or the project's fallback wrapper) or fall back to ``__name__``.
    """
    ext = _build_extension(name)
    langchain_tools = ext.as_langchain_tools()
    ms_agent_tools = ext.as_ms_agent_tools()

    for idx, (lc, msaf) in enumerate(
        zip(langchain_tools, ms_agent_tools, strict=True)
    ):
        lc_name = getattr(lc, "name", None)
        msaf_name = (
            getattr(msaf, "__ai_name__", None)
            or getattr(msaf, "name", None)
            or getattr(msaf, "__name__", None)
        )
        assert lc_name is not None, (
            f"{name}[{idx}]: LangChain tool has no `name` attribute"
        )
        assert msaf_name is not None, (
            f"{name}[{idx}]: MSAF tool has no resolvable name "
            "(checked __ai_name__, name, __name__)"
        )
        assert lc_name == msaf_name, (
            f"{name}[{idx}]: tool name drift — "
            f"LangChain={lc_name!r} vs MSAF={msaf_name!r}. "
            "Adding/renaming a tool in one format MUST update the "
            "other (D11)."
        )


@pytest.mark.parametrize("name", REAL_EXTENSION_NAMES)
def test_each_real_extension_yields_at_least_one_tool(name: str) -> None:
    """Real extensions MUST NOT return empty tool lists.

    Spec scenario: extension-registry / "ms_graph/teams/sharepoint/
    outlook no longer return empty tool lists" (the MODIFIED contract
    that distinguishes a real extension from a stub).
    """
    ext = _build_extension(name)
    assert len(ext.as_langchain_tools()) > 0, (
        f"{name}: as_langchain_tools returned empty — real extensions "
        "MUST expose at least one tool (post-P5 contract)"
    )
    assert len(ext.as_ms_agent_tools()) > 0, (
        f"{name}: as_ms_agent_tools returned empty — real extensions "
        "MUST expose at least one tool (post-P5 contract)"
    )
