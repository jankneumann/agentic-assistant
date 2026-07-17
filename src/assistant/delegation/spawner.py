"""Sub-agent delegation with role-switching + concurrency enforcement.

P25 agent-iam adds delegation-chain attribution: the spawner carries an
:class:`AgentIdentity` for the parent (injected by the caller, or
synthesized from persona + parent role), derives the child principal
for every hop via ``identity.delegate_to(sub_role)``, enforces the
persona's ``guardrails.delegation.max_chain_depth`` ceiling (default
5; ``0`` = unlimited), logs the chain on every decision, and emits a
guardrail audit record through the telemetry provider.
"""

from __future__ import annotations

import logging
from typing import Any

from assistant.core.capabilities.audit import emit_guardrail_audit
from assistant.core.capabilities.guardrails import (
    DEFAULT_MAX_CHAIN_DEPTH,
    AllowAllGuardrails,
    GuardrailProvider,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.types import ActionDecision, ActionRequest
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.harnesses.base import SdkHarnessAdapter
from assistant.telemetry.decorators import traced_delegation

logger = logging.getLogger(__name__)


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
        identity: AgentIdentity | None = None,
    ) -> None:
        self.persona = persona
        self.parent_role = parent_role
        self.harness = harness
        self.tools = tools
        self.extensions = extensions
        self.role_registry = role_registry or RoleRegistry()
        self.guardrails: GuardrailProvider = guardrails or AllowAllGuardrails()
        # P25 agent-iam: the parent principal for chain attribution. A
        # nested spawner receives the (already-extended) identity of
        # its parent hop; a top-level spawner synthesizes the root.
        if identity is None:
            try:
                session_id = str(harness.thread_id or "")
            except (NotImplementedError, AttributeError):
                # Base-class property for harnesses predating the
                # thread_id contract (or test doubles without one) —
                # identity works without a session id.
                session_id = ""
            identity = AgentIdentity(
                persona=persona.name,
                role=parent_role.name,
                session_id=session_id,
            )
        self.identity: AgentIdentity = identity
        self._active: int = 0

    def _audit(self, sub_role_name: str, decision: ActionDecision) -> None:
        """Log the chain + emit the audit record for one decision."""
        child = self.identity.delegate_to(sub_role_name)
        logger.info(
            "delegation %s: chain %s (depth %d) -> %s",
            "allowed" if decision.allowed else "DENIED",
            self.identity.chain_display(),
            child.chain_depth,
            sub_role_name,
        )
        emit_guardrail_audit(
            ActionRequest(
                action_type="delegation",
                resource=sub_role_name,
                persona=self.persona.name,
                role=self.parent_role.name,
                metadata={
                    "child_chain": [*child.delegation_chain, child.role],
                    "child_chain_depth": child.chain_depth,
                },
                identity=self.identity,
            ),
            decision,
        )

    @traced_delegation
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

        # P25 agent-iam: enforce the delegation-chain depth ceiling
        # BEFORE the guardrail check — an over-deep chain is denied
        # regardless of what the policy provider would say.
        child = self.identity.delegate_to(sub_role_name)
        guardrail_config = getattr(self.persona, "guardrails", None)
        max_depth = (
            guardrail_config.delegation.max_chain_depth
            if guardrail_config is not None
            else DEFAULT_MAX_CHAIN_DEPTH
        )
        if max_depth and child.chain_depth > max_depth:
            decision = ActionDecision(
                allowed=False,
                reason=(
                    f"delegation chain depth {child.chain_depth} exceeds "
                    f"max_chain_depth {max_depth} "
                    f"(chain: {child.chain_display()})"
                ),
            )
            self._audit(sub_role_name, decision)
            raise PermissionError(decision.reason)

        decision = self.guardrails.check_delegation(
            self.parent_role.name, sub_role_name, task
        )
        self._audit(sub_role_name, decision)
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
