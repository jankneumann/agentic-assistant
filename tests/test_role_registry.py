"""Tests for role-registry spec.

Covers all 9 scenarios across 3 requirements in
``openspec/changes/bootstrap-vertical-slice/specs/role-registry/spec.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.core.role import RoleRegistry


@pytest.fixture
def personal_persona(personas_dir: Path) -> PersonaConfig:
    return PersonaRegistry(personas_dir).load("personal")


# ── Role Discovery ───────────────────────────────────────────────────


def test_public_role_is_discovered(roles_dir: Path) -> None:
    registry = RoleRegistry(roles_dir)
    assert "researcher" in registry.discover()


def test_template_directory_is_excluded(roles_dir: Path) -> None:
    registry = RoleRegistry(roles_dir)
    assert "_template" not in registry.discover()


# ── Persona-Scoped Role Availability ─────────────────────────────────


def test_disabled_role_is_filtered_out(
    roles_dir: Path, personas_dir: Path
) -> None:
    persona = PersonaRegistry(personas_dir).load("personal")
    persona.disabled_roles = ["coder"]
    registry = RoleRegistry(roles_dir, personas_dir)
    available = registry.available_for_persona(persona)
    assert "coder" not in available
    assert "researcher" in available


# ── Role Loading with Persona Overrides ──────────────────────────────


def test_base_role_loads_without_overrides(
    roles_dir: Path, personas_dir: Path
) -> None:
    # planner has no override in personas/personal/roles/ → base values only
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("planner", persona)
    assert "content_analyzer:knowledge_graph" in role.preferred_tools


def test_prompt_append_extends_base_prompt(
    roles_dir: Path, personas_dir: Path
) -> None:
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("researcher", persona)
    assert "Role: Researcher" in role.prompt  # base content present
    assert "Personal Context Additions" in role.prompt  # override appended
    assert role.prompt.index("Role: Researcher") < role.prompt.index(
        "Personal Context Additions"
    )


def test_additional_preferred_tools_extends_list(
    roles_dir: Path, personas_dir: Path
) -> None:
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load(
        "chief_of_staff", persona
    )
    # base has content_analyzer:*; override adds gmail:send etc
    assert "content_analyzer:daily_digest" in role.preferred_tools
    assert "gmail:send" in role.preferred_tools


def test_delegation_overrides_update_individual_keys(
    tmp_path: Path, roles_dir: Path
) -> None:
    # Build a minimal persona on tmp_path with a custom override
    persona_dir = tmp_path / "fake"
    (persona_dir / "roles").mkdir(parents=True)
    (persona_dir / "persona.yaml").write_text(
        "name: fake\ndisplay_name: Fake\n"
        "database: {url_env: X}\ngraphiti: {url_env: Y}\n"
        "auth: {provider: custom, config: {}}\n"
    )
    (persona_dir / "roles" / "researcher.yaml").write_text(
        "delegation_overrides:\n  max_concurrent: 2\n"
    )
    persona = PersonaRegistry(tmp_path).load("fake")
    role = RoleRegistry(roles_dir, tmp_path).load("researcher", persona)
    assert role.delegation["max_concurrent"] == 2
    assert role.delegation["can_spawn_sub_agents"] is True  # base preserved


def test_context_overrides_update_individual_keys(
    roles_dir: Path, personas_dir: Path
) -> None:
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("researcher", persona)
    # personal's researcher override sets output_format: conversational
    assert role.context["output_format"] == "conversational"
    # base researcher.role.yaml has other context keys preserved
    assert role.context.get("save_findings") is True


def test_missing_role_raises_with_available_list(
    roles_dir: Path, personas_dir: Path
) -> None:
    persona = PersonaRegistry(personas_dir).load("personal")
    registry = RoleRegistry(roles_dir, personas_dir)
    with pytest.raises(ValueError) as exc:
        registry.load("nonexistent", persona)
    assert "Available:" in str(exc.value)
