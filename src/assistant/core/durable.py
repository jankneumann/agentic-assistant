"""Durable session tier — persona config, schema, stores (P30).

``durable-sessions`` consolidates the cross-phase deferrals that all
needed the persona DB:

- **``sessions:`` persona section** (:func:`parse_sessions_config`):
  ``durable: true`` opts the persona into Postgres-backed session
  persistence. No section (or ``durable: false``) keeps every
  in-memory default — the clean-room "no config, no feature" posture.
- **Session metadata store**: the ``sessions`` table
  (thread_id / persona / role / harness / created_at / last_used /
  expires_at / status) lets serving surfaces re-bind a known
  ``thread_id`` to a fresh harness after in-process expiry or a
  restart (the LangGraph checkpointer restores the conversation
  state; this table only answers "is this thread known, whose is it,
  and is it still valid?").
- **Approvals store**: the ``approvals`` table persists the
  guardrail-provider :class:`~assistant.core.capabilities.approvals.
  ApprovalRequest` records so approval round-trips survive restarts.
- **Spend ledger**: :class:`PostgresBudgetLedger` implements the P13
  ``BudgetLedger`` protocol on the ``guardrail_spend`` table
  (``guardrails.budgets.model_call.persist: db``).
- **Audit log**: the ``audit_log`` table receives guardrail decision
  records (including approval decisions) when durable sessions are
  on; telemetry spans continue regardless (the P25 escape-hatch spans
  are unchanged — this adds the durable sink they deferred).

Schema ownership: the SQLAlchemy Core tables below are the single
in-code description of the durable tier and what the sync stores
query through; **alembic migration 002 is the authoritative Postgres
DDL** (JSONB, timestamptz) and must be applied via ``assistant db
upgrade``. The LangGraph checkpointer manages its OWN tables via its
``setup()`` method (``harnesses/sdk/checkpointer.py``) — checkpointer
schema and alembic migrations are deliberately separate concerns (the
checkpointer schema belongs to the langgraph-checkpoint-postgres
package and versions with it).

Stores are SYNC (SQLAlchemy Core over ``core.db.create_sync_engine``)
because their consumers are sync call sites — the ``BudgetLedger``
protocol, ``check_model_call``, and the clean-room/learning gate
checks. Tests exercise the same store code against sqlite engines
(``metadata.create_all``) so the public suite stays server-free.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine

from assistant.core.capabilities.approvals import (
    ApprovalAlreadyDecidedError,
    ApprovalError,
    ApprovalRequest,
    ApprovalStore,
    UnknownApprovalError,
    _default_schema,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.types import ActionRequest, RiskLevel

logger = logging.getLogger(__name__)


# ── Persona ``sessions:`` section ────────────────────────────────────


class SessionsConfigError(ValueError):
    """A persona ``sessions:`` section failed validation at load time."""


@dataclass(frozen=True)
class SessionsConfig:
    """Parsed persona ``sessions:`` section.

    Falsy (the default) when the persona declares no durable sessions —
    every consumer then keeps its in-memory behavior.

    - ``durable``: opt-in flag; requires a persona ``database:`` url at
      runtime (validated where the stores/checkpointer are built, not
      at parse time — the url resolves through the credential seam).
    - ``session_ttl_seconds``: durable-session validity window measured
      from ``last_used`` (``0`` = never expires). Distinct from the
      serving surfaces' in-process idle TTL, which only releases
      process resources — a durably known thread_id can be re-bound
      until THIS window lapses.
    - ``approval_ttl_seconds``: pending-approval validity window
      (``0`` = never expires); a lapsed pending approval expires and a
      retry files a fresh request.
    """

    durable: bool = False
    session_ttl_seconds: float = 0.0
    approval_ttl_seconds: float = 0.0

    def __bool__(self) -> bool:
        return self.durable


def parse_sessions_config(raw: Any) -> SessionsConfig:
    """Parse and validate a persona ``sessions:`` section.

    Actionable-error posture (same as ``guardrails:`` / ``learning:``):
    unknown keys and mis-typed values fail with
    :class:`SessionsConfigError` naming the offender.
    """
    if not raw:
        return SessionsConfig()
    if not isinstance(raw, dict):
        raise SessionsConfigError(
            f"sessions: expected a mapping, got {type(raw).__name__}."
        )
    unknown = sorted(
        set(raw) - {"durable", "session_ttl_seconds", "approval_ttl_seconds"}
    )
    if unknown:
        raise SessionsConfigError(
            f"sessions: unknown keys {unknown}. Expected 'durable:', "
            f"'session_ttl_seconds:', and/or 'approval_ttl_seconds:'."
        )
    durable = raw.get("durable", False)
    if not isinstance(durable, bool):
        raise SessionsConfigError(
            f"sessions: durable must be a boolean, got "
            f"{type(durable).__name__}."
        )

    def _ttl(key: str) -> float:
        value = raw.get(key, 0.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SessionsConfigError(
                f"sessions: {key} must be a number, got "
                f"{type(value).__name__}."
            )
        if value < 0:
            raise SessionsConfigError(f"sessions: {key} must be >= 0.")
        return float(value)

    return SessionsConfig(
        durable=durable,
        session_ttl_seconds=_ttl("session_ttl_seconds"),
        approval_ttl_seconds=_ttl("approval_ttl_seconds"),
    )


# ── Schema (mirrored by alembic migration 002) ───────────────────────

metadata = sa.MetaData()

sessions_table = sa.Table(
    "sessions",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("persona", sa.String(64), nullable=False, index=True),
    sa.Column("role", sa.String(64), nullable=False),
    sa.Column("harness", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_used", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("status", sa.String(16), nullable=False, default="active"),
)

approvals_table = sa.Table(
    "approvals",
    metadata,
    sa.Column("approval_id", sa.String(64), primary_key=True),
    sa.Column("persona", sa.String(64), nullable=False, index=True),
    sa.Column("action_type", sa.String(64), nullable=False),
    sa.Column("resource", sa.String(512), nullable=False),
    sa.Column("role", sa.String(64), nullable=False, default=""),
    sa.Column("message", sa.Text(), nullable=False),
    sa.Column("requested_schema", sa.JSON(), nullable=False),
    sa.Column("action_metadata", sa.JSON(), nullable=False, default=dict),
    sa.Column("identity", sa.JSON(), nullable=True),
    sa.Column("risk", sa.Integer(), nullable=False),
    sa.Column("thread_id", sa.String(64), nullable=False, default=""),
    sa.Column("status", sa.String(16), nullable=False, default="pending"),
    sa.Column("decided_by", sa.String(128), nullable=False, default=""),
    sa.Column("justification", sa.Text(), nullable=False, default=""),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
)

guardrail_spend_table = sa.Table(
    "guardrail_spend",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("persona", sa.String(64), nullable=False, index=True),
    sa.Column("cost_usd", sa.Float(), nullable=False),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
)

audit_log_table = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("persona", sa.String(64), nullable=False, index=True),
    sa.Column("event", sa.String(64), nullable=False),
    sa.Column("action_type", sa.String(64), nullable=False, default=""),
    sa.Column("resource", sa.String(512), nullable=False, default=""),
    sa.Column("role", sa.String(64), nullable=False, default=""),
    sa.Column("decision", sa.String(32), nullable=False, default=""),
    sa.Column("reason", sa.Text(), nullable=False, default=""),
    sa.Column("attributes", sa.JSON(), nullable=False, default=dict),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize DB round-trips: sqlite drops tzinfo, Postgres keeps it."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ── Session metadata store ───────────────────────────────────────────


@dataclass
class SessionRecord:
    """One durable-session metadata row (NOT the conversation state —
    that lives in the LangGraph checkpointer keyed by the same
    ``thread_id``)."""

    thread_id: str
    persona: str
    role: str
    harness: str
    created_at: datetime = field(default_factory=_utcnow)
    last_used: datetime = field(default_factory=_utcnow)
    expires_at: datetime | None = None
    status: str = "active"


class PostgresSessionStore:
    """Session metadata persistence on the persona DB (sync engine)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(self, record: SessionRecord) -> None:
        # Delete-then-insert keeps the upsert portable across the
        # Postgres production dialect and the sqlite test engines.
        with self._engine.begin() as conn:
            conn.execute(
                sessions_table.delete().where(
                    sessions_table.c.thread_id == record.thread_id
                )
            )
            conn.execute(
                sessions_table.insert().values(
                    thread_id=record.thread_id,
                    persona=record.persona,
                    role=record.role,
                    harness=record.harness,
                    created_at=record.created_at,
                    last_used=record.last_used,
                    expires_at=record.expires_at,
                    status=record.status,
                )
            )

    def get(self, thread_id: str) -> SessionRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(sessions_table).where(
                    sessions_table.c.thread_id == thread_id
                )
            ).mappings().first()
        if row is None:
            return None
        return SessionRecord(
            thread_id=row["thread_id"],
            persona=row["persona"],
            role=row["role"],
            harness=row["harness"],
            created_at=_as_utc(row["created_at"]) or _utcnow(),
            last_used=_as_utc(row["last_used"]) or _utcnow(),
            expires_at=_as_utc(row["expires_at"]),
            status=row["status"],
        )

    def touch(
        self, thread_id: str, *, ttl_seconds: float = 0.0
    ) -> None:
        """Refresh ``last_used`` (and slide ``expires_at`` when a TTL
        window is configured)."""
        now = _utcnow()
        values: dict[str, Any] = {"last_used": now}
        if ttl_seconds > 0:
            from datetime import timedelta

            values["expires_at"] = now + timedelta(seconds=ttl_seconds)
        with self._engine.begin() as conn:
            conn.execute(
                sessions_table.update()
                .where(sessions_table.c.thread_id == thread_id)
                .values(**values)
            )

    def mark_expired(self, thread_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sessions_table.update()
                .where(sessions_table.c.thread_id == thread_id)
                .values(status="expired")
            )


