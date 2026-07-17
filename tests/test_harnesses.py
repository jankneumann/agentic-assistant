"""Tests for harness-adapter spec.

Covers all scenarios across requirements in harness-adapter spec,
including the Phase 3 restructure (SDK/Host split, harness_type property).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.extensions._stub import StubExtension
from assistant.harnesses.base import HarnessAdapter, HostHarnessAdapter, SdkHarnessAdapter
from assistant.harnesses.factory import create_harness
from assistant.harnesses.host.claude_code import ClaudeCodeHarness
from assistant.harnesses.sdk.deep_agents import DeepAgentsHarness
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness


def _persona(
    deep_enabled: bool = True,
    ms_enabled: bool = False,
) -> PersonaConfig:
    return PersonaConfig(
        name="p",
        display_name="P",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={
            "deep_agents": {"enabled": deep_enabled},
            "ms_agent_framework": {"enabled": ms_enabled},
        },
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
    )


def _role() -> RoleConfig:
    return RoleConfig(
        name="r",
        display_name="R",
        description="",
        prompt="test prompt",
        delegation={"allowed_sub_roles": []},
    )


# ── Abstract Harness Adapter Contract ────────────────────────────────


def test_instantiating_abstract_class_raises() -> None:
    with pytest.raises(TypeError):
        HarnessAdapter(_persona(), _role())  # type: ignore[abstract]


def test_concrete_subclass_must_implement_all_methods() -> None:
    class Partial(SdkHarnessAdapter):
        def name(self) -> str:
            return "partial"

    with pytest.raises(TypeError):
        Partial(_persona(), _role())  # type: ignore[abstract]


# ── Harness type property ────────────────────────────────────────────


def test_sdk_harness_type() -> None:
    h = DeepAgentsHarness(_persona(), _role())
    assert h.harness_type() == "sdk"


def test_host_harness_type() -> None:
    h = ClaudeCodeHarness(_persona(), _role())
    assert h.harness_type() == "host"


# ── Deep Agents Harness ──────────────────────────────────────────────


def test_harness_name_is_deep_agents() -> None:
    assert DeepAgentsHarness(_persona(), _role()).name() == "deep_agents"


def test_create_agent_resolves_model_through_registry_binding() -> None:
    """Registry-only (P19 verdict #3): create_agent resolves the model
    via the consumer binding — synthesized default here, since the
    persona declares no ``models:`` registry."""
    sentinel_model = MagicMock(name="model-handle")
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=sentinel_model,
    ) as init_mock, patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock(name="agent")
        h = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        init_mock.assert_called_once_with("anthropic:claude-sonnet-4-20250514")
        kwargs = cda_mock.call_args.kwargs
        assert kwargs["model"] is sentinel_model


def test_create_agent_uses_only_the_provided_tool_list() -> None:
    """Spec harness-adapter "create_agent uses only the provided tool
    list": ``tools`` is the complete ToolPolicy-aggregated list; the
    harness derives nothing from ``extensions`` (P17 tool-spec
    migration removed the former second aggregation site)."""
    tool_a = MagicMock(name="tool_a")
    tool_b = MagicMock(name="tool_b")

    class _Ext(StubExtension):
        def tool_specs(self) -> list:
            raise AssertionError(
                "DeepAgentsHarness called tool_specs(); harnesses must "
                "not derive tools from extensions"
            )

    ext = _Ext("e", {})
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h.create_agent(tools=[tool_a, tool_b], extensions=[ext]))
        passed_tools = cda_mock.call_args.kwargs["tools"]
        # Non-ToolSpec entries pass through the adapter unchanged.
        assert passed_tools == [tool_a, tool_b]


def test_create_agent_renders_tool_specs_via_langchain_adapter() -> None:
    """ToolSpec entries in ``tools`` are rendered to StructuredTools
    (name/description/schema preserved; invocation hits the handler)."""
    from langchain_core.tools import StructuredTool

    from assistant.core.toolspec import ToolSpec

    async def _handler(query: str) -> str:
        return f"hit:{query}"

    spec = ToolSpec(
        name="gmail.search",
        description="Search.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_handler,
        source="extension:gmail",
    )
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h.create_agent(tools=[spec], extensions=[]))
        [tool] = cda_mock.call_args.kwargs["tools"]
        assert isinstance(tool, StructuredTool)
        assert tool.name == "gmail.search"
        assert tool.description == "Search."
        assert asyncio.run(tool.ainvoke({"query": "x"})) == "hit:x"


def test_invoke_returns_last_assistant_message_content() -> None:
    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            return {
                "messages": [
                    {"role": "user", "content": "q"},
                    {"role": "assistant", "content": "a"},
                ]
            }

    h = DeepAgentsHarness(_persona(), _role())
    result = asyncio.run(h.invoke(_FakeAgent(), "q"))
    assert result == "a"


def test_invoke_extracts_content_from_langchain_aimessage_objects() -> None:
    """Regression test for a latent bug discovered during the
    add-teacher-role smoke test: the real langchain agent returns
    ``AIMessage`` objects (which expose ``type='ai'``), NOT dicts with
    ``role='assistant'``. Before the fix, ``_msg_role`` looked only at
    ``role`` and returned ``""`` for every ``AIMessage``, so
    ``invoke()`` returned ``""`` and the REPL printed an empty
    ``[Teacher]>`` line.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            return {
                "messages": [
                    HumanMessage(content="explain entropy"),
                    AIMessage(content="entropy is a measure of disorder"),
                ]
            }

    h = DeepAgentsHarness(_persona(), _role())
    result = asyncio.run(h.invoke(_FakeAgent(), "q"))
    assert result == "entropy is a measure of disorder"


def test_invoke_extracts_text_from_aimessage_with_content_blocks() -> None:
    """Anthropic models can emit ``content`` as a list of content
    blocks (``[{"type": "text", ...}, {"type": "tool_use", ...}]``)
    when tool calls and text are interleaved. ``invoke()`` must
    extract and concatenate the text blocks; otherwise the REPL would
    echo a raw Python list repr.
    """
    from langchain_core.messages import AIMessage

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            return {
                "messages": [
                    AIMessage(content=[
                        {"type": "text", "text": "Step 1: "},
                        {"type": "tool_use", "id": "t1", "name": "kb", "input": {}},
                        {"type": "text", "text": "entropy is..."},
                    ])
                ]
            }

    h = DeepAgentsHarness(_persona(), _role())
    result = asyncio.run(h.invoke(_FakeAgent(), "q"))
    assert result == "Step 1: entropy is..."


def test_invoke_returns_empty_when_no_assistant_message() -> None:
    """Pure tool-call turn with no final text response — invoke()
    returns empty string rather than crashing."""
    from langchain_core.messages import HumanMessage

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            return {"messages": [HumanMessage(content="q")]}

    h = DeepAgentsHarness(_persona(), _role())
    result = asyncio.run(h.invoke(_FakeAgent(), "q"))
    assert result == ""


# ── Memory Snippet Injection + Post-Turn Capture (memory-retrieval-activation) ──


class _RecordingMemoryPolicy:
    """Fake MemoryPolicy that returns canned snippets and records captures."""

    def __init__(
        self, snippets: list[str] | None = None, *, fail_record: bool = False
    ) -> None:
        self._snippets = snippets or []
        self._fail_record = fail_record
        self.recorded: list[tuple[str, str]] = []

    def resolve(self, persona, harness_name):  # pragma: no cover - unused
        raise NotImplementedError

    def export_memory_context(self, persona) -> str:
        return ""

    async def get_recent_snippets(
        self, persona, role, *, limit: int = 10
    ) -> list:
        return list(self._snippets[:limit])

    async def record_interaction(
        self, persona, role, *, user_message: str, response: str
    ) -> None:
        if self._fail_record:
            raise ConnectionError("memory backend down")
        self.recorded.append((user_message, response))


def test_create_agent_prepends_recent_context_when_snippets_exist() -> None:
    """Parity with the MSAF harness: DeepAgents MUST prepend memory
    snippets under ``## Recent context`` at create_agent time."""
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(
            _persona(),
            _role(),
            memory_policy=_RecordingMemoryPolicy(["snippet-1", "snippet-2"]),
        )
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        prompt = cda_mock.call_args.kwargs["system_prompt"]
        assert "## Recent context" in prompt
        assert "snippet-1" in prompt
        assert "snippet-2" in prompt
        assert "test prompt" in prompt  # composed role prompt still present
        assert prompt.index("## Recent context") < prompt.index("test prompt")


def test_create_agent_prompt_unchanged_when_no_snippets() -> None:
    from assistant.core.composition import compose_system_prompt

    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        persona, role = _persona(), _role()
        h = DeepAgentsHarness(
            persona, role, memory_policy=_RecordingMemoryPolicy([])
        )
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        prompt = cda_mock.call_args.kwargs["system_prompt"]
        assert "## Recent context" not in prompt
        assert prompt == compose_system_prompt(persona, role)


def test_create_agent_default_file_policy_yields_no_injection() -> None:
    """A persona with no database_url resolves FileMemoryPolicy; with
    empty memory_content the prompt MUST stay unchanged."""
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        assert "## Recent context" not in cda_mock.call_args.kwargs["system_prompt"]


def test_invoke_captures_interaction_on_success() -> None:
    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            return {"messages": [{"role": "assistant", "content": "the answer"}]}

    policy = _RecordingMemoryPolicy()
    h = DeepAgentsHarness(_persona(), _role(), memory_policy=policy)
    result = asyncio.run(h.invoke(_FakeAgent(), "the question"))
    assert result == "the answer"
    assert policy.recorded == [("the question", "the answer")]


def test_invoke_swallows_capture_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Memory failures must never break a conversation — a raising
    record_interaction MUST be swallowed with a warning."""
    import logging

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            return {"messages": [{"role": "assistant", "content": "ok"}]}

    policy = _RecordingMemoryPolicy(fail_record=True)
    h = DeepAgentsHarness(_persona(), _role(), memory_policy=policy)

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(h.invoke(_FakeAgent(), "q"))

    assert result == "ok"  # invoke succeeded despite capture failure
    assert policy.recorded == []
    assert "memory capture failed" in caplog.text.lower()


def test_invoke_does_not_capture_on_agent_failure() -> None:
    class _FailingAgent:
        async def ainvoke(self, payload, config=None):
            raise RuntimeError("model exploded")

    policy = _RecordingMemoryPolicy()
    h = DeepAgentsHarness(_persona(), _role(), memory_policy=policy)
    with pytest.raises(RuntimeError):
        asyncio.run(h.invoke(_FailingAgent(), "q"))
    assert policy.recorded == []


# ── Multi-Turn Conversation Memory (#34) ─────────────────────────────


def test_create_agent_constructs_with_checkpointer() -> None:
    """The harness MUST pass a non-None ``checkpointer`` to
    ``create_deep_agent``; without it, the agent has no place to
    persist prior turns and every ``ainvoke`` starts a fresh
    conversation (the bug filed as agentic-assistant#34)."""
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        kwargs = cda_mock.call_args.kwargs
        assert kwargs.get("checkpointer") is not None
        assert h._thread_id  # non-empty


def test_invoke_passes_thread_id_in_runnable_config() -> None:
    """``invoke`` MUST pass ``config={"configurable":
    {"thread_id": self._thread_id}}`` to ``agent.ainvoke``;
    LangGraph's checkpointer uses this key to look up the prior
    state for the conversation."""
    captured: dict = {}

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            captured["config"] = config
            return {"messages": [{"role": "assistant", "content": "ok"}]}

    h = DeepAgentsHarness(_persona(), _role())
    h._thread_id = "thread-xyz-123"
    asyncio.run(h.invoke(_FakeAgent(), "hello"))
    assert captured["config"] == {"configurable": {"thread_id": "thread-xyz-123"}}


def test_thread_id_is_stable_across_invocations_on_one_harness() -> None:
    """Successive ``invoke`` calls on the same harness MUST use the
    same ``thread_id``. If the id changed per call, LangGraph would
    treat each call as a new conversation and the bug would persist."""
    seen_thread_ids: list[str] = []

    class _FakeAgent:
        async def ainvoke(self, payload, config=None):
            seen_thread_ids.append(config["configurable"]["thread_id"])
            return {"messages": [{"role": "assistant", "content": "ok"}]}

    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = _FakeAgent()
        h = DeepAgentsHarness(_persona(), _role())
        agent = asyncio.run(h.create_agent(tools=[], extensions=[]))
        asyncio.run(h.invoke(agent, "turn 1"))
        asyncio.run(h.invoke(agent, "turn 2"))
    assert len(seen_thread_ids) == 2
    assert seen_thread_ids[0] == seen_thread_ids[1]
    assert seen_thread_ids[0] == h._thread_id


def test_distinct_harnesses_get_distinct_thread_ids() -> None:
    """Two ``DeepAgentsHarness`` instances MUST be assigned distinct
    ``thread_id`` values so that a ``/role <new>`` rebuild (which
    instantiates a fresh harness) starts a fresh conversation.
    Matches the existing ``/role`` rebuild semantics in
    ``cli.py:146-159``."""
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent",
        return_value=MagicMock(),
    ):
        h1 = DeepAgentsHarness(_persona(), _role())
        h2 = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h1.create_agent(tools=[], extensions=[]))
        asyncio.run(h2.create_agent(tools=[], extensions=[]))
        assert h1._thread_id != h2._thread_id
        assert h1._thread_id and h2._thread_id


