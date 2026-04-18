"""Tests for capability types — Task 1.1.

Covers: ActionRequest, ActionDecision, RiskLevel, ExecutionContext,
MemoryConfig, MemoryScoping, CapabilitySet dataclasses.
"""

from __future__ import annotations

from pathlib import Path


def test_action_request_captures_context() -> None:
    from assistant.core.capabilities.types import ActionRequest

    req = ActionRequest(
        action_type="tool_call",
        resource="gmail.send",
        persona="personal",
        role="chief_of_staff",
    )
    assert req.action_type == "tool_call"
    assert req.resource == "gmail.send"
    assert req.persona == "personal"
    assert req.role == "chief_of_staff"
    assert req.metadata == {}


def test_action_request_with_metadata() -> None:
    from assistant.core.capabilities.types import ActionRequest

    req = ActionRequest(
        action_type="delegation",
        resource="writer",
        persona="personal",
        role="chief_of_staff",
        metadata={"task": "draft email"},
    )
    assert req.metadata == {"task": "draft email"}


def test_action_decision_defaults() -> None:
    from assistant.core.capabilities.types import ActionDecision

    dec = ActionDecision(allowed=True)
    assert dec.allowed is True
    assert dec.reason == ""
    assert dec.require_confirmation is False


def test_action_decision_with_reason() -> None:
    from assistant.core.capabilities.types import ActionDecision

    dec = ActionDecision(allowed=False, reason="policy violation", require_confirmation=True)
    assert dec.allowed is False
    assert dec.reason == "policy violation"
    assert dec.require_confirmation is True


def test_risk_level_ordering() -> None:
    from assistant.core.capabilities.types import RiskLevel

    assert RiskLevel.LOW < RiskLevel.MEDIUM
    assert RiskLevel.MEDIUM < RiskLevel.HIGH
    assert RiskLevel.HIGH < RiskLevel.CRITICAL
    assert RiskLevel.LOW < RiskLevel.CRITICAL


def test_execution_context_captures_sandbox_state() -> None:
    from assistant.core.capabilities.types import ExecutionContext

    ctx = ExecutionContext(work_dir=Path("/tmp/sandbox"), isolation_type="worktree")
    assert ctx.work_dir == Path("/tmp/sandbox")
    assert ctx.isolation_type == "worktree"
    assert ctx.metadata == {}


def test_execution_context_metadata_default() -> None:
    from assistant.core.capabilities.types import ExecutionContext

    ctx = ExecutionContext(work_dir=Path("."), isolation_type="none")
    assert ctx.metadata == {}


def test_memory_config_captures_backend_selection() -> None:
    from assistant.core.capabilities.types import MemoryConfig, MemoryScoping

    cfg = MemoryConfig(
        backend_type="file",
        config={"memory_files": ["./AGENTS.md"]},
        scoping=MemoryScoping(),
    )
    assert cfg.backend_type == "file"
    assert cfg.config == {"memory_files": ["./AGENTS.md"]}


def test_memory_scoping_defaults() -> None:
    from assistant.core.capabilities.types import MemoryScoping

    scoping = MemoryScoping()
    assert scoping.per_persona is True
    assert scoping.per_role is False
    assert scoping.per_session is False


def test_capability_set_holds_all_five() -> None:
    from assistant.core.capabilities.guardrails import AllowAllGuardrails, GuardrailProvider
    from assistant.core.capabilities.memory import FileMemoryPolicy, MemoryPolicy
    from assistant.core.capabilities.sandbox import PassthroughSandbox, SandboxProvider
    from assistant.core.capabilities.tools import DefaultToolPolicy, ToolPolicy
    from assistant.core.capabilities.types import CapabilitySet

    cs = CapabilitySet(
        guardrails=AllowAllGuardrails(),
        sandbox=PassthroughSandbox(),
        memory=FileMemoryPolicy(),
        tools=DefaultToolPolicy(),
        context=None,
    )
    assert isinstance(cs.guardrails, GuardrailProvider)
    assert isinstance(cs.sandbox, SandboxProvider)
    assert isinstance(cs.memory, MemoryPolicy)
    assert isinstance(cs.tools, ToolPolicy)
