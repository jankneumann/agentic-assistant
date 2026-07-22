"""Approval interrupt/resume — guardrail-provider contract (P30).

Implements the P24 guardrail-provider ``ApprovalRequest`` contract on
top of the durable-session tier: when a ``GuardrailProvider`` returns
``require_confirmation=True`` AND the persona has durable sessions
(``sessions: {durable: true}`` + a ``database_url``), the affected
operation SUSPENDS instead of denying — an :class:`ApprovalRequest`
record (MCP-elicitation-shaped) is persisted to the approvals table
and a typed :class:`PendingApprovalError` carries the request id up
to the serving layer (A2A maps it to a REAL non-terminal
``input-required`` task state, AG-UI surfaces the class name on its
``RunErrorEvent``, the CLI prints resume instructions).

Resume is retry-shaped (v1): ``assistant approvals approve|deny <id>``
records the human decision (idempotent — the first decision wins);
the caller then RETRIES the suspended operation, and
:func:`consume_or_suspend` consults resolved approvals BEFORE
re-checking — an approve decision lets the action proceed exactly
once (the approval is consumed), a deny decision surfaces as
:class:`ApprovalDeniedError` (also consumed once). Where durability
is off (no store), every ``require_confirmation`` site preserves its
pre-P30 deny behavior — approvals need the persona DB.

The :class:`ApprovalStore` protocol is SYNC (mirror of the P13
``BudgetLedger`` posture): the guardrail confirmation hooks run
inside synchronous functions (``check_model_call``, the clean-room
and learning gate checks), so the store runs short queries over the
sync engine tier. :class:`InMemoryApprovalStore` backs the tests and
any process-local experimentation; the Postgres implementation lives
in ``assistant.core.durable``.
"""

from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from assistant.core.capabilities.types import (
    ActionDecision,
    ActionRequest,
    RiskLevel,
)

#: Closed status vocabulary for approval lifecycle records.
APPROVAL_STATUSES = ("pending", "approved", "denied", "consumed", "expired")

#: Default decision payload schema (MCP-elicitation-shaped): an
#: approve/deny boolean plus an optional free-text justification.
DEFAULT_APPROVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approve": {
            "type": "boolean",
            "description": "true approves the blocked action; false denies it.",
        },
        "justification": {
            "type": "string",
            "description": "Optional free-text justification for the decision.",
        },
    },
    "required": ["approve"],
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _default_schema() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_APPROVAL_SCHEMA)


@dataclass
class ApprovalRequest:
    """Channel-agnostic 'a suspended run asks a human for a decision'.

    Mirrors the MCP elicitation shape (guardrail-provider spec): the
    (``message``, ``requested_schema``) pair is directly representable
    as an MCP elicitation request without translation. Lifecycle
    fields (``status`` onward) ride the same record so the store needs
    exactly one row shape; a freshly created request is ``pending``.
    """

    approval_id: str
    message: str
    action: ActionRequest
    risk: RiskLevel
    thread_id: str = ""
    requested_schema: dict[str, Any] = field(default_factory=_default_schema)
    created_at: datetime = field(default_factory=_utcnow)
    expires_at: datetime | None = None
    # -- lifecycle -----------------------------------------------------
    status: str = "pending"
    decided_by: str = ""
    justification: str = ""
    decided_at: datetime | None = None
    consumed_at: datetime | None = None


class ApprovalError(Exception):
    """Base class for approval-flow errors."""


class PendingApprovalError(ApprovalError):
    """A guardrail suspended this operation awaiting a human decision.

    Typed suspension signal (P30): raised INSTEAD of the P13 deny when
    a ``require_confirmation`` decision lands on a persona with a
    durable approval store. Carries the approval id so every serving
    layer can point the operator at the resume commands.
    """

    def __init__(self, request: ApprovalRequest) -> None:
        self.approval_id = request.approval_id
        self.action_type = request.action.action_type
        self.resource = request.action.resource
        self.persona = request.action.persona
        super().__init__(
            f"{self.action_type} on {self.resource!r} is suspended awaiting "
            f"approval '{self.approval_id}'. Decide with `assistant "
            f"approvals approve {self.approval_id} -p {self.persona}` (or "
            f"`deny`), then retry the operation."
        )


