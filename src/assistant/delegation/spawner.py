"""Sub-agent delegation with role-switching + concurrency enforcement."""

from __future__ import annotations

from typing import Any

from assistant.core.capabilities.guardrails import AllowAllGuardrails, GuardrailProvider
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.harnesses.base import SdkHarnessAdapter


class DelegationSpawner:
    def __init__(
        self,
        persona: PersonaConfig,
        parent_role: RoleConfig,
        harness: SdkHarnessAdapter,
        tools: list[Any],
        extensions: list[Any],
        role_registry: RoleRegistry | None = None,
        guardrails: GuardrailProvider | None = None,
    ) -> None:
        self.persona = persona
        self.parent_role = parent_role
        self.harness = harness
        self.tools = tools
        self.extensions = extensions
        self.role_registry = role_registry or RoleRegistry()
        self.guardrails: GuardrailProvider = guardrails or AllowAllGuardrails()
        self._active: int = 0

    async def delegate(self, sub_role_name: str, task: str) -> str:
        allowed = self.parent_role.delegation.get("allowed_sub_roles", []) or []
        if sub_role_name not in allowed:
            raise ValueError(
                f"Role '{self.parent_role.name}' cannot delegate to "
                f"'{sub_role_name}'. Allowed: {allowed}"
            )

        available = self.role_registry.available_for_persona(self.persona)
        if sub_role_name not in available:
            raise ValueError(
                f"Role '{sub_role_name}' is not available for persona "
                f"'{self.persona.name}' (check disabled_roles)."
            )

        decision = self.guardrails.check_delegation(
            self.parent_role.name, sub_role_name, task
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        max_concurrent = self.parent_role.delegation.get(
            "max_concurrent", 3
        )
        if self._active >= max_concurrent:
            raise RuntimeError(
                f"Max concurrent delegations ({max_concurrent}) reached for "
                f"role '{self.parent_role.name}'."
            )

        sub_role = self.role_registry.load(sub_role_name, self.persona)
        self._active += 1
        try:
            return await self.harness.spawn_sub_agent(
                sub_role, task, self.tools, self.extensions
            )
        finally:
            self._active -= 1
