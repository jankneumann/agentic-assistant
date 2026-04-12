"""Harness adapter base class."""

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

    @abstractmethod
    def name(self) -> str: ...