class ApprovalDeniedError(ApprovalError, PermissionError):
    """A human denied the pending approval; the retried action stops."""

    def __init__(self, request: ApprovalRequest) -> None:
        self.approval_id = request.approval_id
        detail = f": {request.justification}" if request.justification else ""
        super().__init__(
            f"{request.action.action_type} on {request.action.resource!r} "
            f"was denied by {request.decided_by or 'a human decision'} "
            f"(approval '{request.approval_id}'){detail}"
        )


class ApprovalAlreadyDecidedError(ApprovalError):
    """A second decision arrived for an already-decided approval."""


class UnknownApprovalError(ApprovalError):
    """The approval id does not exist in the store."""


@runtime_checkable
class ApprovalStore(Protocol):
    """Sync persistence seam for approval request/decision records."""

    def create(self, request: ApprovalRequest) -> None: ...

    def get(self, approval_id: str) -> ApprovalRequest | None: ...

    def list_requests(
        self, persona: str, *, status: str | None = None
    ) -> list[ApprovalRequest]: ...

    def find_pending(
        self, persona: str, action_type: str, resource: str
    ) -> ApprovalRequest | None: ...

    def find_resolved(
        self, persona: str, action_type: str, resource: str
    ) -> ApprovalRequest | None: ...

    def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        decided_by: str = "",
        justification: str = "",
    ) -> ApprovalRequest: ...

    def consume(self, approval_id: str) -> bool: ...


class InMemoryApprovalStore:
    """Process-lifetime ApprovalStore (tests + non-persisted fallback).

    Implements the exact same semantics contract as the Postgres store
    (``assistant.core.durable.PostgresApprovalStore``): pending rows
    expire lazily on read, ``decide`` is first-decision-wins, and
    ``consume`` flips an approved/denied row to ``consumed`` exactly
    once.
    """

    def __init__(self, *, now: Any | None = None) -> None:
        self._records: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._now = now or _utcnow

    def _expire_lapsed(self) -> None:
        now = self._now()
        for record in self._records.values():
            if (
                record.status == "pending"
                and record.expires_at is not None
                and record.expires_at <= now
            ):
                record.status = "expired"

    def create(self, request: ApprovalRequest) -> None:
        with self._lock:
            if request.approval_id in self._records:
                raise ApprovalError(
                    f"duplicate approval_id '{request.approval_id}'"
                )
            self._records[request.approval_id] = request

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._lock:
            self._expire_lapsed()
            record = self._records.get(approval_id)
            return copy.deepcopy(record) if record is not None else None

    def list_requests(
        self, persona: str, *, status: str | None = None
    ) -> list[ApprovalRequest]:
        with self._lock:
            self._expire_lapsed()
            records = [
                copy.deepcopy(r)
                for r in self._records.values()
                if r.action.persona == persona
                and (status is None or r.status == status)
            ]
            return sorted(records, key=lambda r: r.created_at)

    def _find(
        self, persona: str, action_type: str, resource: str, statuses: tuple[str, ...]
    ) -> ApprovalRequest | None:
        for record in sorted(
            self._records.values(), key=lambda r: r.created_at
        ):
            if (
                record.action.persona == persona
                and record.action.action_type == action_type
                and record.action.resource == resource
                and record.status in statuses
            ):
                return copy.deepcopy(record)
        return None

    def find_pending(
        self, persona: str, action_type: str, resource: str
    ) -> ApprovalRequest | None:
        with self._lock:
            self._expire_lapsed()
            return self._find(persona, action_type, resource, ("pending",))

    def find_resolved(
        self, persona: str, action_type: str, resource: str
    ) -> ApprovalRequest | None:
        with self._lock:
            self._expire_lapsed()
            return self._find(
                persona, action_type, resource, ("approved", "denied")
            )

    def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        decided_by: str = "",
        justification: str = "",
    ) -> ApprovalRequest:
        with self._lock:
            self._expire_lapsed()
            record = self._records.get(approval_id)
            if record is None:
                raise UnknownApprovalError(
                    f"unknown approval '{approval_id}'"
                )
            if record.status != "pending":
                raise ApprovalAlreadyDecidedError(
                    f"approval '{approval_id}' is already {record.status}; "
                    f"duplicate decisions are rejected, not replayed."
                )
            record.status = "approved" if approved else "denied"
            record.decided_by = decided_by
            record.justification = justification
            record.decided_at = self._now()
            return copy.deepcopy(record)

    def consume(self, approval_id: str) -> bool:
        with self._lock:
            record = self._records.get(approval_id)
            if record is None or record.status not in ("approved", "denied"):
                return False
            record.status = "consumed"
            record.consumed_at = self._now()
            return True


