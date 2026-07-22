"""SessionRegistry durable re-bind path (P30 durable-sessions).

The registry moved to ``assistant.harnesses.sessions`` (P17 D7
relocation); the pre-P30 in-memory suites keep running against the
compat re-export in ``assistant.a2a.task_handler``. These tests cover
the NEW durable tier: metadata recording, resolve() re-bind after
in-process expiry, durable TTL lapse, and role scoping — all against
the in-memory store fake (semantics twin of the Postgres store).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from assistant.core.durable import InMemorySessionStore
from assistant.harnesses.sessions import SessionRegistry
from tests.a2a.helpers import FakeHarness, make_session_factory


def _rebind_factory(created: list[FakeHarness]):
    async def _rebind(thread_id: str):
        harness = FakeHarness(thread_id=thread_id)
        created.append(harness)
        return harness, {"agent-for": thread_id}

    return _rebind


async def test_compat_reexport_from_task_handler():
    from assistant.a2a import task_handler

    assert task_handler.SessionRegistry is SessionRegistry


async def test_create_records_session_metadata():
    factory, _created = make_session_factory()
    store = InMemorySessionStore()
    registry = SessionRegistry(
        factory,
        store=store,
        persona="fixture",
        role="coder",
        harness="deep_agents",
    )
    session = await registry.create()
    record = store.get(session.thread_id)
    assert record is not None
    assert record.persona == "fixture"
    assert record.role == "coder"
    assert record.harness == "deep_agents"
    assert record.status == "active"


async def test_resolve_returns_live_session_first():
    factory, _ = make_session_factory()
    store = InMemorySessionStore()
    rebound: list[FakeHarness] = []
    registry = SessionRegistry(
        factory, store=store, rebind_factory=_rebind_factory(rebound)
    )
    session = await registry.create()
    assert await registry.resolve(session.thread_id) is session
    assert rebound == []


async def test_resolve_rebinds_after_in_process_expiry():
    factory, _ = make_session_factory()
    store = InMemorySessionStore()
    rebound: list[FakeHarness] = []
    registry = SessionRegistry(
        factory,
        store=store,
        rebind_factory=_rebind_factory(rebound),
        role="coder",
        persona="fixture",
    )
    session = await registry.create()
    thread_id = session.thread_id
    # In-process expiry releases resources but NOT durable state.
    assert registry.expire(thread_id) is True
    assert registry.lookup(thread_id) is None
    resolved = await registry.resolve(thread_id)
    assert resolved is not None
    assert resolved.thread_id == thread_id
    assert len(rebound) == 1
    assert rebound[0].thread_id == thread_id
    # The re-bound session is now live again.
    assert registry.lookup(thread_id) is resolved


async def test_resolve_unknown_id_returns_none():
    factory, _ = make_session_factory()
    registry = SessionRegistry(
        factory,
        store=InMemorySessionStore(),
        rebind_factory=_rebind_factory([]),
    )
    assert await registry.resolve("never-created") is None


async def test_resolve_without_durable_tier_preserves_pre_p30_behavior():
    factory, _ = make_session_factory()
    registry = SessionRegistry(factory)
    session = await registry.create()
    registry.expire(session.thread_id)
    assert await registry.resolve(session.thread_id) is None


async def test_resolve_rejects_lapsed_durable_session():
    factory, _ = make_session_factory()
    store = InMemorySessionStore()
    registry = SessionRegistry(
        factory,
        store=store,
        rebind_factory=_rebind_factory([]),
        durable_ttl_seconds=60,
    )
    session = await registry.create()
    thread_id = session.thread_id
    registry.expire(thread_id)
    # Lapse the durable window.
    record = store.get(thread_id)
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await registry.resolve(thread_id) is None
    refreshed = store.get(thread_id)
    assert refreshed is not None and refreshed.status == "expired"


async def test_resolve_rejects_expired_status_row():
    factory, _ = make_session_factory()
    store = InMemorySessionStore()
    registry = SessionRegistry(
        factory, store=store, rebind_factory=_rebind_factory([])
    )
    session = await registry.create()
    registry.expire(session.thread_id)
    store.mark_expired(session.thread_id)
    assert await registry.resolve(session.thread_id) is None


async def test_resolve_rejects_foreign_role_session():
    factory, _ = make_session_factory()
    store = InMemorySessionStore()
    coder = SessionRegistry(
        factory,
        store=store,
        rebind_factory=_rebind_factory([]),
        role="coder",
    )
    session = await coder.create()
    coder.expire(session.thread_id)
    writer = SessionRegistry(
        factory,
        store=store,
        rebind_factory=_rebind_factory([]),
        role="writer",
    )
    assert await writer.resolve(session.thread_id) is None


async def test_rebind_factory_thread_id_mismatch_raises():
    factory, _ = make_session_factory()
    store = InMemorySessionStore()

    async def _bad_rebind(thread_id: str):
        harness = FakeHarness(thread_id="something-else")
        return harness, {}

    registry = SessionRegistry(
        factory, store=store, rebind_factory=_bad_rebind
    )
    session = await registry.create()
    registry.expire(session.thread_id)
    with pytest.raises(ValueError, match="thread_id"):
        await registry.resolve(session.thread_id)


async def test_a2a_handler_rebinds_expired_context_id():
    """End-to-end: an in-process-expired contextId is resumable through
    the A2A task handler when the durable tier is configured."""
    from assistant.a2a.task_handler import A2ATaskHandler
    from assistant.a2a.types import MessageSendParams, TaskState
    from tests.a2a.helpers import user_message_payload

    factory, _ = make_session_factory()
    store = InMemorySessionStore()
    rebound: list[FakeHarness] = []
    registry = SessionRegistry(
        factory, store=store, rebind_factory=_rebind_factory(rebound)
    )
    handler = A2ATaskHandler(registry)

    first = await handler.handle_message_send(
        MessageSendParams.model_validate(user_message_payload("hi"))
    )
    context_id = first.context_id
    registry.expire(context_id)

    second = await handler.handle_message_send(
        MessageSendParams.model_validate(
            user_message_payload("again", context_id=context_id)
        )
    )
    assert second.context_id == context_id
    assert second.status.state is TaskState.COMPLETED
    assert len(rebound) == 1


async def test_a2a_handler_still_rejects_truly_unknown_context_id():
    from assistant.a2a.task_handler import A2ATaskHandler
    from assistant.a2a.types import A2AProtocolError, MessageSendParams
    from tests.a2a.helpers import user_message_payload

    factory, _ = make_session_factory()
    registry = SessionRegistry(
        factory,
        store=InMemorySessionStore(),
        rebind_factory=_rebind_factory([]),
    )
    handler = A2ATaskHandler(registry)
    with pytest.raises(A2AProtocolError, match="unknown contextId"):
        await handler.handle_message_send(
            MessageSendParams.model_validate(
                user_message_payload("hi", context_id="never-created")
            )
        )


async def test_store_failure_never_breaks_create():
    class _BoomStore:
        def record(self, record):
            raise RuntimeError("db down")

        def get(self, thread_id):
            raise RuntimeError("db down")

        def touch(self, thread_id, *, ttl_seconds=0.0):
            raise RuntimeError("db down")

        def mark_expired(self, thread_id):
            raise RuntimeError("db down")

    factory, _ = make_session_factory()
    registry = SessionRegistry(
        factory, store=_BoomStore(), rebind_factory=_rebind_factory([])
    )
    session = await registry.create()  # must not raise
    assert registry.lookup(session.thread_id) is session
    # Durable resolve degrades to unknown, not to a crash.
    registry.expire(session.thread_id)
    assert await registry.resolve(session.thread_id) is None
