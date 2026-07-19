"""Durable session tier (P30): config parse, sqlite-backed stores, audit.

The Postgres store implementations run their real SQL against sqlite
engines (``metadata.create_all``) so the public suite stays
server-free — the same store code paths execute in production against
the persona DB (migration 002 owns the authoritative Postgres DDL).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy.pool import StaticPool

from assistant.core import durable
from assistant.core.capabilities.approvals import (
    ApprovalAlreadyDecidedError,
    build_approval_request,
)
from assistant.core.capabilities.audit import emit_guardrail_audit
from assistant.core.capabilities.guardrails import (
    GuardrailConfigError,
    _clear_budget_ledgers,
    budget_ledger_for,
    parse_guardrail_config,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.types import (
    ActionDecision,
    ActionRequest,
    RiskLevel,
)
from assistant.core.db import sync_db_url
from assistant.core.durable import (
    InMemoryAuditStore,
    PostgresApprovalStore,
    PostgresAuditStore,
    PostgresBudgetLedger,
    PostgresSessionStore,
    SessionRecord,
    SessionsConfig,
    SessionsConfigError,
    durable_stores_for,
    parse_sessions_config,
    record_durable_audit,
    register_audit_sink,
)
from assistant.core.persona import PersonaRegistry


@pytest.fixture(autouse=True)
def _clean_durable_state():
    durable._clear_durable_state()
    _clear_budget_ledgers()
    yield
    durable._clear_durable_state()
    _clear_budget_ledgers()


@pytest.fixture
def engine():
    eng = sa.create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    durable.metadata.create_all(eng)
    yield eng
    eng.dispose()


# ── sessions: config parse ───────────────────────────────────────────


class TestSessionsConfigParse:
    def test_absent_section_is_falsy_default(self):
        config = parse_sessions_config(None)
        assert not config
        assert config.durable is False

    def test_durable_true_parses(self):
        config = parse_sessions_config(
            {"durable": True, "session_ttl_seconds": 60, "approval_ttl_seconds": 30}
        )
        assert config
        assert config.session_ttl_seconds == 60.0
        assert config.approval_ttl_seconds == 30.0

    def test_unknown_key_fails(self):
        with pytest.raises(SessionsConfigError, match="unknown keys"):
            parse_sessions_config({"durable": True, "bogus": 1})

    def test_non_boolean_durable_fails(self):
        with pytest.raises(SessionsConfigError, match="durable"):
            parse_sessions_config({"durable": "yes"})

    def test_negative_ttl_fails(self):
        with pytest.raises(SessionsConfigError, match="session_ttl_seconds"):
            parse_sessions_config({"durable": True, "session_ttl_seconds": -1})

    def test_persona_load_parses_sessions_section(self, tmp_path: Path):
        pdir = tmp_path / "durable_fixture"
        pdir.mkdir()
        (pdir / "persona.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "durable_fixture",
                    "harnesses": {"deep_agents": {"enabled": True}},
                    "sessions": {"durable": True, "session_ttl_seconds": 120},
                }
            )
        )
        pc = PersonaRegistry(tmp_path).load("durable_fixture")
        assert isinstance(pc.sessions, SessionsConfig)
        assert pc.sessions.durable is True
        assert pc.sessions.session_ttl_seconds == 120.0

    def test_persona_load_rejects_invalid_sessions_section(
        self, tmp_path: Path
    ):
        pdir = tmp_path / "bad_fixture"
        pdir.mkdir()
        (pdir / "persona.yaml").write_text(
            yaml.safe_dump({"name": "bad_fixture", "sessions": {"nope": 1}})
        )
        with pytest.raises(ValueError, match="sessions: section"):
            PersonaRegistry(tmp_path).load("bad_fixture")


# ── sync engine url normalization ────────────────────────────────────


class TestSyncDbUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("postgresql+asyncpg://u@h/db", "postgresql+psycopg://u@h/db"),
            ("postgresql://u@h/db", "postgresql+psycopg://u@h/db"),
            ("postgres://u@h/db", "postgresql+psycopg://u@h/db"),
            ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
            ("sqlite:///tmp/x.db", "sqlite:///tmp/x.db"),
        ],
    )
    def test_normalization(self, raw: str, expected: str):
        assert sync_db_url(raw) == expected


# ── session metadata store ───────────────────────────────────────────


class TestPostgresSessionStore:
    def test_record_get_roundtrip(self, engine):
        store = PostgresSessionStore(engine)
        record = SessionRecord(
            thread_id="t1", persona="fixture", role="coder", harness="deep_agents"
        )
        store.record(record)
        loaded = store.get("t1")
        assert loaded is not None
        assert loaded.persona == "fixture"
        assert loaded.role == "coder"
        assert loaded.status == "active"
        assert loaded.created_at.tzinfo is not None

    def test_get_unknown_returns_none(self, engine):
        assert PostgresSessionStore(engine).get("nope") is None

    def test_record_is_idempotent_upsert(self, engine):
        store = PostgresSessionStore(engine)
        store.record(
            SessionRecord(
                thread_id="t1", persona="fixture", role="coder", harness="h"
            )
        )
        store.record(
            SessionRecord(
                thread_id="t1", persona="fixture", role="writer", harness="h"
            )
        )
        loaded = store.get("t1")
        assert loaded is not None and loaded.role == "writer"

    def test_touch_slides_expiry_window(self, engine):
        store = PostgresSessionStore(engine)
        store.record(
            SessionRecord(
                thread_id="t1", persona="fixture", role="coder", harness="h"
            )
        )
        store.touch("t1", ttl_seconds=3600)
        loaded = store.get("t1")
        assert loaded is not None
        assert loaded.expires_at is not None
        assert loaded.expires_at > datetime.now(UTC)

    def test_mark_expired(self, engine):
        store = PostgresSessionStore(engine)
        store.record(
            SessionRecord(
                thread_id="t1", persona="fixture", role="coder", harness="h"
            )
        )
        store.mark_expired("t1")
        loaded = store.get("t1")
        assert loaded is not None and loaded.status == "expired"


# ── approvals store (same semantics as the in-memory twin) ───────────


def _action(resource: str = "expensive-opus") -> ActionRequest:
    return ActionRequest(
        action_type="model_call",
        resource=resource,
        persona="fixture",
        role="coder",
        metadata={"model_id": "opus"},
        identity=AgentIdentity(persona="fixture", role="coder"),
    )


def _decision() -> ActionDecision:
    return ActionDecision(
        allowed=True, reason="confirm", require_confirmation=True
    )


class TestPostgresApprovalStore:
    def test_create_get_roundtrip_with_identity(self, engine):
        store = PostgresApprovalStore(engine)
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.HIGH, thread_id="t1"
        )
        store.create(request)
        loaded = store.get(request.approval_id)
        assert loaded is not None
        assert loaded.action.resource == "expensive-opus"
        assert loaded.action.metadata == {"model_id": "opus"}
        assert loaded.action.identity is not None
        assert loaded.action.identity.persona == "fixture"
        assert loaded.risk is RiskLevel.HIGH
        assert loaded.thread_id == "t1"
        assert loaded.status == "pending"

    def test_first_decision_wins_and_consume_once(self, engine):
        store = PostgresApprovalStore(engine)
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.HIGH
        )
        store.create(request)
        decided = store.decide(
            request.approval_id,
            approved=True,
            decided_by="cli:fixture",
            justification="ok",
        )
        assert decided.status == "approved"
        with pytest.raises(ApprovalAlreadyDecidedError):
            store.decide(request.approval_id, approved=False)
        assert store.consume(request.approval_id) is True
        assert store.consume(request.approval_id) is False
        final = store.get(request.approval_id)
        assert final is not None and final.status == "consumed"

    def test_find_pending_and_resolved(self, engine):
        store = PostgresApprovalStore(engine)
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.LOW
        )
        store.create(request)
        assert (
            store.find_pending("fixture", "model_call", "expensive-opus")
            is not None
        )
        assert (
            store.find_resolved("fixture", "model_call", "expensive-opus")
            is None
        )
        store.decide(request.approval_id, approved=True)
        assert (
            store.find_pending("fixture", "model_call", "expensive-opus")
            is None
        )
        resolved = store.find_resolved(
            "fixture", "model_call", "expensive-opus"
        )
        assert resolved is not None and resolved.status == "approved"

    def test_pending_expires_lazily(self, engine):
        store = PostgresApprovalStore(engine)
        past = datetime.now(UTC) - timedelta(seconds=120)
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.LOW,
            expiry_seconds=30, now=past,
        )
        store.create(request)
        loaded = store.get(request.approval_id)
        assert loaded is not None and loaded.status == "expired"
        assert (
            store.find_pending("fixture", "model_call", "expensive-opus")
            is None
        )

    def test_list_requests_filters_status(self, engine):
        store = PostgresApprovalStore(engine)
        request = build_approval_request(
            _action(), _decision(), risk=RiskLevel.LOW
        )
        store.create(request)
        assert len(store.list_requests("fixture", status="pending")) == 1
        assert store.list_requests("other") == []


# ── spend ledger (persist: db) ───────────────────────────────────────


class TestPostgresBudgetLedger:
    def test_record_and_window_query(self, engine):
        ledger = PostgresBudgetLedger(engine, persona="fixture")
        now = datetime.now(UTC)
        ledger.record(0.4, now - timedelta(days=2))
        ledger.record(0.25, now)
        ledger.record(0.1, now)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        assert ledger.spent_since(day_start) == pytest.approx(0.35)
        assert ledger.spent_since(now - timedelta(days=3)) == pytest.approx(0.75)

    def test_ledger_is_persona_scoped(self, engine):
        a = PostgresBudgetLedger(engine, persona="a")
        b = PostgresBudgetLedger(engine, persona="b")
        now = datetime.now(UTC)
        a.record(1.0, now)
        assert b.spent_since(now - timedelta(minutes=1)) == 0.0

    def test_survives_ledger_reinstantiation(self, engine):
        now = datetime.now(UTC)
        PostgresBudgetLedger(engine, persona="fixture").record(0.5, now)
        fresh = PostgresBudgetLedger(engine, persona="fixture")
        assert fresh.spent_since(now - timedelta(minutes=1)) == pytest.approx(0.5)


class TestPersistDbSelection:
    def _config(self):
        return parse_guardrail_config(
            {
                "budgets": {
                    "model_call": {"daily_usd": 1.0, "persist": "db"}
                }
            }
        )

    def test_parse_accepts_db(self):
        assert self._config().spend_persist == "db"

    def test_parse_rejects_unknown_persist(self):
        with pytest.raises(GuardrailConfigError, match="persist"):
            parse_guardrail_config(
                {"budgets": {"model_call": {"persist": "redis"}}}
            )

    def test_db_persist_without_url_raises(self):
        with pytest.raises(GuardrailConfigError, match="database url"):
            budget_ledger_for("fixture", self._config())

    def test_db_persist_builds_postgres_ledger(self, tmp_path: Path):
        url = f"sqlite:///{tmp_path}/spend.db"
        # Create the schema the ledger queries.
        eng = sa.create_engine(url)
        durable.metadata.create_all(eng)
        eng.dispose()
        ledger = budget_ledger_for(
            "fixture", self._config(), database_url=url
        )
        assert isinstance(ledger, PostgresBudgetLedger)
        now = datetime.now(UTC)
        ledger.record(0.2, now)
        assert ledger.spent_since(
            now - timedelta(minutes=1)
        ) == pytest.approx(0.2)
        # Process-wide cache: same key returns the same ledger.
        again = budget_ledger_for(
            "fixture", self._config(), database_url=url
        )
        assert again is ledger


# ── durable audit log ────────────────────────────────────────────────


class TestDurableAudit:
    def test_postgres_audit_append(self, engine):
        store = PostgresAuditStore(engine)
        store.append(
            "fixture",
            "guardrail.decision",
            action_type="model_call",
            resource="opus",
            role="coder",
            decision="deny",
            reason="budget",
            attributes={"chain_depth": 0},
        )
        with engine.connect() as conn:
            rows = conn.execute(
                sa.select(durable.audit_log_table)
            ).mappings().all()
        assert len(rows) == 1
        assert rows[0]["decision"] == "deny"
        assert rows[0]["attributes"] == {"chain_depth": 0}

    def test_record_durable_audit_without_sink_is_noop(self):
        record_durable_audit("nobody", "guardrail.decision", decision="allow")

    def test_emit_guardrail_audit_appends_to_registered_sink(self):
        sink = InMemoryAuditStore()
        register_audit_sink("fixture", sink)
        action = _action()
        emit_guardrail_audit(
            action, ActionDecision(allowed=False, reason="denied by policy")
        )
        assert len(sink.events) == 1
        event = sink.events[0]
        assert event["persona"] == "fixture"
        assert event["decision"] == "deny"
        assert event["resource"] == "expensive-opus"

    def test_identity_less_requests_are_not_audited(self):
        sink = InMemoryAuditStore()
        register_audit_sink("fixture", sink)
        action = ActionRequest(
            action_type="model_call",
            resource="opus",
            persona="fixture",
            role="coder",
        )
        emit_guardrail_audit(action, ActionDecision(allowed=True))
        assert sink.events == []

    def test_failing_sink_never_raises(self):
        class _Boom:
            def append(self, *a, **k):
                raise RuntimeError("db down")

        register_audit_sink("fixture", _Boom())
        emit_guardrail_audit(
            _action(), ActionDecision(allowed=True)
        )  # must not raise


# ── per-persona store resolution ─────────────────────────────────────


class _PersonaStub:
    def __init__(self, name="fixture", sessions=None, database_url=""):
        self.name = name
        self.sessions = sessions
        self.database_url = database_url


class TestDurableStoresFor:
    def test_non_durable_persona_resolves_none(self):
        assert durable_stores_for(_PersonaStub()) is None
        assert (
            durable_stores_for(
                _PersonaStub(sessions=SessionsConfig(durable=False))
            )
            is None
        )

    def test_durable_without_url_raises_actionable_error(self):
        persona = _PersonaStub(sessions=SessionsConfig(durable=True))
        with pytest.raises(ValueError, match="database"):
            durable_stores_for(persona)

    def test_durable_persona_builds_and_caches_stores(self, tmp_path: Path):
        url = f"sqlite:///{tmp_path}/durable.db"
        eng = sa.create_engine(url)
        durable.metadata.create_all(eng)
        eng.dispose()
        persona = _PersonaStub(
            sessions=SessionsConfig(durable=True), database_url=url
        )
        stores = durable_stores_for(persona)
        assert stores is not None
        assert isinstance(stores.approvals, PostgresApprovalStore)
        assert isinstance(stores.sessions, PostgresSessionStore)
        assert durable_stores_for(persona) is stores
        # Resolution registers the durable audit sink.
        assert durable.get_audit_sink("fixture") is stores.audit
