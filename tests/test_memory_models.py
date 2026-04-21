"""Tests for core/models.py — ORM model definitions."""

from __future__ import annotations

from assistant.core.db import Base
from assistant.core.models import Interaction, MemoryEntry, Preference


class TestMemoryEntry:
    def test_inherits_from_base(self):
        assert issubclass(MemoryEntry, Base)

    def test_tablename(self):
        assert MemoryEntry.__tablename__ == "memory"

    def test_has_required_columns(self):
        cols = {c.name for c in MemoryEntry.__table__.columns}
        assert {"id", "persona", "key", "value", "updated_at"} <= cols

    def test_unique_constraint_persona_key(self):
        constraints = [
            c.name
            for c in MemoryEntry.__table__.constraints
            if hasattr(c, "name") and c.name
        ]
        assert "uq_memory_persona_key" in constraints

    def test_value_is_jsonb(self):
        col = MemoryEntry.__table__.c.value
        assert "JSON" in str(col.type).upper()


class TestPreference:
    def test_inherits_from_base(self):
        assert issubclass(Preference, Base)

    def test_tablename(self):
        assert Preference.__tablename__ == "preferences"

    def test_has_required_columns(self):
        cols = {c.name for c in Preference.__table__.columns}
        assert {"id", "persona", "category", "key", "value", "confidence", "updated_at"} <= cols

    def test_unique_constraint_persona_category_key(self):
        constraints = [
            c.name
            for c in Preference.__table__.constraints
            if hasattr(c, "name") and c.name
        ]
        assert "uq_preferences_persona_category_key" in constraints

    def test_confidence_is_float(self):
        col = Preference.__table__.c.confidence
        assert "FLOAT" in str(col.type).upper() or "REAL" in str(col.type).upper()


class TestInteraction:
    def test_inherits_from_base(self):
        assert issubclass(Interaction, Base)

    def test_tablename(self):
        assert Interaction.__tablename__ == "interactions"

    def test_has_required_columns(self):
        cols = {c.name for c in Interaction.__table__.columns}
        assert {"id", "persona", "role", "summary", "metadata", "created_at"} <= cols

    def test_metadata_is_jsonb(self):
        col = Interaction.__table__.c.metadata
        assert "JSON" in str(col.type).upper()

    def test_summary_is_text(self):
        col = Interaction.__table__.c.summary
        assert "TEXT" in str(col.type).upper()
