"""Tests for DelegationContext rendering + harness prompt injection (P12).

Covers the delegation-context change's harness-adapter delta: the
``## Delegation context`` block mirrors the D27 ``## Recent context``
prepend in BOTH SDK harnesses, empty sections are omitted, and the
no-context path leaves prompts byte-identical to pre-P12 output.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.delegation.context import (
    DELEGATION_SECTION_HEADING,
    DelegationContext,
)
from assistant.harnesses.sdk.deep_agents import DeepAgentsHarness
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness


def _persona() -> PersonaConfig:
    return PersonaConfig(
        name="p",
        display_name="P",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={
            "deep_agents": {"enabled": True},
            "ms_agent_framework": {"enabled": True},
        },
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
    )


def _role(name: str = "writer") -> RoleConfig:
    return RoleConfig(
        name=name,
        display_name=name.title(),
        description="",
        prompt="test prompt",
        delegation={"allowed_sub_roles": []},
    )


def _child_identity() -> AgentIdentity:
    return AgentIdentity(persona="p", role="researcher").delegate_to("writer")


def _full_context() -> DelegationContext:
    return DelegationContext(
        parent_role="researcher",
        identity=_child_identity(),
        memory_snippets=("snippet-alpha", "snippet-beta"),
        conversation_summary="user wants a summary email",
        constraints={
            "max_depth_remaining": 4,
            "deadline_seconds": 30,
            "allowed_tools": ["gmail:send", "gmail:draft"],
        },
    )


class _EmptyMemoryPolicy:
    async def get_recent_snippets(self, persona, role, *, limit=10):
        return []

    async def record_interaction(self, persona, role, *, user_message, response):
        return None

    def resolve(self, persona, harness_name):  # pragma: no cover
        raise NotImplementedError

    def export_memory_context(self, persona) -> str:
        return ""


class _SnippetMemoryPolicy(_EmptyMemoryPolicy):
    async def get_recent_snippets(self, persona, role, *, limit=10):
        return ["recent-snippet"]


# ── DelegationContext.render() ───────────────────────────────────────


def test_render_full_context_contains_all_sections() -> None:
    text = _full_context().render()
    assert text.startswith(DELEGATION_SECTION_HEADING)
    assert "role 'writer'" in text
    assert "delegated by role 'researcher'" in text
    assert "researcher -> writer (depth 1)" in text
    assert "### Conversation summary" in text
    assert "user wants a summary email" in text
    assert "### Relevant memory" in text
    assert "snippet-alpha" in text and "snippet-beta" in text
    assert "### Constraints" in text
    assert "- max_depth_remaining: 4" in text
    assert "- deadline_seconds: 30" in text
    assert "- allowed_tools: gmail:send, gmail:draft" in text


def test_render_omits_empty_sections() -> None:
    text = DelegationContext(
        parent_role="researcher", identity=_child_identity()
    ).render()
    assert text.startswith(DELEGATION_SECTION_HEADING)
    assert "Delegation chain: researcher -> writer" in text
    assert "### Conversation summary" not in text
    assert "### Relevant memory" not in text
    assert "### Constraints" not in text


def test_chain_lives_on_identity_not_duplicated() -> None:
    """The dataclass carries no chain field of its own — the P25
    AgentIdentity is the single source of chain truth."""
    ctx = _full_context()
    assert not hasattr(ctx, "delegation_chain")
    assert ctx.identity.delegation_chain == ("researcher",)


# ── DeepAgents harness injection ─────────────────────────────────────


def test_deep_agents_prepends_delegation_block() -> None:
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
            memory_policy=_SnippetMemoryPolicy(),
            delegation_context=_full_context(),
        )
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        prompt = cda_mock.call_args.kwargs["system_prompt"]
        assert DELEGATION_SECTION_HEADING in prompt
        assert "## Recent context" in prompt
        # Delegation block leads the whole prompt, then recent
        # context, then the composed role prompt.
        assert prompt.index(DELEGATION_SECTION_HEADING) < prompt.index(
            "## Recent context"
        )
        assert prompt.index("## Recent context") < prompt.index("test prompt")


def test_deep_agents_prompt_unchanged_without_context() -> None:
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
            persona, role, memory_policy=_EmptyMemoryPolicy()
        )
        asyncio.run(h.create_agent(tools=[], extensions=[]))
        prompt = cda_mock.call_args.kwargs["system_prompt"]
        assert DELEGATION_SECTION_HEADING not in prompt
        assert prompt == compose_system_prompt(persona, role)


def test_deep_agents_spawn_sub_agent_threads_context() -> None:
    """spawn_sub_agent(context=...) reaches the sub-harness's prompt."""
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        agent = MagicMock()

        async def _ainvoke(payload, config=None):
            return {"messages": [{"role": "assistant", "content": "done"}]}

        agent.ainvoke = _ainvoke
        cda_mock.return_value = agent
        parent = DeepAgentsHarness(
            _persona(), _role("researcher"), memory_policy=_EmptyMemoryPolicy()
        )
        result = asyncio.run(
            parent.spawn_sub_agent(
                _role("writer"),
                "draft it",
                tools=[],
                extensions=[],
                context=_full_context(),
            )
        )
        assert result == "done"
        prompt = cda_mock.call_args.kwargs["system_prompt"]
        assert DELEGATION_SECTION_HEADING in prompt
        assert "user wants a summary email" in prompt


def test_deep_agents_spawn_sub_agent_without_context_backward_compat() -> None:
    """Pre-P12 positional call shape still works (context=None)."""
    with patch(
        "assistant.harnesses.sdk.deep_agents.init_chat_model",
        return_value=MagicMock(),
    ), patch(
        "assistant.harnesses.sdk.deep_agents.create_deep_agent"
    ) as cda_mock:
        agent = MagicMock()

        async def _ainvoke(payload, config=None):
            return {"messages": [{"role": "assistant", "content": "ok"}]}

        agent.ainvoke = _ainvoke
        cda_mock.return_value = agent
        parent = DeepAgentsHarness(
            _persona(), _role("researcher"), memory_policy=_EmptyMemoryPolicy()
        )
        result = asyncio.run(
            parent.spawn_sub_agent(_role("writer"), "draft", [], [])
        )
        assert result == "ok"
        prompt = cda_mock.call_args.kwargs["system_prompt"]
        assert DELEGATION_SECTION_HEADING not in prompt


# ── MSAF harness injection ───────────────────────────────────────────


class _FakeContextProvider:
    def compose_system_prompt(self, persona, role) -> str:
        return "msaf base prompt"

    def export_context(self, persona, role) -> dict[str, str]:
        return {"system_prompt": self.compose_system_prompt(persona, role)}


def test_msaf_instructions_prepend_delegation_block() -> None:
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        memory_policy=_SnippetMemoryPolicy(),
        context_provider=_FakeContextProvider(),
        delegation_context=_full_context(),
    )
    instructions = asyncio.run(h._compose_instructions())
    assert instructions.index(DELEGATION_SECTION_HEADING) == 0
    assert instructions.index(DELEGATION_SECTION_HEADING) < instructions.index(
        "## Recent context"
    )
    assert instructions.index("## Recent context") < instructions.index(
        "msaf base prompt"
    )


def test_msaf_instructions_unchanged_without_context() -> None:
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        memory_policy=_EmptyMemoryPolicy(),
        context_provider=_FakeContextProvider(),
    )
    instructions = asyncio.run(h._compose_instructions())
    assert instructions == "msaf base prompt"
