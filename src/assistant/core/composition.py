"""Three-layer system prompt composition: base → persona → role."""

from __future__ import annotations

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig

BASE_SYSTEM_PROMPT = """You are Jan's personal AI assistant. You operate within \
a specific persona (execution boundary) and role (behavioral pattern).

You have access to specialized backend systems via HTTP tools and
persona-specific integrations. Route tasks appropriately, maintain
cross-session memory, and respect persona boundaries.

## Core Rules
- Be direct and substantive; avoid filler
- Respect persona boundaries — never access tools or data outside your
  active persona's scope
- When delegating to sub-agents, they inherit your persona but can switch roles
- Update memory with learned preferences and patterns
- For complex tasks, use planning tools to decompose before executing
"""

_SEPARATOR = "\n\n---\n\n"


def compose_system_prompt(persona: PersonaConfig, role: RoleConfig) -> str:
    layers = [BASE_SYSTEM_PROMPT]
    if persona.prompt_augmentation and persona.prompt_augmentation.strip():
        layers.append(persona.prompt_augmentation)
    if role.prompt and role.prompt.strip():
        layers.append(role.prompt)
    layers.append(_build_active_context(persona, role))
    return _SEPARATOR.join(layers)


def _build_active_context(persona: PersonaConfig, role: RoleConfig) -> str:
    sub_roles = role.delegation.get("allowed_sub_roles") or []
    sub_roles_str = ", ".join(sub_roles) if sub_roles else "none"

    parts = [
        "## Active Configuration",
        f"- **Persona**: {persona.display_name}",
        f"- **Role**: {role.display_name}",
        f"- **Sub-roles**: {sub_roles_str}",
    ]
    if role.planning.get("always_plan"):
        parts.append("- **Planning**: Always plan before executing")
    if role.preferred_tools:
        parts.append(
            f"- **Preferred tools**: {', '.join(role.preferred_tools)}"
        )
    return "\n".join(parts)
