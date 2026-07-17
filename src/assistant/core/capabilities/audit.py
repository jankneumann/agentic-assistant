"""Guardrail decision audit trail — agent-iam (P25).

Every guardrail decision made for an :class:`ActionRequest` carrying an
:class:`AgentIdentity` is emitted as a structured audit record through
the EXISTING telemetry provider (observability spec: ``start_span`` is
the sanctioned escape hatch for non-first-class operations, so the
closed trace-op vocabulary is untouched). There is no separate audit
store — telemetry is the sink; a dedicated durable audit log is
deferred alongside the approval interrupt/resume flow.

Record shape (span ``guardrail.decision`` attributes):

- ``action_type`` / ``resource`` — what was requested
- ``persona`` / ``role`` — the acting principal
- ``delegation_chain`` (list, root-first) + ``chain_depth`` — how the
  authority arrived (P12 delegation chains become attributable here)
- ``session_id`` / ``issued_at`` — correlation with the session
- ``decision`` — ``allow`` | ``deny`` | ``require_confirmation``
- ``reason`` — the guardrail's stated reason (may be empty on allow)

Requests without an identity are NOT audited — pre-P25 call sites keep
their exact behavior; the identity-attaching sites (delegation spawner,
model-call hook, harness spawn paths) opt in by construction. Emission
is defensive: a failing provider logs a WARNING and never breaks the
action flow (same posture as memory capture).
"""

from __future__ import annotations

import logging
from typing import Any

from assistant.core.capabilities.types import ActionDecision, ActionRequest

logger = logging.getLogger(__name__)

#: Span name for guardrail audit records (telemetry escape hatch).
GUARDRAIL_AUDIT_SPAN = "guardrail.decision"


def decision_outcome(decision: ActionDecision) -> str:
    """Map an ActionDecision onto the closed audit outcome vocabulary."""
    if not decision.allowed:
        return "deny"
    if decision.require_confirmation:
        return "require_confirmation"
    return "allow"


def emit_guardrail_audit(
    action: ActionRequest, decision: ActionDecision
) -> None:
    """Emit one audit record for a guardrail decision, if attributable.

    No-op when ``action.identity`` is ``None`` — only identity-carrying
    requests produce audit records. Never raises: telemetry problems
    must not change guardrail enforcement outcomes.
    """
    identity = action.identity
    if identity is None:
        return
    attributes: dict[str, Any] = {
        "action_type": action.action_type,
        "resource": action.resource,
        "persona": identity.persona,
        "role": identity.role,
        "delegation_chain": list(identity.delegation_chain),
        "chain_depth": identity.chain_depth,
        "session_id": identity.session_id,
        "issued_at": identity.issued_at.isoformat(),
        "decision": decision_outcome(decision),
        "reason": decision.reason,
    }
    try:
        # Lazy import: keep the capabilities package import-light and
        # preserve the telemetry factory's established patch point.
        from assistant.telemetry import get_observability_provider

        with get_observability_provider().start_span(
            GUARDRAIL_AUDIT_SPAN, attributes=attributes
        ):
            pass
    except Exception as exc:
        logger.warning(
            "guardrail audit record not emitted (%s); decision "
            "enforcement is unaffected",
            type(exc).__name__,
        )


__all__ = ["GUARDRAIL_AUDIT_SPAN", "decision_outcome", "emit_guardrail_audit"]
