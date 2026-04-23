"""Tests for persona ``auth_header`` schema evolution.

Covers the backwards-compatible transition from the legacy flat
``auth_header_env: VAR_NAME`` form to the structured
``auth_header: {type, env, header?}`` dict form. See design decision D11
in ``openspec/changes/http-tools-layer/design.md``.

The new shape stores the **env var name** (not the resolved credential)
so that downstream ``resolve_auth_header()`` can read the variable at
discovery time — not at persona-load time.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from assistant.core.persona import PersonaRegistry


def _write_persona_yaml(persona_dir: Path, body: str) -> None:
    """Create a minimal persona.yaml at ``persona_dir`` with the given body."""
    persona_dir.mkdir(parents=True, exist_ok=True)
    (persona_dir / "persona.yaml").write_text(body)


# ── Structured form preserved ────────────────────────────────────────


def test_structured_bearer_auth_header_preserved(tmp_path: Path) -> None:
    """``auth_header: {type: bearer, env: X}`` is passed through as-is.

    The env var name is kept verbatim — the resolver reads the value at
    discovery time, not at persona-load time.
    """
    _write_persona_yaml(
        tmp_path / "p",
        textwrap.dedent(
            """
            name: p
            display_name: P
            database: {url_env: DB}
            graphiti: {url_env: GR}
            auth: {provider: custom, config: {}}
            tool_sources:
              backend:
                base_url_env: BACKEND_URL
                auth_header:
                  type: bearer
                  env: BACKEND_TOKEN
                allowed_tools: []
            """
        ).lstrip(),
    )
    registry = PersonaRegistry(tmp_path)
    cfg = registry.load("p")
    assert cfg.tool_sources["backend"]["auth_header"] == {
        "type": "bearer",
        "env": "BACKEND_TOKEN",
    }


def test_structured_api_key_with_custom_header_preserved(tmp_path: Path) -> None:
    """``auth_header: {type: api-key, env: X, header: Y}`` preserves ``header``."""
    _write_persona_yaml(
        tmp_path / "p",
        textwrap.dedent(
            """
            name: p
            display_name: P
            database: {url_env: DB}
            graphiti: {url_env: GR}
            auth: {provider: custom, config: {}}
            tool_sources:
              api:
                base_url_env: API_URL
                auth_header:
                  type: api-key
                  env: API_KEY
                  header: X-Api-Key
                allowed_tools: []
            """
        ).lstrip(),
    )
    registry = PersonaRegistry(tmp_path)
    cfg = registry.load("p")
    assert cfg.tool_sources["api"]["auth_header"] == {
        "type": "api-key",
        "env": "API_KEY",
        "header": "X-Api-Key",
    }


# ── Legacy form normalized ───────────────────────────────────────────


def test_legacy_auth_header_env_normalized_to_bearer(tmp_path: Path) -> None:
    """Flat ``auth_header_env: FOO`` → ``{type: bearer, env: FOO}``.

    The legacy form auto-normalizes to a structured dict with type=bearer;
    the value is the **env var name**, not the resolved token.
    """
    _write_persona_yaml(
        tmp_path / "p",
        textwrap.dedent(
            """
            name: p
            display_name: P
            database: {url_env: DB}
            graphiti: {url_env: GR}
            auth: {provider: custom, config: {}}
            tool_sources:
              legacy:
                base_url_env: LEGACY_URL
                auth_header_env: LEGACY_TOKEN
                allowed_tools: []
            """
        ).lstrip(),
    )
    registry = PersonaRegistry(tmp_path)
    cfg = registry.load("p")
    assert cfg.tool_sources["legacy"]["auth_header"] == {
        "type": "bearer",
        "env": "LEGACY_TOKEN",
    }


# ── Missing form → None ──────────────────────────────────────────────


def test_missing_auth_header_is_none(tmp_path: Path) -> None:
    """A source with neither ``auth_header`` nor ``auth_header_env`` gets None."""
    _write_persona_yaml(
        tmp_path / "p",
        textwrap.dedent(
            """
            name: p
            display_name: P
            database: {url_env: DB}
            graphiti: {url_env: GR}
            auth: {provider: custom, config: {}}
            tool_sources:
              open:
                base_url_env: OPEN_URL
                allowed_tools: []
            """
        ).lstrip(),
    )
    registry = PersonaRegistry(tmp_path)
    cfg = registry.load("p")
    assert cfg.tool_sources["open"]["auth_header"] is None


# ── allowed_tools semantics unchanged ────────────────────────────────


def test_allowed_tools_preserved_alongside_new_auth_shape(
    tmp_path: Path,
) -> None:
    """``allowed_tools`` is untouched by the ``auth_header`` shape change."""
    _write_persona_yaml(
        tmp_path / "p",
        textwrap.dedent(
            """
            name: p
            display_name: P
            database: {url_env: DB}
            graphiti: {url_env: GR}
            auth: {provider: custom, config: {}}
            tool_sources:
              backend:
                base_url_env: BACKEND_URL
                auth_header: {type: bearer, env: BACKEND_TOKEN}
                allowed_tools: [list_things, get_thing]
            """
        ).lstrip(),
    )
    registry = PersonaRegistry(tmp_path)
    cfg = registry.load("p")
    assert cfg.tool_sources["backend"]["allowed_tools"] == [
        "list_things",
        "get_thing",
    ]


# ── base_url still resolves env var (unchanged) ──────────────────────


def test_base_url_still_resolves_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``base_url_env`` continues to resolve the env var at load time.

    The shape change only affects ``auth_header``; ``base_url`` keeps the
    existing eager-resolution behaviour so callers can detect a missing
    configuration via the empty-string guard in ``cli.py``.
    """
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com")
    _write_persona_yaml(
        tmp_path / "p",
        textwrap.dedent(
            """
            name: p
            display_name: P
            database: {url_env: DB}
            graphiti: {url_env: GR}
            auth: {provider: custom, config: {}}
            tool_sources:
              backend:
                base_url_env: BACKEND_URL
                auth_header: {type: bearer, env: BACKEND_TOKEN}
                allowed_tools: []
            """
        ).lstrip(),
    )
    registry = PersonaRegistry(tmp_path)
    cfg = registry.load("p")
    assert cfg.tool_sources["backend"]["base_url"] == "https://api.example.com"
