"""Tests for delegation-spawner spec.

Covers all 5 scenarios across 3 requirements in
``openspec/changes/bootstrap-vertical-slice/specs/delegation-spawner/spec.md``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.spawner import DelegationSpawner
from assistant.harnesses.base import HarnessAdapter


class FakeHarness(HarnessAdapter):
    """Captures spawn_sub_agent calls and exposes a gate event for
    concurrency tests."""

    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        super().__init__(persona, role)
        self.spawn_calls: list[tuple[str, str]] = []
        self.gate: asyncio.Event | None = None
        self.response: str = "ok"

    def name(self) -> str:
        return "fake"

    async def create_agent(self, tools, extensions) -> Any:
        return object()

    async def invoke(self, agent, message) -> str:
        return self.response

    async def spawn_sub_agent(
        self, role: RoleConfig, task: str, tools, extensions
    ) -> str:
        self.spawn_calls.append((role.name, task))
        if self.gate is not None:
            await self.gate.wait()
        return self.response


@pytest.fixture
def personal(personas_dir: Path) -> PersonaConfig:
    return PersonaRegistry(personas_dir).load("personal")


@pytest.fixture
def researcher_parent(
    roles_dir: Path, personas_dir: Path, personal: PersonaConfig
) -> RoleConfig:
    return RoleRegistry(roles_dir, personas_dir).load("researcher", personal)


def test_disallowed_sub_role_raises_value_error(
    roles_dir: Path,
    personas_dir: Path,
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
) -> None:
    # researcher allows writer+coder; not planner
    spawner = DelegationSpawner(
        personal,
        researcher_parent,
        FakeHarness(personal, researcher_parent),
        tools=[],
        extensions=[],
        role_registry=RoleRegistry(roles_dir, personas_dir),
    )
    with pytest.raises(ValueError) as exc:
        asyncio.run(spawner.delegate("planner", "x"))
    assert "Allowed" in str(exc.value)


def test_allowed_sub_role_proceeds_to_harness(
    roles_dir: Path,
    personas_dir: Path,
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
) -> None:
    harness = FakeHarness(personal, researcher_parent)
    spawner = DelegationSpawner(
        personal,
        researcher_parent,
        harness,
        tools=[],
        extensions=[],
        role_registry=RoleRegistry(roles_dir, personas_dir),
    )
    asyncio.run(spawner.delegate("writer", "draft an email"))
    assert harness.spawn_calls == [("writer", "draft an email")]


def test_exceeding_max_concurrent_raises(
    roles_dir: Path,
    personas_dir: Path,
    personal: PersonaConfig,
) -> None:
    # Build a parent role with max_concurrent=1
    registry = RoleRegistry(roles_dir, personas_dir)
    parent = registry.load("researcher", personal)
    parent.delegation["max_concurrent"] = 1

    async def scenario() -> None:
        harness = FakeHarness(personal, parent)
        harness.gate = asyncio.Event()
        spawner = DelegationSpawner(
            personal,
            parent,
            harness,
            tools=[],
            extensions=[],
            role_registry=registry,
        )
        first = asyncio.create_task(spawner.delegate("writer", "t1"))
        # Yield to let 'first' start and bump _active to 1
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError) as exc:
            await spawner.delegate("writer", "t2")
        assert "Max concurrent" in str(exc.value) or "max concurrent" in str(
            exc.value
        ).lower()
        harness.gate.set()
        await first

    asyncio.run(scenario())


def test_count_decrements_after_delegation(
    roles_dir: Path,
    personas_dir: Path,
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
) -> None:
    researcher_parent.delegation["max_concurrent"] = 1
    harness = FakeHarness(personal, researcher_parent)
    spawner = DelegationSpawner(
        personal,
        researcher_parent,
        harness,
        tools=[],
        extensions=[],
        role_registry=RoleRegistry(roles_dir, personas_dir),
    )
    asyncio.run(spawner.delegate("writer", "t1"))
    # After completion, counter should allow a second delegation
    asyncio.run(spawner.delegate("writer", "t2"))
    assert len(harness.spawn_calls) == 2


def test_disabled_role_for_persona_raises(
    roles_dir: Path,
    personas_dir: Path,
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
) -> None:
    personal.disabled_roles = ["writer"]
    spawner = DelegationSpawner(
        personal,
        researcher_parent,
        FakeHarness(personal, researcher_parent),
        tools=[],
        extensions=[],
        role_registry=RoleRegistry(roles_dir, personas_dir),
    )
    with pytest.raises(ValueError) as exc:
        asyncio.run(spawner.delegate("writer", "x"))
    assert "personal" in str(exc.value)
