"""MemoryManager — coordinated Postgres + Graphiti memory layer."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.core.models import Interaction, MemoryEntry, Preference
from assistant.telemetry.decorators import trace_memory_op

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        graphiti_client: Any | None = None,
        persona_name: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._graphiti = graphiti_client
        self._persona_name = persona_name

    def _resolve_persona(self, persona: str | None) -> str:
        if persona:
            return persona
        if self._persona_name:
            return self._persona_name
        raise ValueError(
            "persona is required when MemoryManager is not bound at construction",
        )

    @trace_memory_op("context")
    async def get_context(
        self, persona: str | None, role: str, limit: int = 50
    ) -> str:
        resolved_persona = self._resolve_persona(persona)
        sections: list[str] = []

        async with self._session_factory() as session:
            result = await session.execute(
                select(MemoryEntry)
                .where(MemoryEntry.persona == resolved_persona)
                .order_by(MemoryEntry.updated_at.desc())
                .limit(limit)
            )
            entries = result.scalars().all()

        if entries:
            lines = [f"- **{e.key}**: {json.dumps(e.value)}" for e in entries]
            sections.append("## Active Context\n" + "\n".join(lines))
        else:
            sections.append("## Active Context\nNo active context entries.")

        if self._graphiti is not None:
            try:
                results = await self._graphiti.search(role, num_results=5)
                if results:
                    lines = [f"- {_extract_content(r)}" for r in results]
                    sections.append("## Semantic Context\n" + "\n".join(lines))
            except Exception:
                logger.warning(
                    "Graphiti search failed for persona '%s', degrading to Postgres-only",
                    resolved_persona,
                )

        return "\n\n".join(sections) + "\n"

    @trace_memory_op("snippets")
    async def get_recent_snippets(
        self, persona: str, role: str, limit: int = 10
    ) -> list[str]:
        """Return up to ``limit`` short memory snippets for prompt prepend.

        Composition (memory-retrieval-activation):

        - *Durable* snippets — recent facts (``memory`` table, most
          recently updated first), high-confidence preferences, and
          Graphiti semantic search results for ``role`` when the
          knowledge graph is configured (degrading to Postgres-only
          with a warning on connection errors, mirroring
          ``get_context``).
        - *Recent* snippets — the latest interaction summaries.

        Budgeting: durable snippets get the ceiling half of ``limit``;
        interaction summaries fill the remainder. If either bucket
        under-fills, the other backfills so the total is min(available,
        ``limit``). This guarantees both durable knowledge and recency
        are represented when both exist.
        """
        if limit <= 0:
            return []

        async with self._session_factory() as session:
            mem_result = await session.execute(
                select(MemoryEntry)
                .where(MemoryEntry.persona == persona)
                .order_by(MemoryEntry.updated_at.desc())
                .limit(limit)
            )
            entries = mem_result.scalars().all()

            pref_result = await session.execute(
                select(Preference)
                .where(Preference.persona == persona)
                .order_by(Preference.confidence.desc())
                .limit(limit)
            )
            prefs = pref_result.scalars().all()

            inter_result = await session.execute(
                select(Interaction)
                .where(Interaction.persona == persona)
                .order_by(Interaction.created_at.desc())
                .limit(limit)
            )
            interactions = inter_result.scalars().all()

        durable: list[str] = [
            f"**{e.key}**: {json.dumps(e.value)}" for e in entries
        ]
        durable.extend(
            f"[{p.category}] **{p.key}**: {json.dumps(p.value)} "
            f"(confidence: {p.confidence})"
            for p in prefs
        )
        if self._graphiti is not None:
            # Inline (rather than calling ``self.search``) so exactly one
            # trace_memory_op span is emitted per req observability.6.
            try:
                results = await self._graphiti.search(role, num_results=limit)
                durable.extend(_extract_content(r) for r in results)
            except Exception:
                logger.warning(
                    "Graphiti search failed for persona '%s', "
                    "degrading to Postgres-only snippets",
                    persona,
                )

        recent: list[str] = [f"[{i.role}] {i.summary}" for i in interactions]

        head = durable[: limit - (limit // 2)]
        tail = recent[: limit - len(head)]
        if len(head) + len(tail) < limit:
            head = durable[: limit - len(tail)]
        return head + tail

    @trace_memory_op("fact_write")
    async def store_fact(
        self, persona: str | None, key: str, value: Any
    ) -> None:
        resolved_persona = self._resolve_persona(persona)
        try:
            json.dumps(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Value is not JSON-serializable: {e}") from e

        async with self._session_factory() as session:
            stmt = pg_insert(MemoryEntry).values(
                persona=resolved_persona, key=key, value=value,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_memory_persona_key",
                set_={"value": value, "updated_at": datetime.now(UTC)},
            )
            await session.execute(stmt)
            await session.commit()

    @trace_memory_op("preference_write")
    async def store_preference(
        self,
        persona: str,
        category: str,
        key: str,
        value: Any,
        confidence: float = 0.5,
    ) -> None:
        """Upsert one preference row (persona, category, key unique).

        Added by continual-learning (P28): the pipeline's apply step
        writes distilled ``preference`` proposals here. Follows the
        ``store_fact`` upsert pattern; ``value`` must be
        JSON-serializable and ``confidence`` must be within [0, 1].
        """
        try:
            json.dumps(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Value is not JSON-serializable: {e}") from e
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                f"confidence must be within [0, 1], got {confidence}."
            )

        async with self._session_factory() as session:
            stmt = pg_insert(Preference).values(
                persona=persona,
                category=category,
                key=key,
                value=value,
                confidence=confidence,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_preferences_persona_category_key",
                set_={
                    "value": value,
                    "confidence": confidence,
                    "updated_at": datetime.now(UTC),
                },
            )
            await session.execute(stmt)
            await session.commit()

    @trace_memory_op("interaction_write")
    async def store_interaction(
        self,
        persona: str | None,
        role: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        resolved_persona = self._resolve_persona(persona)
        async with self._session_factory() as session:
            interaction = Interaction(
                persona=resolved_persona,
                role=role,
                summary=summary,
                metadata_=metadata or {},
            )
            session.add(interaction)
            await session.commit()

    @trace_memory_op("interaction_list")
    async def list_interactions(
        self,
        persona: str,
        role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent interaction records as JSON-safe dicts.

        Consumed by ``assistant export-eval-dataset`` (P27
        eval-simulation-loop) to turn the post-turn capture stream into
        gen-eval scenario stubs. Newest first; optionally filtered by
        ``role``.
        """
        if limit <= 0:
            return []
        async with self._session_factory() as session:
            stmt = select(Interaction).where(Interaction.persona == persona)
            if role is not None:
                stmt = stmt.where(Interaction.role == role)
            stmt = stmt.order_by(Interaction.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            interactions = result.scalars().all()
        return [
            {
                "id": i.id,
                "role": i.role,
                "summary": i.summary,
                "created_at": (
                    i.created_at.isoformat()
                    if isinstance(i.created_at, datetime)
                    else (str(i.created_at) if i.created_at else None)
                ),
                "metadata": i.metadata_ or {},
            }
            for i in interactions
        ]

    @trace_memory_op("fact_list")
    async def list_facts(
        self, persona: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return the persona's stored facts as JSON-safe dicts.

        Structured sibling of the formatted ``get_context`` read,
        consumed by the P26 clean-room export gateway. Most recently
        updated first; non-positive ``limit`` short-circuits to ``[]``.
        """
        if limit <= 0:
            return []
        async with self._session_factory() as session:
            result = await session.execute(
                select(MemoryEntry)
                .where(MemoryEntry.persona == persona)
                .order_by(MemoryEntry.updated_at.desc())
                .limit(limit)
            )
            entries = result.scalars().all()
        return [
            {
                "id": e.id,
                "key": e.key,
                "value": e.value,
                "updated_at": _iso_or_none(e.updated_at),
            }
            for e in entries
        ]

    @trace_memory_op("preference_list")
    async def list_preferences(
        self, persona: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return the persona's preferences as JSON-safe dicts.

        Highest confidence first (mirrors ``get_recent_snippets``);
        non-positive ``limit`` short-circuits to ``[]``. Consumed by
        the P26 clean-room export gateway.
        """
        if limit <= 0:
            return []
        async with self._session_factory() as session:
            result = await session.execute(
                select(Preference)
                .where(Preference.persona == persona)
                .order_by(Preference.confidence.desc())
                .limit(limit)
            )
            prefs = result.scalars().all()
        return [
            {
                "id": p.id,
                "category": p.category,
                "key": p.key,
                "value": p.value,
                "confidence": p.confidence,
                "updated_at": _iso_or_none(p.updated_at),
            }
            for p in prefs
        ]

    @trace_memory_op("fact_delete")
    async def delete_facts_by_prefix(
        self, persona: str, key_prefix: str
    ) -> int:
        """Delete the persona's facts whose key starts with ``key_prefix``.

        Backs clean-room revocation purges (imported items live under
        ``cleanroom/<bundle_id>/``). An empty prefix is refused — this
        method must never be able to wipe a persona's whole memory
        table by accident. Returns the number of deleted rows.
        """
        if not key_prefix:
            raise ValueError(
                "delete_facts_by_prefix requires a non-empty key_prefix."
            )
        async with self._session_factory() as session:
            result = await session.execute(
                sa_delete(MemoryEntry).where(
                    MemoryEntry.persona == persona,
                    MemoryEntry.key.startswith(key_prefix, autoescape=True),
                )
            )
            await session.commit()
        deleted = getattr(result, "rowcount", 0) or 0
        return int(deleted)

    @trace_memory_op("episode_write")
    async def store_episode(
        self, persona: str | None, content: str, source: str
    ) -> None:
        resolved_persona = self._resolve_persona(persona)
        if self._graphiti is None:
            logger.warning(
                "Graphiti unavailable for persona '%s', discarding episode (source=%s)",
                    resolved_persona, source,
            )
            return
        try:
            from graphiti_core.nodes import EpisodeType

            await self._graphiti.add_episode(
                name=f"{resolved_persona}:{source}",
                episode_body=content,
                source=EpisodeType.text,
                reference_time=datetime.now(UTC),
            )
        except Exception:
            logger.warning(
                "Graphiti add_episode failed for persona '%s' (source=%s), discarding",
                resolved_persona, source,
            )

    @trace_memory_op("search")
    async def search(
        self, persona: str | None, query: str, num_results: int = 5
    ) -> list[str]:
        resolved_persona = self._resolve_persona(persona)
        if self._graphiti is None:
            return []
        try:
            results = await self._graphiti.search(query, num_results=num_results)
            return [_extract_content(r) for r in results]
        except Exception:
            logger.warning(
                    "Graphiti search failed for persona '%s'", resolved_persona
            )
            return []

    @trace_memory_op("export")
    async def export_memory(self, persona: str | None = None) -> str:
        resolved_persona = self._resolve_persona(persona)
        sections: list[str] = []

        async with self._session_factory() as session:
            mem_result = await session.execute(
                select(MemoryEntry)
                .where(MemoryEntry.persona == resolved_persona)
                .order_by(MemoryEntry.updated_at.desc())
                .limit(50)
            )
            entries = mem_result.scalars().all()

            pref_result = await session.execute(
                select(Preference)
                .where(Preference.persona == resolved_persona)
                .order_by(Preference.confidence.desc())
            )
            prefs = pref_result.scalars().all()

            inter_result = await session.execute(
                select(Interaction)
                .where(Interaction.persona == resolved_persona)
                .order_by(Interaction.created_at.desc())
                .limit(100)
            )
            interactions = inter_result.scalars().all()

        ctx_lines = [f"- **{e.key}**: {json.dumps(e.value)}" for e in entries]
        sections.append("## Active Context\n" + ("\n".join(ctx_lines) if ctx_lines else "None."))

        pref_lines = [
            f"- [{p.category}] **{p.key}**: {json.dumps(p.value)} (confidence: {p.confidence})"
            for p in prefs
        ]
        sections.append("## Preferences\n" + ("\n".join(pref_lines) if pref_lines else "None."))

        inter_lines = [
            f"- [{i.role}] {i.summary} ({i.created_at})" for i in interactions
        ]
        sections.append(
            "## Recent Interactions\n" + ("\n".join(inter_lines) if inter_lines else "None.")
        )

        if self._graphiti is not None:
            try:
                results = await self._graphiti.search("summary", num_results=10)
                if results:
                    lines = [f"- {_extract_content(r)}" for r in results]
                    sections.append("## Knowledge Graph Summary\n" + "\n".join(lines))
                else:
                    sections.append("## Knowledge Graph Summary\nNo entities found.")
            except Exception:
                logger.warning(
                    "Graphiti search failed during export for persona '%s'", resolved_persona
                )

        return "\n\n".join(sections) + "\n"


def _iso_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _extract_content(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "content"):
        return str(result.content)
    if hasattr(result, "fact"):
        return str(result.fact)
    if isinstance(result, dict):
        return str(result.get("content", result.get("fact", str(result))))
    return str(result)
