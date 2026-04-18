"""Tests for MemoryPolicy protocol — Task 1.7.

Covers: protocol conformance, FileMemoryPolicy behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _make_persona(harnesses: dict | None = None, memory_content: str = "") -> MagicMock:
    persona = MagicMock()
    persona.harnesses = harnesses or {}
    persona.memory_content = memory_content
    return persona


def test_stub_satisfies_protocol() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy, MemoryPolicy

    assert isinstance(FileMemoryPolicy(), MemoryPolicy)


def test_reads_memory_files_from_config() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy

    persona = _make_persona(
        harnesses={"deep_agents": {"enabled": True, "memory_files": ["./CONTEXT.md"]}}
    )
    policy = FileMemoryPolicy()
    cfg = policy.resolve(persona, "deep_agents")
    assert cfg.backend_type == "file"
    assert cfg.config["memory_files"] == ["./CONTEXT.md"]


def test_defaults_to_agents_md() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy

    persona = _make_persona(harnesses={"deep_agents": {"enabled": True}})
    policy = FileMemoryPolicy()
    cfg = policy.resolve(persona, "deep_agents")
    assert cfg.config["memory_files"] == ["./AGENTS.md"]


def test_export_memory_context_returns_content() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy

    persona = _make_persona(memory_content="## Memory\nSome context")
    policy = FileMemoryPolicy()
    content = policy.export_memory_context(persona)
    assert "## Memory" in content
