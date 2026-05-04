"""Shared stub implementation used by all 7 P1 extension modules.

Each module re-exports a class and a ``create_extension`` factory that bind
a specific ``name``. Real implementations replace this file per-module in
P4/P5.
"""

from __future__ import annotations

from typing import Any

from assistant.core.resilience import (
    HealthStatus,
    default_health_status_for_unimplemented,
)


class StubExtension:
    """Minimal Extension that satisfies the Protocol."""

    name: str = "stub"

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.scopes: list[str] = list(config.get("scopes", []) or [])

    def as_langchain_tools(self) -> list[Any]:
        return []

    def as_ms_agent_tools(self) -> list[Any]:
        return []

    async def health_check(self) -> HealthStatus:
        return default_health_status_for_unimplemented(self.name)
