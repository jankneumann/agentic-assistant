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
    # planner has no override in the persona's role-overrides dir → base
    # values only
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("planner", persona)
    assert "content_analyzer:knowledge_graph" in role.preferred_tools


def test_prompt_append_extends_base_prompt(
    roles_dir: Path, personas_dir: Path
) -> None:
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("researcher", persona)
    assert "Role: Researcher" in role.prompt  # base content present
    # Fixture-defined sentinel in the fixture's researcher role-override
    # yaml prompt_append -- proves override was appended without asserting
    # on private-submodule content.
    assert "FIXTURE_ROLE_SENTINEL_v1" in role.prompt
    assert role.prompt.index("Role: Researcher") < role.prompt.index(
        "FIXTURE_ROLE_SENTINEL_v1"
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


# ── Teacher role (add-teacher-role) ──────────────────────────────────


def test_teacher_role_is_discoverable(roles_dir: Path) -> None:
    """teacher-role/teacher-role-is-discoverable."""
    registry = RoleRegistry(roles_dir)
    assert "teacher" in registry.discover()


def test_teacher_preferred_tools(
    roles_dir: Path, personas_dir: Path
) -> None:
    """teacher-role/teacher-declares-kb-tool-preferences."""
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("teacher", persona)
    assert "content_analyzer:search" in role.preferred_tools
    assert "content_analyzer:knowledge_graph" in role.preferred_tools


def test_teacher_delegates_only_to_researcher(
    roles_dir: Path, personas_dir: Path
) -> None:
    """teacher-role/teacher-declares-researcher-delegation."""
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("teacher", persona)
    assert role.delegation["allowed_sub_roles"] == ["researcher"]
    assert role.delegation["can_spawn_sub_agents"] is True
    assert role.delegation["max_concurrent"] == 1


def test_teacher_skills_dir_resolves(
    roles_dir: Path, personas_dir: Path
) -> None:
    """teacher-role/teacher-skills-directory-populated."""
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("teacher", persona)
    assert role.skills_dir == "./roles/teacher/skills"
    skills_path = Path(role.skills_dir)
    assert skills_path.exists()
    assert (skills_path / "feynman.md").exists()
    assert (skills_path / "socratic.md").exists()


def test_feynman_skill_defines_explain_check_reteach_loop(
    roles_dir: Path,
) -> None:
    """teacher-role/feynman-skill-defines-explain-check-reteach-loop.

    Asserts the spec-mandated structural markers in feynman.md:
    - Step 1 with ≤150-word plain-language explanation + flagged analogy
    - Step 3 with 1-10 score + ≤100-word re-teach of gaps
    - Completion signal phrase "You've got it"
    - knowledge_graph consultation permitted before Step 1 only
    """
    content = (roles_dir / "teacher" / "skills" / "feynman.md").read_text()
    lc = content.lower()

    # Step 1 markers
    assert "step 1" in lc
    assert "150" in content, "Step 1 word-budget marker missing"
    assert "analogy" in lc

    # Step 3 markers
    assert "step 3" in lc
    # feynman.md uses an en-dash (U+2013) per typographic convention.
    # Construct via chr() so the source stays ASCII-only and ruff's
    # RUF001 (ambiguous unicode) doesn't fire on the test file.
    en_dash_form = f"1{chr(0x2013)}10"
    assert "1-10" in content or en_dash_form in content, (
        "1-10 scoring scale missing"
    )
    assert "100" in content, "Step 3 re-teach word budget missing"

    # Completion signal — exact phrase per spec.
    assert "you've got it" in lc

    # Tool-timing per D6/spec: knowledge_graph only before Step 1.
    assert "before step 1 only" in lc, (
        "knowledge_graph consultation timing rule missing"
    )


def test_socratic_skill_defines_question_only_loop(roles_dir: Path) -> None:
    """teacher-role/socratic-skill-defines-question-only-loop.

    Asserts the spec-mandated structural markers in socratic.md:
    - States that the assistant asks questions and does NOT state facts
    - Completion signal phrase "You're teaching yourself now"
    - knowledge_graph may be consulted silently between questions
    """
    content = (roles_dir / "teacher" / "skills" / "socratic.md").read_text()
    lc = content.lower()

    # Question-only loop discipline.
    assert "question" in lc
    # The skill MUST explicitly state the no-facts rule.
    assert "does not state facts" in lc or "does NOT state facts" in content

    # Completion signal — exact phrase per spec.
    assert "you're teaching yourself now" in lc

    # Silent knowledge_graph consultation between questions.
    assert "silently" in lc
    assert "knowledge_graph" in lc


def test_teacher_prompt_contains_meta_behavior_markers(
    roles_dir: Path, personas_dir: Path
) -> None:
    """Asserts the meta-behavior markers design.md test-strategy calls out.

    Spec scenarios for first-turn negotiation and skill-switch transition
    are model-behavior scenarios (untestable without a live LLM), but the
    *prompt content* that drives them is checkable: it MUST contain the
    phrases that the spec says it does.
    """
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("teacher", persona)
    lc = role.prompt.lower()

    # First-turn negotiation (D2).
    assert "offer the user a choice" in lc, (
        "first-turn method-choice marker missing from prompt"
    )

    # Skill-switch transition protocol (D7).
    assert "summarize" in lc and "switch" in lc, (
        "skill-switch summarize-before-switch marker missing"
    )

    # Both method names are presented to the user on first turn.
    assert "feynman" in lc
    assert "socratic" in lc

    # Delegation scope (D5).
    assert "researcher" in lc


def test_teacher_prompt_contains_method_persistence_markers(
    roles_dir: Path, personas_dir: Path
) -> None:
    """Method-Persistence-Across-Turns spec requirement: the prompt
    MUST explicitly state that once a method is selected (by any
    mechanism, including plain-prose naming), it is the active
    method for the rest of the session and MUST NOT be re-offered."""
    persona = PersonaRegistry(personas_dir).load("personal")
    role = RoleRegistry(roles_dir, personas_dir).load("teacher", persona)
    lc = role.prompt.lower()

    # Section header / topic.
    assert "method persistence" in lc, (
        "method-persistence section heading missing"
    )

    # Three core rules the prompt MUST encode for the requirement.
    # 1. Selection by any mechanism (including plain prose) is binding.
    assert "plain prose" in lc, (
        "prompt does not cover plain-prose method selection"
    )
    # 2. Never re-offer after selection.
    assert "not re-offer" in lc or "do not re-offer" in lc or "must not re-offer" in lc, (
        "no-re-offer rule missing from prompt"
    )
    # 3. Continue from conversation history rather than re-asking topic.
    assert "do not re-ask" in lc or "not re-ask" in lc or "without re-asking" in lc, (
        "topic-continuity rule missing from prompt"
    )
