"""Tests for prompt-composition spec.

Covers all 6 scenarios across 2 requirements in
``openspec/changes/bootstrap-vertical-slice/specs/prompt-composition/spec.md``.
"""

from __future__ import annotations

from pathlib import Path

from assistant.core.composition import BASE_SYSTEM_PROMPT, compose_system_prompt
from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry


def _make_persona(
    prompt_aug: str = "## Persona\nabc", display: str = "Personal"
) -> PersonaConfig:
    return PersonaConfig(
        name="p",
        display_name=display,
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={},
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
        prompt_augmentation=prompt_aug,
    )


def _make_role(
    prompt: str = "## Role\nxyz",
    *,
    allowed_sub_roles: list[str] | None = None,
    always_plan: bool = False,
    preferred_tools: list[str] | None = None,
    display: str = "Researcher",
) -> RoleConfig:
    return RoleConfig(
        name="r",
        display_name=display,
        description="",
        prompt=prompt,
        preferred_tools=preferred_tools or [],
        delegation={"allowed_sub_roles": allowed_sub_roles or []},
        planning={"always_plan": always_plan} if always_plan else {},
        context={},
    )


def test_all_three_layers_present_in_order() -> None:
    persona = _make_persona(prompt_aug="## Persona\nabc")
    role = _make_role(prompt="## Role\nxyz")
    out = compose_system_prompt(persona, role)
    assert BASE_SYSTEM_PROMPT.rstrip() in out
    # base → persona → role order
    assert out.index("## Persona") > out.index("Core Rules")
    assert out.index("## Role") > out.index("## Persona")
    # separator between layers
    assert "\n\n---\n\n" in out


def test_empty_persona_augmentation_is_omitted() -> None:
    persona = _make_persona(prompt_aug="")
    role = _make_role()
    out = compose_system_prompt(persona, role)
    # There should still be a separator before role + active config
    # but no persona layer block between base and role
    parts = out.split("\n\n---\n\n")
    # base, role, active_config (three parts)
    assert len(parts) == 3


def test_empty_role_prompt_is_omitted() -> None:
    persona = _make_persona(prompt_aug="## Persona\nabc")
    role = _make_role(prompt="")
    out = compose_system_prompt(persona, role)
    parts = out.split("\n\n---\n\n")
    # base, persona, active_config (three parts)
    assert len(parts) == 3


def test_active_configuration_lists_persona_role_and_sub_roles() -> None:
    persona = _make_persona(display="Personal")
    role = _make_role(
        display="Researcher", allowed_sub_roles=["writer", "coder"]
    )
    out = compose_system_prompt(persona, role)
    assert "**Persona**: Personal" in out
    assert "**Role**: Researcher" in out
    assert "**Sub-roles**: writer, coder" in out


def test_no_allowed_sub_roles_renders_none() -> None:
    persona = _make_persona()
    role = _make_role(allowed_sub_roles=[])
    out = compose_system_prompt(persona, role)
    assert "**Sub-roles**: none" in out


def test_always_plan_includes_planning_line() -> None:
    persona = _make_persona()
    role = _make_role(always_plan=True)
    out = compose_system_prompt(persona, role)
    assert "Planning" in out
    assert "plan" in out.lower()


def test_composition_against_fixture_configs(
    personas_dir: Path, roles_dir: Path
) -> None:
    """Integration: composes against the FIXTURE personal + researcher configs.

    Replaces the removed ``test_composition_against_real_configs`` (which
    asserted on strings sourced from the real private submodule). The
    fixture files under the personal-persona fixture tree carry
    intentional, tests-only sentinels (``FIXTURE_PERSONA_SENTINEL_v1`` in
    prompt.md, ``FIXTURE_ROLE_SENTINEL_v1`` in roles/researcher.yaml) so
    we can prove end-to-end composition coverage without coupling the
    assertion to any private content.
    """
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("researcher", persona)
    out = compose_system_prompt(persona, role)
    # Base + role presence (base-role strings are public, in roles/).
    assert "Role: Researcher" in out
    assert "**Persona**: Personal" in out
    assert "**Role**: Researcher" in out
    # Persona-layer fixture sentinel (sourced from fixture prompt.md).
    assert "FIXTURE_PERSONA_SENTINEL_v1" in out
    # Role-layer fixture sentinel (sourced from fixture role override).
    assert "FIXTURE_ROLE_SENTINEL_v1" in out
