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
from assistant.core.toolspec import ToolSpec
from assistant.extensions.base import ExtensionBase


class StubExtension(ExtensionBase):
    """Minimal Extension that satisfies the Protocol.

    Inherits no-op ``initialize``/``shutdown``/``refresh_credentials``
    lifecycle defaults from ``ExtensionBase`` (P10 extension-lifecycle).
    """

    name: str = "stub"

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.scopes: list[str] = list(config.get("scopes", []) or [])

    def tool_specs(self) -> list[ToolSpec]:
        return []

    async def health_check(self) -> HealthStatus:
        return default_health_status_for_unimplemented(self.name)
