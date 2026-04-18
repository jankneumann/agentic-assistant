"""MemoryPolicy protocol and FileMemoryPolicy implementation — Task 1.8."""

from __future__ import annotations

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
