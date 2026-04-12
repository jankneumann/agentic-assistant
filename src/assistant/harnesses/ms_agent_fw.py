"""MS Agent Framework harness (P1 stub — full impl lands in P5)."""

from __future__ import annotations

from typing import Any

from assistant.core.role import RoleConfig
from assistant.harnesses.base import HarnessAdapter

_NOT_IMPLEMENTED_MSG = (
    "MS Agent Framework harness is not yet implemented. "
    "Full implementation is deferred to a later proposal (P5 — "
    "ms-graph-extensions). Use '-h deep_agents' for now."
)


class MSAgentFrameworkHarness(HarnessAdapter):
    def name(self) -> str:
        return "ms_agent_framework"

    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def invoke(self, agent: Any, message: str) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def spawn_sub_agent(
        self,
        role: RoleConfig,
        task: str,
        tools: list[Any],
        extensions: list[Any],
    ) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
