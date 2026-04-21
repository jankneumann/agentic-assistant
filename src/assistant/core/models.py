"""SQLAlchemy ORM models for per-persona memory storage."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Float,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from assistant.core.db import Base


class MemoryEntry(Base):
    __tablename__ = "memory"

    id: Mapped[int] = mapped_column(primary_key=True)
    persona: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("persona", "key", name="uq_memory_persona_key"),
        Index("idx_memory_persona", "persona"),
    )


class Preference(Base):
    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    persona: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "persona", "category", "key", name="uq_preferences_persona_category_key"
        ),
        Index("idx_preferences_persona_category", "persona", "category"),
    )


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    persona: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_interactions_persona_created", "persona", created_at.desc()),
    )
