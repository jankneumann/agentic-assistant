"""Tests for P12 delegation-context spawner features.

Covers the delegation-spawner delta: context construction + threading,
cycle detection (+ allow_recursive override), delegate_parallel
(isolation + concurrency cap), monitoring/cancellation registry,
analytics, and spawner backward compatibility with pre-P12 harness
adapters (no ``context`` keyword).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.context import DelegationContext
from assistant.delegation.spawner import (
    DelegationOutcome,
    DelegationSpawner,
)
from assistant.harnesses.base import SdkHarnessAdapter


class ContextCapturingHarness(SdkHarnessAdapter):
    """P12-aware fake: records the DelegationContext of every spawn."""

    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        super().__init__(persona, role)
        self.spawn_calls: list[tuple[str, str]] = []
        self.contexts: list[DelegationContext | None] = []
        self.gate: asyncio.Event | None = None
        self.response: str = "ok"
        self.fail_for_tasks: set[str] = set()

    def name(self) -> str:
        return "fake"

    async def create_agent(self, tools, extensions) -> Any:
        return object()

    async def invoke(self, agent, message) -> str:
        return self.response

    async def spawn_sub_agent(
        self,
        role: RoleConfig,
        task: str,
        tools,
        extensions,
        context: DelegationContext | None = None,
    ) -> str:
        self.spawn_calls.append((role.name, task))
        self.contexts.append(context)
        if task in self.fail_for_tasks:
            raise ValueError(f"boom: {task}")
        if self.gate is not None:
            await self.gate.wait()
        return self.response


class LegacyHarness(SdkHarnessAdapter):
    """Pre-P12 adapter shape: spawn_sub_agent without ``context``."""

    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        super().__init__(persona, role)
        self.spawn_calls: list[tuple[str, str]] = []

    def name(self) -> str:
        return "legacy"

    async def create_agent(self, tools, extensions) -> Any:
        return object()

    async def invoke(self, agent, message) -> str:
        return "legacy-ok"

    async def spawn_sub_agent(  # type: ignore[override]
        self, role: RoleConfig, task: str, tools, extensions
    ) -> str:
        self.spawn_calls.append((role.name, task))
        return "legacy-ok"


class _SnippetPolicy:
    """Fake MemoryPolicy recording snippet fetches + interactions."""

    def __init__(self, snippets: list[str] | None = None) -> None:
        self._snippets = snippets or []
        self.snippet_requests: list[tuple[str, str, int]] = []
        self.recorded: list[tuple[str, str, str]] = []

    def resolve(self, persona, harness_name):  # pragma: no cover
        raise NotImplementedError

    def export_memory_context(self, persona) -> str:
        return ""

    async def get_recent_snippets(self, persona, role, *, limit=10):
        self.snippet_requests.append(
            (getattr(persona, "name", ""), getattr(role, "name", ""), limit)
        )
        return list(self._snippets[:limit])

    async def record_interaction(
        self, persona, role, *, user_message: str, response: str
    ) -> None:
        self.recorded.append(
            (getattr(role, "name", ""), user_message, response)
        )


@pytest.fixture
def personal(personas_dir: Path) -> PersonaConfig:
    return PersonaRegistry(personas_dir).load("personal")


@pytest.fixture
def registry(roles_dir: Path, personas_dir: Path) -> RoleRegistry:
    return RoleRegistry(roles_dir, personas_dir)


@pytest.fixture
def researcher_parent(
    registry: RoleRegistry, personal: PersonaConfig
) -> RoleConfig:
    return registry.load("researcher", personal)


def _spawner(
    personal: PersonaConfig,
    parent: RoleConfig,
    registry: RoleRegistry,
    harness: SdkHarnessAdapter | None = None,
    **kwargs: Any,
) -> tuple[DelegationSpawner, SdkHarnessAdapter]:
    harness = harness or ContextCapturingHarness(personal, parent)
    spawner = DelegationSpawner(
        personal,
        parent,
        harness,
        tools=[],
        extensions=[],
        role_registry=registry,
        **kwargs,
    )
    return spawner, harness


# ── Context construction + threading ─────────────────────────────────


def test_delegate_threads_context_with_sub_role_snippets(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    policy = _SnippetPolicy(["mem-1", "mem-2"])
    spawner, harness = _spawner(
        personal, researcher_parent, registry, memory_policy=policy
    )
    asyncio.run(
        spawner.delegate(
            "writer",
            "draft an email",
            conversation_summary="the user asked for a recap",
        )
    )
    assert isinstance(harness, ContextCapturingHarness)
    ctx = harness.contexts[0]
    assert ctx is not None
    assert ctx.parent_role == "researcher"
    # Identity is the CHILD principal for the hop.
    assert ctx.identity.role == "writer"
    assert ctx.identity.delegation_chain == ("researcher",)
    # Snippets were fetched under the SUB-role.
    assert policy.snippet_requests[0][1] == "writer"
    assert ctx.memory_snippets == ("mem-1", "mem-2")
    assert ctx.conversation_summary == "the user asked for a recap"
    # max_depth_remaining = default ceiling (5) - child depth (1).
    assert ctx.constraints["max_depth_remaining"] == 4


def test_delegate_context_constraints_carry_deadline_and_tools(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    spawner, harness = _spawner(
        personal, researcher_parent, registry, memory_policy=_SnippetPolicy()
    )
    asyncio.run(
        spawner.delegate(
            "writer",
            "quick task",
            deadline_seconds=30,
            allowed_tools=["gmail:send"],
        )
    )
    assert isinstance(harness, ContextCapturingHarness)
    ctx = harness.contexts[0]
    assert ctx is not None
    assert ctx.constraints["deadline_seconds"] == 30
    assert ctx.constraints["allowed_tools"] == ["gmail:send"]


def test_delegate_snippet_failure_degrades_to_empty(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    class _FailingPolicy(_SnippetPolicy):
        async def get_recent_snippets(self, persona, role, *, limit=10):
            raise ConnectionError("memory down")

    spawner, harness = _spawner(
        personal,
        researcher_parent,
        registry,
        memory_policy=_FailingPolicy(),
    )
    result = asyncio.run(spawner.delegate("writer", "t"))
    assert result == "ok"
    assert isinstance(harness, ContextCapturingHarness)
    ctx = harness.contexts[0]
    assert ctx is not None and ctx.memory_snippets == ()


def test_legacy_harness_without_context_kwarg_still_works(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    """Spawner backward compat: pre-P12 adapters get the pre-P12 call."""
    legacy = LegacyHarness(personal, researcher_parent)
    spawner, _ = _spawner(
        personal,
        researcher_parent,
        registry,
        harness=legacy,
        memory_policy=_SnippetPolicy(),
    )
    result = asyncio.run(spawner.delegate("writer", "draft"))
    assert result == "legacy-ok"
    assert legacy.spawn_calls == [("writer", "draft")]


# ── Cycle detection ──────────────────────────────────────────────────


def test_cycle_in_chain_is_denied(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    """A sub-role already in the delegation chain is rejected."""
    identity = AgentIdentity(
        persona=personal.name,
        role="researcher",
        delegation_chain=("writer",),
    )
    spawner, harness = _spawner(
        personal,
        researcher_parent,
        registry,
        identity=identity,
        memory_policy=_SnippetPolicy(),
    )
    with pytest.raises(PermissionError) as exc:
        asyncio.run(spawner.delegate("writer", "again"))
    assert "cycle" in str(exc.value)
    assert "allow_recursive" in str(exc.value)
    assert isinstance(harness, ContextCapturingHarness)
    assert harness.spawn_calls == []


def test_self_delegation_is_denied(
    personal: PersonaConfig,
    registry: RoleRegistry,
) -> None:
    parent = registry.load("researcher", personal)
    parent.delegation["allowed_sub_roles"] = ["researcher"]
    spawner, _harness = _spawner(
        personal, parent, registry, memory_policy=_SnippetPolicy()
    )
    with pytest.raises(PermissionError) as exc:
        asyncio.run(spawner.delegate("researcher", "recurse"))
    assert "cycle" in str(exc.value)


def test_allow_recursive_permits_repeat_role(
    personal: PersonaConfig,
    registry: RoleRegistry,
) -> None:
    parent = registry.load("researcher", personal)
    parent.delegation["allow_recursive"] = True
    identity = AgentIdentity(
        persona=personal.name,
        role="researcher",
        delegation_chain=("writer",),
    )
    spawner, harness = _spawner(
        personal,
        parent,
        registry,
        identity=identity,
        memory_policy=_SnippetPolicy(),
    )
    result = asyncio.run(spawner.delegate("writer", "again"))
    assert result == "ok"
    assert isinstance(harness, ContextCapturingHarness)
    assert harness.spawn_calls == [("writer", "again")]


def test_cycle_check_runs_before_depth_ceiling(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    """A cyclic hop reports the cycle even when depth is also exceeded."""
    identity = AgentIdentity(
        persona=personal.name,
        role="researcher",
        delegation_chain=("writer", "coder", "writer", "coder", "writer"),
    )
    spawner, _ = _spawner(
        personal,
        researcher_parent,
        registry,
        identity=identity,
        memory_policy=_SnippetPolicy(),
    )
    with pytest.raises(PermissionError) as exc:
        asyncio.run(spawner.delegate("writer", "t"))
    assert "cycle" in str(exc.value)


# ── delegate_parallel ────────────────────────────────────────────────


def test_delegate_parallel_isolates_failures(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    spawner, harness = _spawner(
        personal, researcher_parent, registry, memory_policy=_SnippetPolicy()
    )
    assert isinstance(harness, ContextCapturingHarness)
    harness.fail_for_tasks = {"bad"}
    outcomes = asyncio.run(
        spawner.delegate_parallel(
            [("writer", "good-1"), ("writer", "bad"), ("coder", "good-2")]
        )
    )
    assert [o.status for o in outcomes] == ["success", "error", "success"]
    assert outcomes[0].result == "ok"
    assert "ValueError" in outcomes[1].error
    assert outcomes[2].sub_role == "coder"
    # Order matches input, regardless of completion order.
    assert [o.task for o in outcomes] == ["good-1", "bad", "good-2"]


def test_delegate_parallel_respects_concurrency_cap(
    personal: PersonaConfig,
    registry: RoleRegistry,
) -> None:
    parent = registry.load("researcher", personal)
    parent.delegation["max_concurrent"] = 2

    async def scenario() -> list[DelegationOutcome]:
        peak = 0
        active = 0
        lock = asyncio.Lock()

        class _TrackingHarness(ContextCapturingHarness):
            async def spawn_sub_agent(
                self, role, task, tools, extensions, context=None
            ):
                nonlocal peak, active
                async with lock:
                    active += 1
                    peak = max(peak, active)
                await asyncio.sleep(0.01)
                async with lock:
                    active -= 1
                return "ok"

        harness = _TrackingHarness(personal, parent)
        spawner = DelegationSpawner(
            personal,
            parent,
            harness,
            tools=[],
            extensions=[],
            role_registry=registry,
            memory_policy=_SnippetPolicy(),
        )
        outcomes = await spawner.delegate_parallel(
            [("writer", f"t{i}") for i in range(5)]
        )
        assert peak <= 2
        return outcomes

    outcomes = asyncio.run(scenario())
    # The semaphore queues excess tasks instead of tripping the
    # delegate() hard concurrency ceiling — all five succeed.
    assert [o.status for o in outcomes] == ["success"] * 5


def test_delegate_parallel_empty_input_returns_empty(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    spawner, _ = _spawner(
        personal, researcher_parent, registry, memory_policy=_SnippetPolicy()
    )
    assert asyncio.run(spawner.delegate_parallel([])) == []


# ── Monitoring / cancellation ────────────────────────────────────────


def test_list_active_and_cancel(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    async def scenario() -> None:
        harness = ContextCapturingHarness(personal, researcher_parent)
        harness.gate = asyncio.Event()  # never set — blocks forever
        spawner = DelegationSpawner(
            personal,
            researcher_parent,
            harness,
            tools=[],
            extensions=[],
            role_registry=registry,
            memory_policy=_SnippetPolicy(),
        )
        task = asyncio.create_task(spawner.delegate("writer", "long haul"))
        await asyncio.sleep(0.01)

        active = spawner.list_active()
        assert len(active) == 1
        record = active[0]
        assert record.sub_role == "writer"
        assert record.status == "running"
        assert record.duration_ms is None

        assert spawner.cancel(record.delegation_id) is True
        with pytest.raises(asyncio.CancelledError):
            await task

        assert spawner.list_active() == []
        finished = spawner.get_record(record.delegation_id)
        assert finished is not None
        assert finished.status == "cancelled"
        assert finished.finished_at is not None
        # Cancelling a finished delegation is a no-op.
        assert spawner.cancel(record.delegation_id) is False

    asyncio.run(scenario())


def test_cancel_unknown_id_returns_false(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    spawner, _ = _spawner(
        personal, researcher_parent, registry, memory_policy=_SnippetPolicy()
    )
    assert spawner.cancel("no-such-id") is False


def test_deadline_seconds_enforced(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    async def scenario() -> None:
        harness = ContextCapturingHarness(personal, researcher_parent)
        harness.gate = asyncio.Event()  # never set
        spawner = DelegationSpawner(
            personal,
            researcher_parent,
            harness,
            tools=[],
            extensions=[],
            role_registry=registry,
            memory_policy=_SnippetPolicy(),
        )
        with pytest.raises(TimeoutError):
            await spawner.delegate("writer", "slow", deadline_seconds=0.02)
        records = list(spawner.analytics()["by_status"].items())
        assert ("failed", 1) in records

    asyncio.run(scenario())


# ── Analytics ────────────────────────────────────────────────────────


def test_analytics_counts_outcomes(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    spawner, harness = _spawner(
        personal, researcher_parent, registry, memory_policy=_SnippetPolicy()
    )
    assert isinstance(harness, ContextCapturingHarness)
    harness.fail_for_tasks = {"bad"}
    asyncio.run(spawner.delegate("writer", "fine"))
    with pytest.raises(ValueError):
        asyncio.run(spawner.delegate("writer", "bad"))
    stats = spawner.analytics()
    assert stats["total"] == 2
    assert stats["active"] == 0
    assert stats["by_status"] == {"succeeded": 1, "failed": 1}
    assert stats["by_sub_role"] == {"writer": 2}
    assert stats["avg_duration_ms"] is not None


def test_successful_delegation_records_summary_under_parent_role(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    policy = _SnippetPolicy()
    spawner, _ = _spawner(
        personal, researcher_parent, registry, memory_policy=policy
    )
    asyncio.run(spawner.delegate("writer", "draft the recap"))
    assert len(policy.recorded) == 1
    role_name, user_message, response = policy.recorded[0]
    assert role_name == "researcher"  # parent role, not sub-role
    assert user_message.startswith("[delegation] researcher -> writer:")
    assert "draft the recap" in user_message
    assert response == "ok"


def test_failed_delegation_records_no_summary(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    registry: RoleRegistry,
) -> None:
    policy = _SnippetPolicy()
    spawner, harness = _spawner(
        personal, researcher_parent, registry, memory_policy=policy
    )
    assert isinstance(harness, ContextCapturingHarness)
    harness.fail_for_tasks = {"bad"}
    with pytest.raises(ValueError):
        asyncio.run(spawner.delegate("writer", "bad"))
    assert policy.recorded == []
