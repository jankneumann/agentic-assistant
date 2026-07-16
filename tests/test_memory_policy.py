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


# ── FileMemoryPolicy.get_recent_snippets (memory-retrieval-activation) ──


def test_file_snippets_empty_when_no_memory_content() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy

    persona = _make_persona(memory_content="")
    assert FileMemoryPolicy().get_recent_snippets(persona, MagicMock()) == []


def test_file_snippets_return_sections_most_recent_first() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy

    persona = _make_persona(
        memory_content="## Oldest\nalpha\n\n## Middle\nbeta\n\n## Newest\ngamma"
    )
    snippets = FileMemoryPolicy().get_recent_snippets(persona, MagicMock())
    assert len(snippets) == 3
    assert "Newest" in snippets[0]
    assert "Middle" in snippets[1]
    assert "Oldest" in snippets[2]


def test_file_snippets_respect_limit() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy

    content = "\n\n".join(f"## Section {i}\nbody {i}" for i in range(8))
    persona = _make_persona(memory_content=content)
    snippets = FileMemoryPolicy().get_recent_snippets(
        persona, MagicMock(), limit=3
    )
    assert len(snippets) == 3
    assert "Section 7" in snippets[0]


def test_file_snippets_respect_total_char_budget() -> None:
    from assistant.core.capabilities.memory import (
        _FILE_SNIPPET_CHAR_BUDGET,
        FileMemoryPolicy,
    )

    big = "x" * (_FILE_SNIPPET_CHAR_BUDGET + 500)
    persona = _make_persona(
        memory_content=f"## Old\nshould not fit\n\n## New\n{big}"
    )
    snippets = FileMemoryPolicy().get_recent_snippets(persona, MagicMock())
    total = sum(len(s) for s in snippets)
    assert total <= _FILE_SNIPPET_CHAR_BUDGET
    # The newest section consumed the whole budget; the older section
    # must not appear at all.
    assert not any("should not fit" in s for s in snippets)


def test_file_snippets_whole_content_when_no_headings() -> None:
    from assistant.core.capabilities.memory import FileMemoryPolicy

    persona = _make_persona(memory_content="just some prose, no headings")
    snippets = FileMemoryPolicy().get_recent_snippets(persona, MagicMock())
    assert snippets == ["just some prose, no headings"]


def test_file_record_interaction_is_noop() -> None:
    import asyncio

    from assistant.core.capabilities.memory import FileMemoryPolicy

    persona = _make_persona(memory_content="## Memory\ncontext")
    result = asyncio.run(
        FileMemoryPolicy().record_interaction(
            persona, MagicMock(), user_message="hi", response="hello"
        )
    )
    assert result is None
