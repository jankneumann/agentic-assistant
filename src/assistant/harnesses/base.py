"""Harness adapter base classes — SDK and Host tiers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig


class HarnessAdapter(ABC):
    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        self.persona = persona
        self.role = role

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def harness_type(self) -> str: ...


class SdkHarnessAdapter(HarnessAdapter):
    """SDK-based harness that owns the agent loop."""

    def harness_type(self) -> str:
        return "sdk"

    @abstractmethod
    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any: ...

    @abstractmethod
    async def invoke(self, agent: Any, message: str) -> str: ...

    @abstractmethod
    async def spawn_sub_agent(
        self,
        role: RoleConfig,
        task: str,
        tools: list[Any],
        extensions: list[Any],
    ) -> str: ...


class HostHarnessAdapter(HarnessAdapter):
    """Host harness where the host owns the agent loop.

    Our code exports configuration artifacts; the host provides
    memory, sandbox, permissions, and tool execution.
    """

    def harness_type(self) -> str:
        return "host"

    @abstractmethod
    def export_context(self, capabilities: Any) -> dict[str, str]: ...

    @abstractmethod
    def export_guardrail_declarations(
        self, capabilities: Any
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def export_tool_manifest(
        self, capabilities: Any
    ) -> dict[str, Any]: ...
