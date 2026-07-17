"""SessionRegistry tests — harness-adapter Session Registry requirement
(first consumer: P6 a2a-server): create/lookup/expire by thread_id.
"""

from __future__ import annotations

import pytest

from assistant.a2a.task_handler import SessionRegistry
from tests.a2a.helpers import make_session_factory


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_create_returns_session_keyed_by_harness_thread_id():
    factory, created = make_session_factory()
    registry = SessionRegistry(factory)
    session = await registry.create()
    assert session.thread_id == created[0].thread_id
    assert session.harness is created[0]
    assert len(registry) == 1


async def test_created_sessions_have_distinct_thread_ids():
    factory, _ = make_session_factory()
    registry = SessionRegistry(factory)
    s1 = await registry.create()
    s2 = await registry.create()
    assert s1.thread_id != s2.thread_id
    assert len(registry) == 2


async def test_lookup_returns_same_live_session():
    factory, _ = make_session_factory()
    registry = SessionRegistry(factory)
    session = await registry.create()
    assert registry.lookup(session.thread_id) is session


async def test_lookup_unknown_thread_id_returns_none():
    factory, _ = make_session_factory()
    registry = SessionRegistry(factory)
    assert registry.lookup("never-created") is None
    # Never silently creates.
    assert len(registry) == 0


async def test_expire_releases_session():
    factory, _ = make_session_factory()
    registry = SessionRegistry(factory)
    session = await registry.create()
    assert registry.expire(session.thread_id) is True
    assert registry.lookup(session.thread_id) is None
    assert registry.expire(session.thread_id) is False


async def test_idle_ttl_expires_stale_sessions():
    clock = _FakeClock()
    factory, _ = make_session_factory()
    registry = SessionRegistry(factory, idle_ttl_seconds=100.0, clock=clock)
    session = await registry.create()

    clock.advance(50.0)
    # Still live; lookup refreshes the idle clock.
    assert registry.lookup(session.thread_id) is session

    clock.advance(99.0)
    assert registry.lookup(session.thread_id) is session  # refreshed at t=50

    clock.advance(101.0)
    assert registry.lookup(session.thread_id) is None
    assert len(registry) == 0


async def test_duplicate_thread_id_from_factory_rejected():
    from tests.a2a.helpers import FakeHarness

    fixed = FakeHarness(thread_id="thread-dup")

    async def _factory():
        return fixed, object()

    registry = SessionRegistry(_factory)
    await registry.create()
    with pytest.raises(ValueError, match="duplicate thread_id"):
        await registry.create()
