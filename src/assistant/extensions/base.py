"""Extension protocol.

Extensions wrap external system APIs (Gmail, MS Graph, etc.) and expose them
to the underlying harness. P1 ships empty-tool stubs; P4 adds real Google
implementations, P5 adds MS implementations.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from assistant.core.resilience import HealthStatus


@runtime_checkable
class Extension(Protocol):
    name: str

    def as_langchain_tools(self) -> list[Any]: ...

    def as_ms_agent_tools(self) -> list[Any]: ...

    async def health_check(self) -> HealthStatus: ...
