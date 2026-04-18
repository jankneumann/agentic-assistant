"""GuardrailProvider protocol and AllowAllGuardrails stub — Task 1.4."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from assistant.core.capabilities.types import ActionDecision, ActionRequest, RiskLevel


@runtime_checkable
class GuardrailProvider(Protocol):
    def check_action(self, action: ActionRequest) -> ActionDecision: ...
    def check_delegation(
        self, parent_role: str, sub_role: str, task: str
    ) -> ActionDecision: ...
    def declare_risk(self, action: ActionRequest) -> RiskLevel: ...


class AllowAllGuardrails:
    def check_action(self, action: ActionRequest) -> ActionDecision:
        return ActionDecision(allowed=True)

    def check_delegation(
        self, parent_role: str, sub_role: str, task: str
    ) -> ActionDecision:
        return ActionDecision(allowed=True)

    def declare_risk(self, action: ActionRequest) -> RiskLevel:
        return RiskLevel.LOW
