"""MemoryManager — coordinated Postgres + Graphiti memory layer."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

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
    ) -> None:
        self._session_factory = session_factory
        self._graphiti = graphiti_client

    @trace_memory_op("context")
    async def get_context(
        self, persona: str, role: str, limit: int = 50
    ) -> str:
        sections: list[str] = []

        async with self._session_factory() as session:
            result = await session.execute(
                select(MemoryEntry)
                .where(MemoryEntry.persona == persona)
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
                    persona,
                )

        return "\n\n".join(sections) + "\n"

    @trace_memory_op("fact_write")
    async def store_fact(self, persona: str, key: str, value: Any) -> None:
        try:
            json.dumps(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Value is not JSON-serializable: {e}") from e

        async with self._session_factory() as session:
            stmt = pg_insert(MemoryEntry).values(
                persona=persona, key=key, value=value,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_memory_persona_key",
                set_={"value": value, "updated_at": datetime.now(UTC)},
            )
            await session.execute(stmt)
            await session.commit()

    @trace_memory_op("interaction_write")
    async def store_interaction(
        self,
        persona: str,
        role: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            interaction = Interaction(
                persona=persona,
                role=role,
                summary=summary,
                metadata_=metadata or {},
            )
            session.add(interaction)
            await session.commit()

    @trace_memory_op("episode_write")
    async def store_episode(
        self, persona: str, content: str, source: str
    ) -> None:
        if self._graphiti is None:
            logger.warning(
                "Graphiti unavailable for persona '%s', discarding episode (source=%s)",
                persona, source,
            )
            return
        try:
            from graphiti_core.nodes import EpisodeType

            await self._graphiti.add_episode(
                name=f"{persona}:{source}",
                episode_body=content,
                source=EpisodeType.text,
                reference_time=datetime.now(UTC),
            )
        except Exception:
            logger.warning(
                "Graphiti add_episode failed for persona '%s' (source=%s), discarding",
                persona, source,
            )

    @trace_memory_op("search")
    async def search(
        self, persona: str, query: str, num_results: int = 5
    ) -> list[str]:
        if self._graphiti is None:
            return []
        try:
            results = await self._graphiti.search(query, num_results=num_results)
            return [_extract_content(r) for r in results]
        except Exception:
            logger.warning(
                "Graphiti search failed for persona '%s'", persona
            )
            return []

    @trace_memory_op("export")
    async def export_memory(self, persona: str) -> str:
        sections: list[str] = []

        async with self._session_factory() as session:
            mem_result = await session.execute(
                select(MemoryEntry)
                .where(MemoryEntry.persona == persona)
                .order_by(MemoryEntry.updated_at.desc())
                .limit(50)
            )
            entries = mem_result.scalars().all()

            pref_result = await session.execute(
                select(Preference)
                .where(Preference.persona == persona)
                .order_by(Preference.confidence.desc())
            )
            prefs = pref_result.scalars().all()

            inter_result = await session.execute(
                select(Interaction)
                .where(Interaction.persona == persona)
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
                    "Graphiti search failed during export for persona '%s'", persona
                )

        return "\n\n".join(sections) + "\n"


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
