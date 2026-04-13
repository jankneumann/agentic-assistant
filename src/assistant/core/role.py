"""Role registry — shared roles with persona-specific overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from assistant.core.persona import PersonaConfig


@dataclass
class RoleConfig:
    name: str
    display_name: str
    description: str
    prompt: str
    preferred_tools: list[str] = field(default_factory=list)
    delegation: dict[str, Any] = field(default_factory=dict)
    planning: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    skills_dir: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class RoleRegistry:
    """Discover public roles and merge persona-specific overrides.

    Merge semantics (shallow, per-field):
    - ``prompt_append``: appended after base prompt with a blank-line separator.
    - ``additional_preferred_tools``: list-extend of base ``preferred_tools``.
    - ``delegation_overrides``: dict update over base ``delegation``.
    - ``context_overrides``: dict update over base ``context``.
    """

    def __init__(
        self,
        roles_dir: Path | str | None = None,
        personas_dir: Path | str | None = None,
    ) -> None:
        # Honor ASSISTANT_PERSONAS_DIR for test-privacy-boundary (see
        # PersonaRegistry.__init__ and docs/gotchas.md G6). The env var
        # redirects both the persona base config and its role overrides
        # so tests never read from `personas/<name>/` at runtime.
        if personas_dir is None:
            env = os.environ.get("ASSISTANT_PERSONAS_DIR")
            personas_dir = Path(env) if env else Path("personas")
        if roles_dir is None:
            roles_dir = Path("roles")
        self.roles_dir = Path(roles_dir)
        self.personas_dir = Path(personas_dir)

    def discover(self) -> list[str]:
        if not self.roles_dir.exists():
            return []
        return sorted(
            p.name
            for p in self.roles_dir.iterdir()
            if p.is_dir()
            and (p / "role.yaml").exists()
            and not p.name.startswith("_")
        )

    def available_for_persona(self, persona: PersonaConfig) -> list[str]:
        return [r for r in self.discover() if r not in persona.disabled_roles]

    def load(self, role_name: str, persona: PersonaConfig) -> RoleConfig:
        base_path = self.roles_dir / role_name
        if not (base_path / "role.yaml").exists():
            raise ValueError(
                f"Role '{role_name}' not found. "
                f"Available: {self.discover()}"
            )

        with open(base_path / "role.yaml") as f:
            base = yaml.safe_load(f) or {}

        base_prompt = ""
        prompt_path = base_path / "prompt.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()

        override_path = (
            self.personas_dir / persona.name / "roles" / f"{role_name}.yaml"
        )
        override: dict[str, Any] = {}
        if override_path.exists():
            with open(override_path) as f:
                override = yaml.safe_load(f) or {}

        merged_prompt = base_prompt
        if override.get("prompt_append"):
            merged_prompt = f"{merged_prompt}\n\n{override['prompt_append']}"

        preferred_tools = list(base.get("preferred_tools", []) or [])
        if override.get("additional_preferred_tools"):
            preferred_tools.extend(override["additional_preferred_tools"])

        delegation = dict(base.get("delegation", {}) or {})
        if override.get("delegation_overrides"):
            delegation.update(override["delegation_overrides"])

        context = dict(base.get("context", {}) or {})
        if override.get("context_overrides"):
            context.update(override["context_overrides"])

        return RoleConfig(
            name=base["name"],
            display_name=base.get("display_name", base["name"]),
            description=base.get("description", ""),
            prompt=merged_prompt,
            preferred_tools=preferred_tools,
            delegation=delegation,
            planning=base.get("planning", {}) or {},
            context=context,
            skills_dir=base.get("skills_dir", ""),
            raw={**base, **override},
        )
