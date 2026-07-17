"""Harness factory — enforces registration and persona-enablement.

P11 harness-routing adds :func:`select_harness`: deterministic,
config-driven resolution of the ``--harness auto`` sentinel (explicit
request → persona ``harnesses.routing:`` rules → built-in defaults).
No LLM calls — semantic task routing is P12's ``delegation/router.py``,
not this seam.
"""

from __future__ import annotations

import logging
from typing import Any

from assistant.core.harness_routing import (
    AUTO_HARNESS,
    role_prefers_ms_tools,
    rule_matches,
)
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import HarnessAdapter, HostHarnessAdapter
from assistant.harnesses.host.claude_code import ClaudeCodeHarness
from assistant.harnesses.sdk.deep_agents import DeepAgentsHarness
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness

logger = logging.getLogger(__name__)

HARNESS_REGISTRY: dict[str, type[HarnessAdapter]] = {
    "deep_agents": DeepAgentsHarness,
    "ms_agent_framework": MSAgentFrameworkHarness,
    "claude_code": ClaudeCodeHarness,
}

#: Span name for routing decisions (telemetry ``start_span`` escape
#: hatch — same pattern as the P25 ``guardrail.decision`` audit record;
#: the closed trace-op vocabulary is untouched).
HARNESS_ROUTING_SPAN = "harness.routing"


def _is_host_harness(harness_name: str) -> bool:
    cls = HARNESS_REGISTRY.get(harness_name)
    return cls is not None and issubclass(cls, HostHarnessAdapter)


def _is_enabled_sdk(persona: PersonaConfig, harness_name: str) -> bool:
    """True for a registered, persona-enabled, non-host harness."""
    if harness_name not in HARNESS_REGISTRY or _is_host_harness(harness_name):
        return False
    cfg = persona.harnesses.get(harness_name, {}) or {}
    return bool(cfg.get("enabled", False))


def _emit_routing_decision(
    persona: PersonaConfig,
    role: RoleConfig,
    requested: str | None,
    selected: str,
    reason: str,
) -> None:
    """Log + span-emit one routing decision. Never raises.

    Defensive posture mirrors ``core/capabilities/audit.py``: a failing
    telemetry provider logs a WARNING and never changes the selection.
    """
    logger.info(
        "harness routing: persona=%s role=%s requested=%s selected=%s "
        "reason=%s",
        persona.name,
        role.name,
        requested or AUTO_HARNESS,
        selected,
        reason,
    )
    try:
        # Lazy import: keep the factory import-light and preserve the
        # telemetry factory's established patch point.
        from assistant.telemetry import get_observability_provider

        with get_observability_provider().start_span(
            HARNESS_ROUTING_SPAN,
            attributes={
                "persona": persona.name,
                "role": role.name,
                "requested": requested or AUTO_HARNESS,
                "selected": selected,
                "reason": reason,
            },
        ):
            pass
    except Exception as exc:
        logger.warning(
            "harness routing span not emitted (%s); selection is "
            "unaffected",
            type(exc).__name__,
        )


def select_harness(
    persona: PersonaConfig,
    role: RoleConfig,
    *,
    requested: str | None = None,
) -> str:
    """Resolve the harness name for a persona-times-role composition.

    Deterministic precedence (P11 harness-routing; no LLM calls):

    1. **Explicit request** — any ``requested`` other than ``None`` /
       ``"auto"`` is returned verbatim (enablement validation stays in
       :func:`create_harness`).
    2. **Persona ``harnesses.routing:`` rules** — ordered first-match
       on role-name glob and/or role ``preferred_tools`` globs. A
       matching rule whose target is disabled is skipped with a
       WARNING (config drift should not abort an interactive run); a
       matching rule naming an unknown or host harness raises.
    3. **Built-in defaults** — role prefers MS-source tools
       (``ms_graph``/``outlook``/``teams``/``sharepoint``) AND
       ``ms_agent_framework`` enabled → MSAF; else ``deep_agents``
       when enabled; else the remaining enabled SDK harness; else
       ``ValueError``.

    A host harness is NEVER auto-selected: host harnesses export
    configuration for a subscription-seat host rather than execute, so
    auto-selecting one would silently no-op an interactive run. The
    host tier stays explicit-only (``-H claude_code`` + ``assistant
    export``).
    """
    if requested and requested != AUTO_HARNESS:
        _emit_routing_decision(persona, role, requested, requested, "explicit")
        return requested

    # ── Persona routing rules (ordered, first match) ──────────────
    for index, rule in enumerate(persona.harness_routing):
        if not rule_matches(rule, role.name, role.preferred_tools):
            continue
        if rule.harness not in HARNESS_REGISTRY:
            raise ValueError(
                f"harnesses.routing rule[{index}] names unknown harness "
                f"{rule.harness!r}. Available: {sorted(HARNESS_REGISTRY)}."
            )
        if _is_host_harness(rule.harness):
            raise ValueError(
                f"harnesses.routing rule[{index}] names host harness "
                f"{rule.harness!r}; host harnesses cannot be "
                f"auto-selected — the host tier is explicit-only "
                f"(-H {rule.harness} with 'assistant export')."
            )
        if not _is_enabled_sdk(persona, rule.harness):
            logger.warning(
                "harnesses.routing rule[%d] matched role %r but harness "
                "%r is not enabled for persona %r; skipping rule",
                index,
                role.name,
                rule.harness,
                persona.name,
            )
            continue
        reason = f"rule[{index}]"
        _emit_routing_decision(persona, role, requested, rule.harness, reason)
        return rule.harness

    # ── Built-in defaults ──────────────────────────────────────────
    ms_signal = role_prefers_ms_tools(role.preferred_tools)
    if ms_signal and _is_enabled_sdk(persona, "ms_agent_framework"):
        _emit_routing_decision(
            persona, role, requested, "ms_agent_framework", "builtin:ms-tools"
        )
        return "ms_agent_framework"
    if _is_enabled_sdk(persona, "deep_agents"):
        reason = (
            "builtin:ms-tools-fallback" if ms_signal else "builtin:default"
        )
        _emit_routing_decision(persona, role, requested, "deep_agents", reason)
        return "deep_agents"
    if _is_enabled_sdk(persona, "ms_agent_framework"):
        _emit_routing_decision(
            persona,
            role,
            requested,
            "ms_agent_framework",
            "builtin:only-enabled-sdk",
        )
        return "ms_agent_framework"

    raise ValueError(
        f"No enabled SDK harness for persona '{persona.name}' — "
        f"--harness auto cannot select one (host harnesses are "
        f"explicit-only). Enable deep_agents or ms_agent_framework in "
        f"the persona's harnesses: section, or pass -H explicitly."
    )


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

    ``harness_name`` must be concrete — callers resolve the ``auto``
    sentinel through :func:`select_harness` first.
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