class InMemorySessionStore:
    """Dict-backed SessionStore twin (tests + fakes)."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    def record(self, record: SessionRecord) -> None:
        self._records[record.thread_id] = record

    def get(self, thread_id: str) -> SessionRecord | None:
        return self._records.get(thread_id)

    def touch(self, thread_id: str, *, ttl_seconds: float = 0.0) -> None:
        record = self._records.get(thread_id)
        if record is None:
            return
        record.last_used = _utcnow()
        if ttl_seconds > 0:
            from datetime import timedelta

            record.expires_at = record.last_used + timedelta(
                seconds=ttl_seconds
            )

    def mark_expired(self, thread_id: str) -> None:
        record = self._records.get(thread_id)
        if record is not None:
            record.status = "expired"


# ── Approvals store (Postgres implementation) ────────────────────────


def _identity_payload(identity: AgentIdentity | None) -> dict[str, Any] | None:
    if identity is None:
        return None
    return {
        "persona": identity.persona,
        "role": identity.role,
        "delegation_chain": list(identity.delegation_chain),
        "session_id": identity.session_id,
        "issued_at": identity.issued_at.isoformat(),
    }


def _identity_from_payload(payload: Any) -> AgentIdentity | None:
    if not isinstance(payload, dict):
        return None
    try:
        return AgentIdentity(
            persona=str(payload.get("persona", "")),
            role=str(payload.get("role", "")),
            delegation_chain=tuple(payload.get("delegation_chain", ()) or ()),
            session_id=str(payload.get("session_id", "")),
            issued_at=datetime.fromisoformat(payload["issued_at"])
            if payload.get("issued_at")
            else _utcnow(),
        )
    except (TypeError, ValueError):
        return None


class PostgresApprovalStore:
    """ApprovalStore over the persona DB (sync engine).

    Same semantics contract as
    :class:`~assistant.core.capabilities.approvals.InMemoryApprovalStore`:
    lazy pending-expiry on read, first-decision-wins ``decide``,
    consume-exactly-once.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    def _expire_lapsed(self, conn: sa.Connection) -> None:
        conn.execute(
            approvals_table.update()
            .where(
                approvals_table.c.status == "pending",
                approvals_table.c.expires_at.is_not(None),
                approvals_table.c.expires_at <= _utcnow(),
            )
            .values(status="expired")
        )

    @staticmethod
    def _row_to_request(row: Any) -> ApprovalRequest:
        action = ActionRequest(
            action_type=row["action_type"],
            resource=row["resource"],
            persona=row["persona"],
            role=row["role"],
            metadata=dict(row["action_metadata"] or {}),
            identity=_identity_from_payload(row["identity"]),
        )
        return ApprovalRequest(
            approval_id=row["approval_id"],
            message=row["message"],
            action=action,
            risk=RiskLevel(row["risk"]),
            thread_id=row["thread_id"],
            requested_schema=dict(row["requested_schema"] or _default_schema()),
            created_at=_as_utc(row["created_at"]) or _utcnow(),
            expires_at=_as_utc(row["expires_at"]),
            status=row["status"],
            decided_by=row["decided_by"],
            justification=row["justification"],
            decided_at=_as_utc(row["decided_at"]),
            consumed_at=_as_utc(row["consumed_at"]),
        )

    def create(self, request: ApprovalRequest) -> None:
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.select(approvals_table.c.approval_id).where(
                    approvals_table.c.approval_id == request.approval_id
                )
            ).first()
            if existing is not None:
                raise ApprovalError(
                    f"duplicate approval_id '{request.approval_id}'"
                )
            conn.execute(
                approvals_table.insert().values(
                    approval_id=request.approval_id,
                    persona=request.action.persona,
                    action_type=request.action.action_type,
                    resource=request.action.resource,
                    role=request.action.role,
                    message=request.message,
                    requested_schema=request.requested_schema,
                    action_metadata=request.action.metadata or {},
                    identity=_identity_payload(request.action.identity),
                    risk=int(request.risk),
                    thread_id=request.thread_id,
                    status=request.status,
                    decided_by=request.decided_by,
                    justification=request.justification,
                    created_at=request.created_at,
                    expires_at=request.expires_at,
                    decided_at=request.decided_at,
                    consumed_at=request.consumed_at,
                )
            )

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._engine.begin() as conn:
            self._expire_lapsed(conn)
            row = conn.execute(
                sa.select(approvals_table).where(
                    approvals_table.c.approval_id == approval_id
                )
            ).mappings().first()
        return self._row_to_request(row) if row is not None else None

    def list_requests(
        self, persona: str, *, status: str | None = None
    ) -> list[ApprovalRequest]:
        with self._engine.begin() as conn:
            self._expire_lapsed(conn)
            query = (
                sa.select(approvals_table)
                .where(approvals_table.c.persona == persona)
                .order_by(approvals_table.c.created_at)
            )
            if status is not None:
                query = query.where(approvals_table.c.status == status)
            rows = conn.execute(query).mappings().all()
        return [self._row_to_request(row) for row in rows]

    def _find(
        self,
        persona: str,
        action_type: str,
        resource: str,
        statuses: tuple[str, ...],
    ) -> ApprovalRequest | None:
        with self._engine.begin() as conn:
            self._expire_lapsed(conn)
            row = conn.execute(
                sa.select(approvals_table)
                .where(
                    approvals_table.c.persona == persona,
                    approvals_table.c.action_type == action_type,
                    approvals_table.c.resource == resource,
                    approvals_table.c.status.in_(statuses),
                )
                .order_by(approvals_table.c.created_at)
            ).mappings().first()
        return self._row_to_request(row) if row is not None else None

    def find_pending(
        self, persona: str, action_type: str, resource: str
    ) -> ApprovalRequest | None:
        return self._find(persona, action_type, resource, ("pending",))

    def find_resolved(
        self, persona: str, action_type: str, resource: str
    ) -> ApprovalRequest | None:
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
        with self._lock, self._engine.begin() as conn:
            self._expire_lapsed(conn)
            row = conn.execute(
                sa.select(approvals_table).where(
                    approvals_table.c.approval_id == approval_id
                )
            ).mappings().first()
            if row is None:
                raise UnknownApprovalError(
                    f"unknown approval '{approval_id}'"
                )
            if row["status"] != "pending":
                raise ApprovalAlreadyDecidedError(
                    f"approval '{approval_id}' is already {row['status']}; "
                    f"duplicate decisions are rejected, not replayed."
                )
            conn.execute(
                approvals_table.update()
                .where(approvals_table.c.approval_id == approval_id)
                .values(
                    status="approved" if approved else "denied",
                    decided_by=decided_by,
                    justification=justification,
                    decided_at=_utcnow(),
                )
            )
            refreshed = conn.execute(
                sa.select(approvals_table).where(
                    approvals_table.c.approval_id == approval_id
                )
            ).mappings().first()
        assert refreshed is not None
        return self._row_to_request(refreshed)

    def consume(self, approval_id: str) -> bool:
        with self._lock, self._engine.begin() as conn:
            result = conn.execute(
                approvals_table.update()
                .where(
                    approvals_table.c.approval_id == approval_id,
                    approvals_table.c.status.in_(("approved", "denied")),
                )
                .values(status="consumed", consumed_at=_utcnow())
            )
            return bool(result.rowcount)


