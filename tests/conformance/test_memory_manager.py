from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.core.memory import MemoryManager


def _make_session_factory(session: AsyncMock) -> MagicMock:
    factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = ctx
    return factory


@pytest.mark.asyncio
async def test_persona_bound_instance_writes_without_persona_argument() -> None:
    session = AsyncMock()
    mgr = MemoryManager(_make_session_factory(session), persona_name="test")

    await mgr.store_fact(None, "project", {"name": "agentic-assistant"})
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_persona_bound_context_read_without_persona_argument() -> None:
    session = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)
    mgr = MemoryManager(_make_session_factory(session), persona_name="test")

    context = await mgr.get_context(None, "researcher")
    assert "Active Context" in context
