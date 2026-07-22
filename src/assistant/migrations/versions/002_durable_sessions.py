"""Durable session tier — sessions, approvals, spend, audit tables.

P30 durable-sessions: session metadata (re-bindable thread_ids),
persisted ApprovalRequests (guardrail interrupt/resume), the
DB-backed model-call spend ledger (``persist: db``), and the durable
guardrail/approval audit log.

NOTE: the LangGraph checkpointer's own tables (``checkpoints`` etc.)
are NOT managed here — ``AsyncPostgresSaver.setup()`` creates and
versions them on first use (``harnesses/sdk/checkpointer.py``).
Checkpointer schema and alembic migrations are separate concerns.

Revision ID: 002
Revises: 001
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("harness", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="active"
        ),
    )
    op.create_index("idx_sessions_persona", "sessions", ["persona"])

    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(64), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(512), nullable=False),
        sa.Column("role", sa.String(64), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "requested_schema",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "action_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("identity", postgresql.JSONB(), nullable=True),
        sa.Column("risk", sa.Integer(), nullable=False),
        sa.Column(
            "thread_id", sa.String(64), nullable=False, server_default=""
        ),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column(
            "decided_by", sa.String(128), nullable=False, server_default=""
        ),
        sa.Column(
            "justification", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_approvals_persona", "approvals", ["persona"])
    op.create_index(
        "idx_approvals_persona_status", "approvals", ["persona", "status"]
    )

    op.create_table(
        "guardrail_spend",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_guardrail_spend_persona_at", "guardrail_spend", ["persona", "at"]
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column(
            "action_type", sa.String(64), nullable=False, server_default=""
        ),
        sa.Column(
            "resource", sa.String(512), nullable=False, server_default=""
        ),
        sa.Column("role", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "decision", sa.String(32), nullable=False, server_default=""
        ),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_audit_log_persona_created",
        "audit_log",
        ["persona", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("guardrail_spend")
    op.drop_table("approvals")
    op.drop_table("sessions")
