"""Claude Code host harness — exports context for Claude Code integration."""

from __future__ import annotations

from typing import Any

from assistant.core.composition import compose_system_prompt
from assistant.harnesses.base import HostHarnessAdapter


class ClaudeCodeHarness(HostHarnessAdapter):
    def name(self) -> str:
        return "claude_code"

    def export_context(self, capabilities: Any) -> dict[str, str]:
        system_prompt = compose_system_prompt(self.persona, self.role)

        memory_context = ""
        if capabilities and hasattr(capabilities, "memory"):
            memory_context = capabilities.memory.export_memory_context(
                self.persona
            )

        return {
            "system_prompt": system_prompt,
            "memory_context": memory_context,
        }

    def export_guardrail_declarations(
        self, capabilities: Any
    ) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        delegation_cfg = self.role.delegation or {}
        allowed = delegation_cfg.get("allowed_sub_roles", [])
        if allowed:
            declarations.append(
                {
                    "type": "delegation",
                    "allowed_sub_roles": allowed,
                    "max_concurrent": delegation_cfg.get("max_concurrent", 3),
                }
            )
        return declarations

    def export_tool_manifest(
        self, capabilities: Any
    ) -> dict[str, Any]:
        if capabilities and hasattr(capabilities, "tools"):
            return capabilities.tools.export_tool_manifest(
                self.persona, self.role
            )
        return {}
