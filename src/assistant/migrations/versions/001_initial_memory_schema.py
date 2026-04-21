"""Initial memory schema — memory, preferences, interactions tables.

Revision ID: 001
Revises: None
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("persona", "key", name="uq_memory_persona_key"),
    )
    op.create_index("idx_memory_persona", "memory", ["persona"])

    op.create_table(
        "preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "persona", "category", "key", name="uq_preferences_persona_category_key"
        ),
    )
    op.create_index(
        "idx_preferences_persona_category", "preferences", ["persona", "category"]
    )

    op.create_table(
        "interactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_interactions_persona_created",
        "interactions",
        ["persona", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("interactions")
    op.drop_table("preferences")
    op.drop_table("memory")
