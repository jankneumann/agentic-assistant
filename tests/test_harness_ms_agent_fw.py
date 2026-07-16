"""Tests for the post-P5 ``MSAgentFrameworkHarness`` real implementation.

Covers ms-agent-framework-harness spec scenarios:

- "Harness is registered and instantiable"
- "create_agent no longer raises NotImplementedError"
- "Agent receives composed instructions"
- "Agent receives extension tools via as_ms_agent_tools"
- "Chat client selection respects persona configuration"
- "invoke returns the agent's response string"
- "invoke propagates underlying exceptions unchanged"
- "spawn_sub_agent returns the sub-agent's response"
- "Sub-agent uses sub-role's composed prompt"
- "Authorized extensions are filtered through ToolPolicy"
- "spawn_sub_agent calls GuardrailProvider before constructing sub-agent"
- "Memory snippets prepended to instructions"
- "Empty memory snippets leaves instructions unchanged"
- "NoopMemoryPolicy yields no injection"
- "Successful invoke emits trace_llm_call once"
- "Failed invoke still emits trace_llm_call before propagating"

The ``agent_framework`` SDK is mocked at the import sites — tests do
NOT exercise the real chat client or LLM round-trips. Lazy imports
inside ``create_agent`` / ``_build_chat_client`` make this clean.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from assistant.core.capabilities.types import (
    ActionDecision,
    ActionRequest,
    MemoryConfig,
    MemoryScoping,
)
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.factory import create_harness
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness

# ── Fixtures ─────────────────────────────────────────────────────────


def _persona(
    *,
    chat_client: str = "openai",
    enabled: bool = True,
) -> PersonaConfig:
    return PersonaConfig(
        name="testpersona",
        display_name="Test",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={
            "ms_agent_framework": {
                "enabled": enabled,
                "chat_client": chat_client,
            }
        },
        tool_sources={},
        extensions=[],
        extensions_dir=None,  # type: ignore[arg-type]
        raw={},
    )


def _role(name: str = "chief_of_staff") -> RoleConfig:
    return RoleConfig(
        name=name,
        display_name=name.replace("_", " ").title(),
        description=f"Test role: {name}",
        prompt="You are work assistant.",
    )


class _FakeAgent:
    """Records constructor kwargs and stubs ``run`` for tests."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.run_response: str | Exception = "fake-response"

    async def run(self, message: str) -> str:
        self.last_message = message
        if isinstance(self.run_response, Exception):
            raise self.run_response
        return self.run_response


class _FakeChatClient:
    """Stand-in for OpenAIChatClient / AzureOpenAIChatClient."""


class _FakeMemoryPolicy:
    def __init__(
        self, snippets: list[str], *, fail_record: bool = False
    ) -> None:
        self._snippets = snippets
        self._fail_record = fail_record
        self.recorded: list[tuple[str, str]] = []

    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig:
        return MemoryConfig(
            backend_type="fake",
            config={},
            scoping=MemoryScoping(),
        )

    def export_memory_context(self, persona: Any) -> str:
        return ""

    async def get_recent_snippets(
        self, persona: Any, role: Any, *, limit: int = 10
    ) -> list[str]:
        return list(self._snippets[:limit])

    async def record_interaction(
        self, persona: Any, role: Any, *, user_message: str, response: str
    ) -> None:
        if self._fail_record:
            raise ConnectionError("memory backend down")
        self.recorded.append((user_message, response))


class _FakeToolPolicy:
    def __init__(self, allowed: list[Any] | None = None) -> None:
        self._allowed = allowed

    def authorized_tools(self, persona, role, *, loaded_extensions):
        return loaded_extensions

    def authorized_extensions(self, persona, role, *, loaded_extensions):
        if self._allowed is None:
            return loaded_extensions
        return list(self._allowed)

    def export_tool_manifest(self, persona, role):
        return {}