# ── Spend ledger (BudgetLedger protocol, persist: db) ────────────────


class PostgresBudgetLedger:
    """P13 ``BudgetLedger`` protocol backed by the persona DB.

    Selected by ``guardrails.budgets.model_call.persist: db``. Spend
    survives restarts AND is shared across processes serving the same
    persona (the file ledger is single-host; the DB ledger is the
    fleet-correct one).
    """

    def __init__(self, engine: Engine, *, persona: str) -> None:
        self._engine = engine
        self._persona = persona

    def record(self, cost_usd: float, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                guardrail_spend_table.insert().values(
                    persona=self._persona, cost_usd=cost_usd, at=at
                )
            )

    def spent_since(self, since: datetime) -> float:
        with self._engine.connect() as conn:
            value = conn.execute(
                sa.select(
                    sa.func.coalesce(
                        sa.func.sum(guardrail_spend_table.c.cost_usd), 0.0
                    )
                ).where(
                    guardrail_spend_table.c.persona == self._persona,
                    guardrail_spend_table.c.at >= since,
                )
            ).scalar()
        return float(value or 0.0)


# ── Durable audit log ────────────────────────────────────────────────


class PostgresAuditStore:
    """Append-only guardrail/approval decision log on the persona DB."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(
        self,
        persona: str,
        event: str,
        *,
        action_type: str = "",
        resource: str = "",
        role: str = "",
        decision: str = "",
        reason: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                audit_log_table.insert().values(
                    persona=persona,
                    event=event,
                    action_type=action_type,
                    resource=resource,
                    role=role,
                    decision=decision,
                    reason=reason,
                    attributes=attributes or {},
                    created_at=_utcnow(),
                )
            )


class InMemoryAuditStore:
    """List-backed audit sink twin (tests + fakes)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(
        self,
        persona: str,
        event: str,
        *,
        action_type: str = "",
        resource: str = "",
        role: str = "",
        decision: str = "",
        reason: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "persona": persona,
                "event": event,
                "action_type": action_type,
                "resource": resource,
                "role": role,
                "decision": decision,
                "reason": reason,
                "attributes": attributes or {},
            }
        )


