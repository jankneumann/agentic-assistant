"""Tests for persona-registry spec.

Covers all 12 scenarios across 5 requirements in
``openspec/changes/bootstrap-vertical-slice/specs/persona-registry/spec.md``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from assistant.core.persona import PersonaConfig, PersonaRegistry

# ── Persona Discovery ────────────────────────────────────────────────


def test_populated_submodule_is_discovered(personas_dir: Path) -> None:
    registry = PersonaRegistry(personas_dir)
    assert "personal" in registry.discover()


def test_discover_returns_sorted(personas_dir: Path) -> None:
    registry = PersonaRegistry(personas_dir)
    discovered = registry.discover()
    assert discovered == sorted(discovered)


def test_template_directory_is_excluded(personas_dir: Path) -> None:
    registry = PersonaRegistry(personas_dir)
    assert "_template" not in registry.discover()


def test_uninitialized_submodule_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()  # directory but no persona.yaml
    (tmp_path / "personal").mkdir()
    (tmp_path / "personal" / "persona.yaml").write_text(
        "name: personal\ndisplay_name: Personal\n"
        "database: {url_env: X}\ngraphiti: {url_env: Y}\n"
        "auth: {provider: custom, config: {}}\n"
    )
    registry = PersonaRegistry(tmp_path)
    discovered = registry.discover()
    assert "personal" in discovered
    assert "work" not in discovered


# ── Persona Loading ──────────────────────────────────────────────────


def test_load_resolves_env_var_references(
    personas_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PERSONAL_DATABASE_URL", "postgresql://localhost/x")
    registry = PersonaRegistry(personas_dir)
    cfg = registry.load("personal")
    assert cfg.database_url == "postgresql://localhost/x"


def test_missing_env_var_resolves_to_empty_string(
    personas_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PERSONAL_DATABASE_URL", raising=False)
    registry = PersonaRegistry(personas_dir)
    cfg = registry.load("personal")
    assert cfg.database_url == ""


def test_loaded_result_is_cached(personas_dir: Path) -> None:
    registry = PersonaRegistry(personas_dir)
    first = registry.load("personal")
    second = registry.load("personal")
    assert first is second


# ── Persona Prompt and Memory Inclusion ──────────────────────────────


def test_prompt_md_is_loaded(personas_dir: Path) -> None:
    registry = PersonaRegistry(personas_dir)
    cfg = registry.load("personal")
    assert "Personal Persona Context" in cfg.prompt_augmentation


def test_memory_md_is_optional(tmp_path: Path) -> None:
    persona_dir = tmp_path / "noprompts"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        "name: noprompts\ndisplay_name: No Prompts\n"
        "database: {url_env: X}\ngraphiti: {url_env: Y}\n"
        "auth: {provider: custom, config: {}}\n"
    )
    registry = PersonaRegistry(tmp_path)
    cfg = registry.load("noprompts")
    assert cfg.memory_content == ""
    assert cfg.prompt_augmentation == ""


# ── Helpful Error on Uninitialized Submodule ─────────────────────────


def test_error_message_lists_alternatives(tmp_path: Path) -> None:
    (tmp_path / "personal").mkdir()
    (tmp_path / "personal" / "persona.yaml").write_text(
        "name: personal\ndisplay_name: Personal\n"
        "database: {url_env: X}\ngraphiti: {url_env: Y}\n"
        "auth: {provider: custom, config: {}}\n"
    )
    registry = PersonaRegistry(tmp_path)
    with pytest.raises(ValueError) as exc:
        registry.load("work")
    msg = str(exc.value)
    assert "Available:" in msg
    assert "git submodule update --init" in msg


# ── Extension Loader Fallback Order ──────────────────────────────────


@pytest.fixture
def persona_with_fake_ext(tmp_path: Path) -> PersonaConfig:
    """Build a PersonaConfig pointing at an in-tmp extensions dir."""
    extensions_dir = tmp_path / "fake_ext_dir"
    extensions_dir.mkdir()
    return PersonaConfig(
        name="fake",
        display_name="Fake",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={},
        tool_sources={},
        extensions=[{"name": "gmail", "module": "gmail", "config": {}}],
        extensions_dir=extensions_dir,
    )


def test_private_extension_takes_precedence(
    persona_with_fake_ext: PersonaConfig,
) -> None:
    private_file = persona_with_fake_ext.extensions_dir / "gmail.py"
    private_file.write_text(
        textwrap.dedent(
            """
            class _PrivateGmail:
                name = "private-gmail"
                def __init__(self, config): self.config = config
                def as_langchain_tools(self): return []
                def as_ms_agent_tools(self): return []
                async def health_check(self): return True

            def create_extension(config):
                return _PrivateGmail(config)
            """
        )
    )
    registry = PersonaRegistry()
    loaded = registry.load_extensions(persona_with_fake_ext)
    assert len(loaded) == 1
    assert loaded[0].name == "private-gmail"


def test_public_fallback_used_when_no_private_override(
    persona_with_fake_ext: PersonaConfig,
) -> None:
    # persona_with_fake_ext's extensions_dir contains no gmail.py — should
    # fall back to the public stub at src/assistant/extensions/gmail.py
    registry = PersonaRegistry()
    loaded = registry.load_extensions(persona_with_fake_ext)
    assert len(loaded) == 1
    assert loaded[0].name == "gmail"


def test_missing_module_logs_warning_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    persona = PersonaConfig(
        name="fake",
        display_name="Fake",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={},
        tool_sources={},
        extensions=[
            {"name": "doesnt_exist", "module": "doesnt_exist", "config": {}}
        ],
        extensions_dir=tmp_path,
    )
    registry = PersonaRegistry()
    with caplog.at_level("WARNING"):
        loaded = registry.load_extensions(persona)
    assert loaded == []
    assert any("doesnt_exist" in rec.message for rec in caplog.records)
