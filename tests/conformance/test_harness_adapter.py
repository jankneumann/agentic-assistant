"""Minimum conformance contract for SdkHarnessAdapter implementations.

Asserts that a harness implementing only the abstract surface satisfies the
protocol. Kept in lockstep with ``assistant.harnesses.base`` -- when the
abstract signatures change, this fake must change with them, which is the
point: it fails loudly rather than letting implementations drift.
"""

from __future__ import annotations

from typing import Any

import pytest

from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.context import DelegationContext
from assistant.harnesses.base import SdkHarnessAdapter


class _FakeHarness(SdkHarnessAdapter):
    """Implements exactly the abstract surface -- nothing more."""

    def name(self) -> str:
        return "fake-sdk"

    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any:
        return {"tools": tools, "extensions": extensions}

    async def invoke(self, agent: Any, message: str) -> str:
        return f"ok:{message}"

    async def spawn_sub_agent(
        self,
        role: RoleConfig,
        task: str,
        tools: list[Any],
        extensions: list[Any],
        context: DelegationContext | None = None,
    ) -> str:
        # ``context`` is the P12 additive parameter: None must preserve
        # pre-P12 behavior exactly.
        return f"sub:{task}"


@pytest.fixture
def personal(personas_dir) -> PersonaConfig:
    return PersonaRegistry(personas_dir).load("personal")


@pytest.fixture
def researcher(roles_dir, personas_dir, personal) -> RoleConfig:
    return RoleRegistry(roles_dir, personas_dir).load("researcher", personal)


async def test_harness_adapter_minimum_conformance(
    personal: PersonaConfig, researcher: RoleConfig
) -> None:
    harness = _FakeHarness(personal, researcher)

    assert harness.harness_type() == "sdk"
    assert harness.name() == "fake-sdk"

    agent = await harness.create_agent(["t1"], ["e1"])
    assert agent == {"tools": ["t1"], "extensions": ["e1"]}
    assert await harness.invoke(agent, "hello") == "ok:hello"

    assert (
        await harness.spawn_sub_agent(researcher, "do thing", [], [])
        == "sub:do thing"
    )


async def test_spawn_sub_agent_accepts_delegation_context(
    personal: PersonaConfig, researcher: RoleConfig
) -> None:
    """The P12 ``context`` parameter must be accepted, not just defaulted."""
    harness = _FakeHarness(personal, researcher)

    result = await harness.spawn_sub_agent(
        researcher, "with ctx", [], [], context=None
    )
    assert result == "sub:with ctx"