# ── Per-persona resolution + audit sink registry ─────────────────────


@dataclass
class DurableStores:
    """The durable-tier stores for one persona (built lazily, cached)."""

    persona: str
    config: SessionsConfig
    sessions: PostgresSessionStore | Any
    approvals: ApprovalStore
    audit: Any


_STORES: dict[str, DurableStores] = {}
_AUDIT_SINKS: dict[str, Any] = {}
_STORES_LOCK = threading.Lock()


def durable_stores_for(persona: Any) -> DurableStores | None:
    """Resolve (and cache) the durable stores for a persona.

    Returns ``None`` for personas without ``sessions: {durable: true}``
    — every consumer then keeps its in-memory/deny defaults. A durable
    declaration WITHOUT a resolvable ``database_url`` raises an
    actionable error (declared durability must never silently
    degrade — same posture as declared A2A auth). Engines are lazy:
    building the stores never touches the network; an unreachable DB
    surfaces on first store operation.
    """
    config = getattr(persona, "sessions", None)
    if not isinstance(config, SessionsConfig) or not config.durable:
        return None
    name = getattr(persona, "name", "")
    with _STORES_LOCK:
        cached = _STORES.get(name)
        if cached is not None:
            return cached
        database_url = getattr(persona, "database_url", "")
        if not database_url:
            raise ValueError(
                f"Persona '{name}' declares sessions: {{durable: true}} "
                f"but no database url resolved — configure database: "
                f"{{url_env: ...}} (durable sessions need the persona "
                f"DB) or remove the sessions section."
            )
        from assistant.core.db import create_sync_engine

        engine = create_sync_engine(database_url)
        stores = DurableStores(
            persona=name,
            config=config,
            sessions=PostgresSessionStore(engine),
            approvals=PostgresApprovalStore(engine),
            audit=PostgresAuditStore(engine),
        )
        _STORES[name] = stores
        _AUDIT_SINKS[name] = stores.audit
        return stores