def test_create_agent_passes_real_inmemorysaver_instance() -> None:
    """Sanity check that the ``checkpointer`` kwarg passed to
    ``create_deep_agent`` is an actual ``InMemorySaver`` (not a
    bare ``MagicMock`` or ``None`` that the API might silently
    accept). Pairs with the upstream LangGraph test suite, which
    covers the checkpointer's history-preservation behavior given
    a properly-bound ``thread_id``.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        cda_mock.return_value = MagicMock()
        h = DeepAgentsHarness(_persona(), _role())
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        checkpointer = cda_mock.call_args.kwargs["checkpointer"]
        assert isinstance(checkpointer, InMemorySaver)


# ── MS Agent Framework Harness Registered but Stubbed ───────────────


def test_factory_returns_ms_af_harness_for_enabled_persona() -> None:
    persona = _persona(deep_enabled=False, ms_enabled=True)
    harness = create_harness(persona, _role(), "ms_agent_framework")
    assert isinstance(harness, MSAgentFrameworkHarness)


def test_ms_af_create_agent_no_longer_raises_not_implemented() -> None:
    """Post-P5 contract: create_agent MUST NOT raise NotImplementedError.

    The full MSAF harness implementation lives behind agent_framework
    SDK imports that this test does not exercise; the dedicated MSAF
    harness suite under tests/test_harness_ms_agent_fw.py covers
    create_agent's full behavior with the SDK mocked.
    """
    h = MSAgentFrameworkHarness(
        _persona(ms_enabled=True),
        _role(),
        chat_client_factory=lambda: object(),
    )

    from unittest.mock import patch

    class _FakeAgent:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    with patch("agent_framework.Agent", new=_FakeAgent, create=True):
        agent = asyncio.run(h.create_agent(tools=[], extensions=[]))
    assert agent is not None  # spec: NotImplementedError MUST NOT fire


# ── Claude Code Host Harness ─────────────────────────────────────────


def test_claude_code_name_and_type() -> None:
    h = ClaudeCodeHarness(_persona(), _role())
    assert h.name() == "claude_code"
    assert h.harness_type() == "host"


def test_claude_code_export_context() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy
    from assistant.core.capabilities.types import CapabilitySet

    persona = _persona()
    persona.prompt_augmentation = ""
    persona.memory_content = "## Memory\ntest"

    cs = CapabilitySet(
        guardrails=MagicMock(),
        sandbox=MagicMock(),
        memory=FileMemoryPolicy(),
        tools=MagicMock(),
        context=None,
    )

    h = ClaudeCodeHarness(persona, _role())
    ctx = h.export_context(cs)
    assert "system_prompt" in ctx
    assert "memory_context" in ctx
    assert "## Memory" in ctx["memory_context"]


def test_claude_code_export_tool_manifest() -> None:
    from assistant.core.capabilities.tools import DefaultToolPolicy
    from assistant.core.capabilities.types import CapabilitySet

    persona = _persona()
    persona.extensions = [{"module": "gmail", "config": {"scopes": ["read"]}}]

    cs = CapabilitySet(
        guardrails=MagicMock(),
        sandbox=MagicMock(),
        memory=MagicMock(),
        tools=DefaultToolPolicy(),
        context=None,
    )

    h = ClaudeCodeHarness(persona, _role())
    manifest = h.export_tool_manifest(cs)
    assert "extensions" in manifest
    assert "gmail" in manifest["extensions"]


# ── Harness Factory Validation ──────────────────────────────────────


def test_factory_creates_sdk_harness() -> None:
    harness = create_harness(_persona(), _role(), "deep_agents")
    assert isinstance(harness, SdkHarnessAdapter)


def test_factory_creates_host_harness() -> None:
    harness = create_harness(_persona(), _role(), "claude_code")
    assert isinstance(harness, HostHarnessAdapter)


def test_unknown_harness_name_raises() -> None:
    with pytest.raises(ValueError) as exc:
        create_harness(_persona(), _role(), "nonexistent")
    assert "Available:" in str(exc.value)


def test_disabled_harness_raises() -> None:
    persona = _persona(deep_enabled=False)
    with pytest.raises(ValueError) as exc:
        create_harness(persona, _role(), "deep_agents")
    assert "not enabled" in str(exc.value).lower()