class _FakeGuardrailProvider:
    def __init__(self, decision: ActionDecision) -> None:
        self.decision = decision
        self.calls: list[ActionRequest] = []

    def check_action(self, action: ActionRequest) -> ActionDecision:
        self.calls.append(action)
        return self.decision

    def check_delegation(self, parent_role, sub_role, task):
        return self.decision

    def declare_risk(self, action):
        from assistant.core.capabilities.types import RiskLevel
        return RiskLevel.LOW


class _FakeExtension:
    def __init__(self, name: str, tools: list[Any]) -> None:
        self.name = name
        self._tools = tools

    def as_langchain_tools(self):
        # MSAF harness MUST NOT call this — assert by raising loud here.
        raise AssertionError(
            "MSAF harness called as_langchain_tools(); spec D11 forbids this"
        )

    def as_ms_agent_tools(self):
        return list(self._tools)


def _patched_agent_factory():
    """Patch ``agent_framework.Agent`` so create_agent records ctor args."""
    return patch("agent_framework.Agent", new=_FakeAgent, create=True)


# ── Registry & instantiability ───────────────────────────────────────


def test_factory_returns_ms_af_harness_for_enabled_persona() -> None:
    """Spec: harness is registered and instantiable."""
    harness = create_harness(_persona(), _role(), "ms_agent_framework")
    assert isinstance(harness, MSAgentFrameworkHarness)
    assert harness.harness_type() == "sdk"
    assert harness.name() == "ms_agent_framework"


# ── create_agent: no NotImplementedError + Agent shape ────────────────


def test_create_agent_does_not_raise_not_implemented_error() -> None:
    """Spec: create_agent no longer raises NotImplementedError."""
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        chat_client_factory=lambda: _FakeChatClient(),
    )
    with _patched_agent_factory():
        agent = asyncio.run(h.create_agent(tools=[], extensions=[]))
    assert isinstance(agent, _FakeAgent)


def test_create_agent_passes_composed_instructions() -> None:
    """Spec: Agent receives composed instructions."""
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        chat_client_factory=lambda: _FakeChatClient(),
    )
    with _patched_agent_factory():
        agent = asyncio.run(h.create_agent(tools=[], extensions=[]))
    # The composed prompt for the test role contains the role prompt.
    instructions = agent.kwargs["instructions"]
    assert "You are work assistant." in instructions


def test_create_agent_passes_extension_tools_via_as_ms_agent_tools() -> None:
    """Spec: Agent receives extension tools via as_ms_agent_tools."""
    outlook_tool = MagicMock(name="outlook_list_messages")
    ad_hoc = MagicMock(name="ad_hoc_tool")
    outlook = _FakeExtension("outlook", [outlook_tool])

    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        tool_policy=_FakeToolPolicy(),  # accepts everything
        chat_client_factory=lambda: _FakeChatClient(),
    )
    with _patched_agent_factory():
        agent = asyncio.run(
            h.create_agent(tools=[ad_hoc], extensions=[outlook])
        )
    tools = agent.kwargs["tools"]
    assert ad_hoc in tools
    assert outlook_tool in tools
    # MSAF harness MUST NOT consult as_langchain_tools(); _FakeExtension
    # raises AssertionError if it does — this test passing proves we
    # didn't call it.


def test_create_agent_uses_azure_chat_client_when_persona_says_so() -> None:
    """Spec: Chat client selection respects persona configuration."""
    azure_marker = _FakeChatClient()
    captured_client: list[Any] = []

    def factory():
        captured_client.append(azure_marker)
        return azure_marker

    h = MSAgentFrameworkHarness(
        _persona(chat_client="azure_openai"),
        _role(),
        chat_client_factory=factory,
    )
    with _patched_agent_factory():
        agent = asyncio.run(h.create_agent(tools=[], extensions=[]))
    assert agent.kwargs["client"] is azure_marker
    assert captured_client == [azure_marker]


# ── Tool policy filtering ────────────────────────────────────────────


