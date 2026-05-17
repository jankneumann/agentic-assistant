from __future__ import annotations

from types import SimpleNamespace

from assistant.harnesses.base import SdkHarnessAdapter


class _FakeHarness(SdkHarnessAdapter):
    def name(self) -> str:
        return "fake-sdk"

    async def create_agent(self, tools: list[object], extensions: list[object]) -> object:
        return {"tools": tools, "extensions": extensions}

    async def invoke(self, agent: object, message: str) -> str:
        return f"ok:{message}"

    async def spawn_sub_agent(self, role: object, task: str, tools: list[object], extensions: list[object]) -> str:
        return f"sub:{task}"


def _fake_persona() -> object:
    return SimpleNamespace(name="personal")


def _fake_role() -> object:
    return SimpleNamespace(name="chief_of_staff")


async def test_harness_adapter_minimum_conformance() -> None:
    harness = _FakeHarness(_fake_persona(), _fake_role())

    assert harness.harness_type() == "sdk"
    assert harness.name() == "fake-sdk"

    agent = await harness.create_agent(["t1"], ["e1"])
    assert agent == {"tools": ["t1"], "extensions": ["e1"]}
    assert await harness.invoke(agent, "hello") == "ok:hello"
    assert await harness.spawn_sub_agent(_fake_role(), "do thing", [], []) == "sub:do thing"
