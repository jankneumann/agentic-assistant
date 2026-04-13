"""Unit tests for the ASSISTANT_PERSONAS_DIR env-var contract.

Locks in the precedence rule:

    explicit constructor arg  >  env var  >  Path("personas") default

The env var was added as a scope expansion during implementation of
OpenSpec change ``test-privacy-boundary`` (see session-log.md ->
Implementation phase, decision 1). Without these tests, a future
refactor could silently break the only mechanism by which in-process
CLI tests honor the privacy-boundary repoint.

Covers Review finding IR-C2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assistant.core.persona import PersonaRegistry
from assistant.core.role import RoleRegistry

# ── PersonaRegistry ────────────────────────────────────────────────────


def test_persona_registry_no_args_reads_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PersonaRegistry() with no argument uses ASSISTANT_PERSONAS_DIR when set."""
    custom = tmp_path / "custom-personas"
    custom.mkdir()
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(custom))
    reg = PersonaRegistry()
    assert reg.personas_dir == custom


def test_persona_registry_explicit_arg_overrides_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PersonaRegistry(path) ignores ASSISTANT_PERSONAS_DIR -- explicit wins."""
    env_path = tmp_path / "env-personas"
    explicit = tmp_path / "explicit-personas"
    env_path.mkdir()
    explicit.mkdir()
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(env_path))
    reg = PersonaRegistry(explicit)
    assert reg.personas_dir == explicit


def test_persona_registry_no_args_no_env_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With env var unset and no arg, PersonaRegistry defaults to Path('personas')."""
    monkeypatch.delenv("ASSISTANT_PERSONAS_DIR", raising=False)
    reg = PersonaRegistry()
    assert reg.personas_dir == Path("personas")


# ── RoleRegistry ───────────────────────────────────────────────────────


def test_role_registry_no_args_reads_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RoleRegistry() with no personas_dir argument uses ASSISTANT_PERSONAS_DIR."""
    custom = tmp_path / "custom-personas"
    custom.mkdir()
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(custom))
    reg = RoleRegistry()
    assert reg.personas_dir == custom


def test_role_registry_explicit_personas_dir_overrides_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RoleRegistry(personas_dir=explicit) ignores env var."""
    env_path = tmp_path / "env-personas"
    explicit = tmp_path / "explicit-personas"
    env_path.mkdir()
    explicit.mkdir()
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(env_path))
    reg = RoleRegistry(personas_dir=explicit)
    assert reg.personas_dir == explicit


def test_role_registry_no_args_no_env_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With env var unset and no arg, RoleRegistry defaults to Path('personas')."""
    monkeypatch.delenv("ASSISTANT_PERSONAS_DIR", raising=False)
    reg = RoleRegistry()
    assert reg.personas_dir == Path("personas")