def test_tool_policy_filters_authorized_extensions_first() -> None:
    """Spec: Authorized extensions are filtered through ToolPolicy.

    The harness MUST consult ``ToolPolicy.authorized_extensions`` before
    reading ``as_ms_agent_tools()`` — the unauthorized extension's tools
    MUST NOT flow into the constructed Agent.
    """
    outlook_tool = MagicMock(name="outlook_tool")
    teams_tool = MagicMock(name="teams_tool")
    outlook = _FakeExtension("outlook", [outlook_tool])
    teams = _FakeExtension("teams", [teams_tool])

    # Policy authorizes ONLY outlook.
    tool_policy = _FakeToolPolicy(allowed=[outlook])
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        tool_policy=tool_policy,
        chat_client_factory=lambda: _FakeChatClient(),
    )
    with _patched_agent_factory():
        agent = asyncio.run(
            h.create_agent(tools=[], extensions=[outlook, teams])
        )
    tools = agent.kwargs["tools"]
    assert outlook_tool in tools
    assert teams_tool not in tools


# ── invoke ───────────────────────────────────────────────────────────


def test_invoke_returns_agent_response_string() -> None:
    """Spec: invoke returns the agent's response string."""
    h = MSAgentFrameworkHarness(_persona(), _role())
    agent = _FakeAgent()
    agent.run_response = "42"
    result = asyncio.run(h.invoke(agent, "what is the answer?"))
    assert result == "42"


def test_invoke_propagates_underlying_exceptions() -> None:
    """Spec: invoke propagates underlying exceptions unchanged.

    Also covers the @traced_harness contract: trace_llm_call is
    emitted once with metadata={"error": "ValueError"} before the
    exception propagates.
    """
    h = MSAgentFrameworkHarness(_persona(), _role())
    agent = _FakeAgent()
    agent.run_response = ValueError("rate limited")

    fake_provider = MagicMock()
    with patch(
        "assistant.telemetry.decorators.get_observability_provider",
        return_value=fake_provider,
    ):
        with pytest.raises(ValueError, match="rate limited"):
            asyncio.run(h.invoke(agent, "hi"))

    # @traced_harness MUST emit exactly one trace_llm_call carrying
    # metadata={"error": "ValueError"} per the harness-adapter contract.
    assert fake_provider.trace_llm_call.call_count == 1
    kwargs = fake_provider.trace_llm_call.call_args.kwargs
    assert kwargs["metadata"]["error"] == "ValueError"


def test_invoke_captures_interaction_on_success() -> None:
    """memory-retrieval-activation: post-turn capture on success."""
    policy = _FakeMemoryPolicy([])
    h = MSAgentFrameworkHarness(_persona(), _role(), memory_policy=policy)
    agent = _FakeAgent()
    agent.run_response = "the answer"
    result = asyncio.run(h.invoke(agent, "the question"))
    assert result == "the answer"
    assert policy.recorded == [("the question", "the answer")]


def test_invoke_swallows_capture_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """memory-retrieval-activation: capture failure never breaks a turn."""
    import logging

    policy = _FakeMemoryPolicy([], fail_record=True)
    h = MSAgentFrameworkHarness(_persona(), _role(), memory_policy=policy)
    agent = _FakeAgent()
    agent.run_response = "ok"

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(h.invoke(agent, "q"))

    assert result == "ok"
    assert policy.recorded == []
    assert "memory capture failed" in caplog.text.lower()


def test_invoke_does_not_capture_on_agent_failure() -> None:
    policy = _FakeMemoryPolicy([])
    h = MSAgentFrameworkHarness(_persona(), _role(), memory_policy=policy)
    agent = _FakeAgent()
    agent.run_response = ValueError("rate limited")
    with pytest.raises(ValueError, match="rate limited"):
        asyncio.run(h.invoke(agent, "q"))
    assert policy.recorded == []


def test_invoke_emits_trace_llm_call_on_success() -> None:
    """Spec: Successful invoke emits trace_llm_call once."""
    h = MSAgentFrameworkHarness(_persona(), _role())
    agent = _FakeAgent()
    agent.run_response = "ok"

    fake_provider = MagicMock()
    with patch(
        "assistant.telemetry.decorators.get_observability_provider",
        return_value=fake_provider,
    ):
        asyncio.run(h.invoke(agent, "hi"))

    assert fake_provider.trace_llm_call.call_count == 1
    kwargs = fake_provider.trace_llm_call.call_args.kwargs
    assert "duration_ms" in kwargs
    assert kwargs["duration_ms"] >= 0
    assert "persona" in kwargs
    assert "role" in kwargs


