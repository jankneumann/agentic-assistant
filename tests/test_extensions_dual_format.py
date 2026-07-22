"""Cross-adapter rendering parity for extension ToolSpecs (P17).

Replaces the pre-P17 dual-format (D11) parity test: extensions no
longer author their tools twice. Each of the four real Microsoft 365
extensions emits a single ``tool_specs()`` list and the per-harness
adapters (``assistant.harnesses.tool_adapters``) render it to the
LangChain, MSAF, and MCP shapes. Drift between harnesses is now
impossible by construction — these tests pin the adapter contract
instead:

- Adapters are pure renderings: N specs in → N rendered tools out, in
  order (spec tool-spec / "Adapters do not change the tool set").
- Rendered names/descriptions match the ToolSpec fields across all
  three adapters (render equivalence with the old per-format outputs:
  the canonical ``<extension>.<verb>`` names are unchanged from the
  pre-migration ``as_langchain_tools`` / ``as_ms_agent_tools``
  surfaces).
- Real extensions MUST NOT return empty spec lists (extension-registry
  MODIFIED contract).
"""

from __future__ import annotations

from typing import Any

import pytest

from assistant.core.toolspec import ToolSpec
from assistant.harnesses.tool_adapters import (
    render_langchain_tools,
    render_mcp_tools,
    render_msaf_tools,
)
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

#: Canonical tool-name lists — unchanged from the pre-P17 dual-format
#: surfaces, so this doubles as the render-equivalence check against
#: the old ``as_langchain_tools()`` / ``as_ms_agent_tools()`` outputs.
EXPECTED_TOOL_NAMES: dict[str, list[str]] = {
    "ms_graph": [
        "ms_graph.search_people",
        "ms_graph.get_my_profile",
        "ms_graph.search_messages",
    ],
    "outlook": [
        "outlook.list_messages",
        "outlook.read_message",
        "outlook.search_messages",
        "outlook.send_email",
        "outlook.list_calendar_events",
        "outlook.find_free_times",
    ],
    "teams": [
        "teams.list_chats",
        "teams.list_channel_messages",
        "teams.read_message",
        "teams.post_chat_message",
    ],
    "sharepoint": [
        "sharepoint.search_sites",
        "sharepoint.list_documents",
        "sharepoint.download_document",
    ],
}


@pytest.mark.parametrize("name", REAL_EXTENSION_NAMES)
def test_tool_specs_carry_canonical_names(name: str) -> None:
    """tool_specs() names match the pre-migration tool surface exactly."""
    ext = _build_extension(name)
    specs = ext.tool_specs()
    assert [s.name for s in specs] == EXPECTED_TOOL_NAMES[name]
    assert all(isinstance(s, ToolSpec) for s in specs)
    assert all(s.source == f"extension:{name}" for s in specs)


@pytest.mark.parametrize("name", REAL_EXTENSION_NAMES)
def test_adapters_render_same_count_and_names(name: str) -> None:
    """All three adapters are pure renderings: same count, same order,
    same names as the ToolSpec list."""
    ext = _build_extension(name)
    specs = ext.tool_specs()

    lc = render_langchain_tools(list(specs))
    msaf = render_msaf_tools(list(specs))
    mcp = render_mcp_tools(list(specs))

    assert len(lc) == len(msaf) == len(mcp) == len(specs)
    spec_names = [s.name for s in specs]
    assert [t.name for t in lc] == spec_names
    assert [t.name for t in msaf] == spec_names
    assert [t.name for t in mcp] == spec_names


@pytest.mark.parametrize("name", REAL_EXTENSION_NAMES)
def test_adapters_preserve_description_and_schema(name: str) -> None:
    ext = _build_extension(name)
    specs = ext.tool_specs()
    lc = render_langchain_tools(list(specs))
    msaf = render_msaf_tools(list(specs))
    mcp = render_mcp_tools(list(specs))
    for spec, lc_t, msaf_t, mcp_t in zip(specs, lc, msaf, mcp, strict=True):
        assert lc_t.description == spec.description
        assert lc_t.args_schema == spec.input_schema
        assert msaf_t.description == spec.description
        assert mcp_t.description == spec.description
        assert mcp_t.inputSchema == spec.input_schema


@pytest.mark.parametrize("name", REAL_EXTENSION_NAMES)
def test_each_real_extension_yields_at_least_one_tool(name: str) -> None:
    """Real extensions MUST NOT return empty spec lists.

    Spec scenario: extension-registry / "ms_graph/teams/sharepoint/
    outlook no longer return empty tool lists" (the MODIFIED contract
    that distinguishes a real extension from a stub).
    """
    ext = _build_extension(name)
    assert len(ext.tool_specs()) > 0, (
        f"{name}: tool_specs returned empty — real extensions "
        "MUST expose at least one tool (post-P5 contract)"
    )
