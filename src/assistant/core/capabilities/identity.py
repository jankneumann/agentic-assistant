"""AgentIdentity principal — agent-iam (P25).

The identity principal answers "who is acting?" for every guardrail
decision: which persona (execution boundary), which role (behavioral
pattern), through which delegation chain the authority arrived, and —
when known — which session/thread the action belongs to.

Design notes (docs/architecture-analysis/2026-07-16-protocol-standards.md,
auth row): no converged standard exists for *agent* identity — SPIFFE-
style workload identity is the closest analogue — so ``AgentIdentity``
is a deliberate placeholder shaped for it: a frozen value object whose
fields map onto a SPIFFE-like path (``persona/role`` ≈ trust domain /
workload, ``delegation_chain`` ≈ the attestation path, ``issued_at`` ≈
SVID issuance). Migration to a real workload-identity document is a
mapping, not a rewrite.

Semantics:

- ``delegation_chain`` holds the ROLE NAMES of the ancestors that
  delegated down to this identity, root-first, NOT including the
  current ``role``. A root (user-facing) identity has an empty chain.
- ``chain_depth`` is the number of delegation hops (``len(chain)``).
- ``delegate_to(sub_role)`` derives the child principal for one hop:
  same persona (sub-agents inherit the persona — execution boundary
  never changes on delegation), the sub-role as the new ``role``, the
  parent's role appended to the chain, the session id carried through,
  and a fresh ``issued_at``.

The dataclass is frozen and the chain is a tuple, so an identity can
never be mutated after construction — chain extension always produces
a new principal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AgentIdentity:
    """Immutable principal: who is performing an action.

    Attributes:
        persona: Persona name — the execution boundary the action runs
            inside. Never changes across delegation hops.
        role: The acting role name.
        delegation_chain: Role names of the delegating ancestors,
            root-first, excluding ``role`` itself. ``()`` for a root
            identity.
        session_id: The harness ``thread_id`` / A2A ``contextId`` the
            action belongs to, when known; ``""`` otherwise.
        issued_at: UTC timestamp of principal construction.
    """

    persona: str
    role: str
    delegation_chain: tuple[str, ...] = ()
    session_id: str = ""
    issued_at: datetime = field(default_factory=_utcnow)

    @property
    def chain_depth(self) -> int:
        """Number of delegation hops behind this identity."""
        return len(self.delegation_chain)

    def delegate_to(self, sub_role: str) -> AgentIdentity:
        """Derive the child principal for one delegation hop.

        The persona is inherited (sub-agents switch role, never
        persona), the parent's role is appended to the chain, the
        session id is carried through, and ``issued_at`` is fresh.
        """
        return AgentIdentity(
            persona=self.persona,
            role=sub_role,
            delegation_chain=(*self.delegation_chain, self.role),
            session_id=self.session_id,
        )

    def chain_display(self) -> str:
        """Human-readable chain for logs: ``root -> ... -> role``."""
        return " -> ".join((*self.delegation_chain, self.role))


__all__ = ["AgentIdentity"]
