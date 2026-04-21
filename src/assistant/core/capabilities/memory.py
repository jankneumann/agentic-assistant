"""MemoryPolicy protocol, FileMemoryPolicy, and PostgresGraphitiMemoryPolicy."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from assistant.core.capabilities.types import MemoryConfig, MemoryScoping


@runtime_checkable
class MemoryPolicy(Protocol):
    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig: ...
    def export_memory_context(self, persona: Any) -> str: ...


class FileMemoryPolicy:
    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig:
        harness_cfg = persona.harnesses.get(harness_name, {}) or {}
        memory_files = harness_cfg.get("memory_files") or ["./AGENTS.md"]
        return MemoryConfig(
            backend_type="file",
            config={"memory_files": memory_files},
            scoping=MemoryScoping(),
        )

    def export_memory_context(self, persona: Any) -> str:
        return persona.memory_content or ""


class PostgresGraphitiMemoryPolicy:
    """MemoryPolicy backed by MemoryManager (Postgres + Graphiti)."""

    def __init__(self, persona: Any) -> None:
        from assistant.core.db import async_session_factory, create_async_engine
        from assistant.core.graphiti import create_graphiti_client
        from assistant.core.memory import MemoryManager

        engine = create_async_engine(persona)
        session_fac = async_session_factory(engine)
        graphiti = create_graphiti_client(persona)
        self._manager = MemoryManager(session_fac, graphiti_client=graphiti)
        self._persona_name = persona.name

    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig:
        return MemoryConfig(
            backend_type="postgres",
            config={},
            scoping=MemoryScoping(),
        )

    def export_memory_context(self, persona: Any) -> str:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, self._manager.export_memory(persona.name)
                ).result()
        return asyncio.run(self._manager.export_memory(persona.name))


class HostProvidedMemoryPolicy:
    """Returns host_provided config for host harnesses (Claude Code, Codex)."""

    def resolve(self, persona: Any, harness_name: str) -> MemoryConfig:
        return MemoryConfig(
            backend_type="host_provided",
            config={},
            scoping=MemoryScoping(),
        )

    def export_memory_context(self, persona: Any) -> str:
        return persona.memory_content or ""