# ── spawn_sub_agent ──────────────────────────────────────────────────


def test_spawn_sub_agent_returns_sub_agents_response() -> None:
    """Spec: spawn_sub_agent returns the sub-agent's response."""
    sub_role = _role(name="research")
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        chat_client_factory=lambda: _FakeChatClient(),
    )

    fake = _FakeAgent()
    fake.run_response = "found 3 docs"
    with patch("agent_framework.Agent", return_value=fake, create=True):
        result = asyncio.run(
            h.spawn_sub_agent(
                role=sub_role,
                task="search docs",
                tools=[],
                extensions=[],
            )
        )
    assert result == "found 3 docs"


def test_spawn_sub_agent_calls_guardrail_provider_first() -> None:
    """Spec: spawn_sub_agent calls GuardrailProvider before constructing sub-agent.

    Denied decision → PermissionError, no Agent construction.
    """
    sub_role = _role(name="research")
    guardrails = _FakeGuardrailProvider(
        ActionDecision(allowed=False, reason="role not allowed")
    )

    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        guardrail_provider=guardrails,
        chat_client_factory=lambda: _FakeChatClient(),
    )

    with patch("agent_framework.Agent", side_effect=AssertionError("MUST NOT construct"), create=True):
        with pytest.raises(PermissionError, match="research"):
            asyncio.run(
                h.spawn_sub_agent(
                    role=sub_role,
                    task="x",
                    tools=[],
                    extensions=[],
                )
            )

    # The harness called the guardrail provider exactly once, with the
    # expected ActionRequest shape (action_type="delegate", resource=
    # target role, metadata carries the task — matching the actual
    # P1.8 ActionRequest fields).
    assert len(guardrails.calls) == 1
    action = guardrails.calls[0]
    assert action.action_type == "delegate"
    assert action.resource == "research"
    assert action.metadata.get("task") == "x"


# ── Memory snippet injection (D27) ───────────────────────────────────


def test_memory_snippets_prepended_to_instructions() -> None:
    """Spec: Memory snippets prepended to instructions."""
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        memory_policy=_FakeMemoryPolicy(["snippet-1", "snippet-2"]),
        chat_client_factory=lambda: _FakeChatClient(),
    )
    with _patched_agent_factory():
        agent = asyncio.run(h.create_agent(tools=[], extensions=[]))

    instructions = agent.kwargs["instructions"]
    assert "## Recent context" in instructions
    assert "snippet-1" in instructions
    assert "snippet-2" in instructions
    assert "You are work assistant." in instructions


def test_empty_memory_snippets_leaves_instructions_unchanged() -> None:
    """Spec: Empty memory snippets leaves instructions unchanged."""
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        memory_policy=_FakeMemoryPolicy([]),
        chat_client_factory=lambda: _FakeChatClient(),
    )
    with _patched_agent_factory():
        agent = asyncio.run(h.create_agent(tools=[], extensions=[]))

    instructions = agent.kwargs["instructions"]
    assert "## Recent context" not in instructions
    assert "You are work assistant." in instructions


def test_default_noop_memory_policy_yields_no_injection() -> None:
    """Spec: NoopMemoryPolicy yields no injection.

    With no explicit memory_policy, the harness resolves via
    CapabilityResolver. The default policy for a persona with
    database_url="" is FileMemoryPolicy whose ``get_recent_snippets``
    returns []. The constructed instructions MUST equal the composed
    prompt unchanged.
    """
    h = MSAgentFrameworkHarness(
        _persona(),
        _role(),
        chat_client_factory=lambda: _FakeChatClient(),
    )
    with _patched_agent_factory():
        agent = asyncio.run(h.create_agent(tools=[], extensions=[]))

    instructions = agent.kwargs["instructions"]
    assert "## Recent context" not in instructions