def register_audit_sink(persona_name: str, sink: Any) -> None:
    """Register a durable audit sink for a persona (tests inject fakes)."""
    with _STORES_LOCK:
        _AUDIT_SINKS[persona_name] = sink


def get_audit_sink(persona_name: str) -> Any | None:
    with _STORES_LOCK:
        return _AUDIT_SINKS.get(persona_name)


def record_durable_audit(
    persona_name: str,
    event: str,
    *,
    action_type: str = "",
    resource: str = "",
    role: str = "",
    decision: str = "",
    reason: str = "",
    attributes: dict[str, Any] | None = None,
) -> None:
    """Best-effort append to the persona's durable audit sink.

    No sink registered (durability off, or the persona never resolved
    its stores in this process) → no-op. Failures are swallowed with a
    WARNING — the audit trail must never change enforcement outcomes
    (same posture as the telemetry spans).
    """
    sink = get_audit_sink(persona_name)
    if sink is None:
        return
    try:
        sink.append(
            persona_name,
            event,
            action_type=action_type,
            resource=resource,
            role=role,
            decision=decision,
            reason=reason,
            attributes=attributes,
        )
    except Exception as exc:
        logger.warning(
            "durable audit append failed for persona %r (%s); "
            "enforcement is unaffected",
            persona_name,
            type(exc).__name__,
        )


def _clear_durable_state() -> None:
    """Test hook: drop cached stores + audit sinks."""
    with _STORES_LOCK:
        _STORES.clear()
        _AUDIT_SINKS.clear()


__all__ = [
    "DurableStores",
    "InMemoryAuditStore",
    "InMemorySessionStore",
    "PostgresApprovalStore",
    "PostgresAuditStore",
    "PostgresBudgetLedger",
    "PostgresSessionStore",
    "SessionRecord",
    "SessionsConfig",
    "SessionsConfigError",
    "_clear_durable_state",
    "approvals_table",
    "audit_log_table",
    "durable_stores_for",
    "get_audit_sink",
    "guardrail_spend_table",
    "metadata",
    "parse_sessions_config",
    "record_durable_audit",
    "register_audit_sink",
    "sessions_table",
]