def build_approval_request(
    action: ActionRequest,
    decision: ActionDecision,
    *,
    risk: RiskLevel,
    thread_id: str = "",
    expiry_seconds: float = 0.0,
    now: datetime | None = None,
) -> ApprovalRequest:
    """Construct the elicitation-shaped record for a blocked action."""
    created_at = now or _utcnow()
    expires_at = None
    if expiry_seconds > 0:
        from datetime import timedelta

        expires_at = created_at + timedelta(seconds=expiry_seconds)
    reason = decision.reason or "a guardrail policy requires confirmation"
    return ApprovalRequest(
        approval_id=str(uuid.uuid4()),
        message=(
            f"Approval requested: {action.action_type} on "
            f"{action.resource!r} for persona {action.persona!r} "
            f"(role {action.role!r}) — {reason}"
        ),
        action=action,
        risk=risk,
        thread_id=thread_id,
        created_at=created_at,
        expires_at=expires_at,
    )


def consume_or_suspend(
    store: ApprovalStore,
    action: ActionRequest,
    decision: ActionDecision,
    *,
    risk: RiskLevel,
    thread_id: str = "",
    expiry_seconds: float = 0.0,
) -> ApprovalRequest | None:
    """Resolve a ``require_confirmation`` decision against the store.

    Consult-resolved-then-recheck semantics (P30):

    1. A resolved *approved* record matching (persona, action_type,
       resource) is CONSUMED (exactly once) and the caller proceeds —
       the return value is the consumed record.
    2. A resolved *denied* record is consumed and surfaces as
       :class:`ApprovalDeniedError` — the denial is visible to the
       agent/operator, then cleared so a later attempt re-suspends.
    3. An existing *pending* record re-raises
       :class:`PendingApprovalError` with the SAME approval id — no
       duplicate requests for repeated retries.
    4. Otherwise a fresh :class:`ApprovalRequest` is created
       (persisted ``pending``) and :class:`PendingApprovalError` is
       raised — the suspension signal the serving layers surface.
    """
    persona = action.persona
    resolved = store.find_resolved(persona, action.action_type, action.resource)
    if resolved is not None:
        store.consume(resolved.approval_id)
        if resolved.status == "approved":
            return resolved
        raise ApprovalDeniedError(resolved)
    pending = store.find_pending(persona, action.action_type, action.resource)
    if pending is not None:
        raise PendingApprovalError(pending)
    request = build_approval_request(
        action,
        decision,
        risk=risk,
        thread_id=thread_id,
        expiry_seconds=expiry_seconds,
    )
    store.create(request)
    raise PendingApprovalError(request)


__all__ = [
    "APPROVAL_STATUSES",
    "DEFAULT_APPROVAL_SCHEMA",
    "ApprovalAlreadyDecidedError",
    "ApprovalDeniedError",
    "ApprovalError",
    "ApprovalRequest",
    "ApprovalStore",
    "InMemoryApprovalStore",
    "PendingApprovalError",
    "UnknownApprovalError",
    "build_approval_request",
    "consume_or_suspend",
]
