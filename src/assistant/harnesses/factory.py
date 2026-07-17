"""Harness factory — enforces registration and persona-enablement."""

from __future__ import annotations

from typing import Any

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import HarnessAdapter, HostHarnessAdapter
from assistant.harnesses.host.claude_code import ClaudeCodeHarness
from assistant.harnesses.sdk.deep_agents import DeepAgentsHarness
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness

HARNESS_REGISTRY: dict[str, type[HarnessAdapter]] = {
    "deep_agents": DeepAgentsHarness,
    "ms_agent_framework": MSAgentFrameworkHarness,
    "claude_code": ClaudeCodeHarness,
}


def create_harness(
    persona: PersonaConfig,
    role: RoleConfig,
    harness_name: str,
    **sdk_kwargs: Any,
) -> HarnessAdapter:
    """Build a registered harness after enablement validation.

    ``sdk_kwargs`` are forwarded to SDK harness constructors only —
    the documented capability-injection kwargs (``model_provider``,
    ``memory_policy``, ...). The scheduler (P7) uses this to pin a
    scheduled job's ``consumer`` model binding; host harnesses accept
    no injection kwargs, so passing any for a host harness raises.
    """
    if harness_name not in HARNESS_REGISTRY:
        raise ValueError(
            f"Unknown harness '{harness_name}'. "
            f"Available: {sorted(HARNESS_REGISTRY)}"
        )

    harness_cls = HARNESS_REGISTRY[harness_name]

    if issubclass(harness_cls, HostHarnessAdapter):
        if sdk_kwargs:
            raise ValueError(
                f"Harness '{harness_name}' is a host harness; it accepts "
                f"no SDK injection kwargs (got {sorted(sdk_kwargs)})."
            )
        return harness_cls(persona, role)

    cfg = persona.harnesses.get(harness_name, {}) or {}
    if not cfg.get("enabled", False):
        raise ValueError(
            f"Harness '{harness_name}' is not enabled for persona "
            f"'{persona.name}'."
        )
    return harness_cls(persona, role, **sdk_kwargs)
