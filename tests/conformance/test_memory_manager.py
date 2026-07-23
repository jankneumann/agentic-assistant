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


@pytest.mark.asyncio
async def test_bound_manager_rejects_mismatched_persona() -> None:
    """A bound manager must refuse an explicit persona that is not its own,
    rather than silently honoring either side and crossing the boundary."""
    session = AsyncMock()
    mgr = MemoryManager(_make_session_factory(session), persona_name="test")

    with pytest.raises(ValueError, match="persona mismatch"):
        await mgr.store_fact("someone_else", "project", {"x": 1})

    # The refusal happens before any DB access.
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_bound_manager_accepts_matching_persona() -> None:
    """Passing the same persona the manager is bound to is allowed."""
    session = AsyncMock()
    mgr = MemoryManager(_make_session_factory(session), persona_name="test")

    await mgr.store_fact("test", "project", {"x": 1})
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_unbound_manager_requires_persona_argument() -> None:
    """An unbound manager still requires an explicit persona (no regression
    for the CLI/host call sites that construct managers without binding)."""
    session = AsyncMock()
    mgr = MemoryManager(_make_session_factory(session))

    with pytest.raises(ValueError, match="persona is required"):
        await mgr.store_fact(None, "project", {"x": 1})
