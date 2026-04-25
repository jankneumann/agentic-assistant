"""Tests for the assistant context ContextVar (Task 1.9).

Spec: observability — Persona and Role Context Propagation
(spec.md:261-287). Design D4.
"""

from __future__ import annotations

import asyncio


def test_default_get_returns_none_pair() -> None:
    from assistant.telemetry.context import get_assistant_ctx, set_assistant_ctx

    # The default reset isn't perfect across tests; explicitly clear.
    set_assistant_ctx(None, None)
    assert get_assistant_ctx() == (None, None)


def test_set_and_get_round_trip() -> None:
    from assistant.telemetry.context import get_assistant_ctx, set_assistant_ctx

    set_assistant_ctx("personal", "assistant")
    assert get_assistant_ctx() == ("personal", "assistant")
    set_assistant_ctx(None, None)


def test_assistant_ctx_pushes_and_pops() -> None:
    from assistant.telemetry.context import (
        assistant_ctx,
        get_assistant_ctx,
        set_assistant_ctx,
    )

    set_assistant_ctx("personal", "assistant")
    with assistant_ctx("personal", "researcher"):
        assert get_assistant_ctx() == ("personal", "researcher")
    assert get_assistant_ctx() == ("personal", "assistant")
    set_assistant_ctx(None, None)


def test_context_persists_across_await() -> None:
    """Spec scenario: 'Context persists across await'."""
    from assistant.telemetry.context import get_assistant_ctx, set_assistant_ctx

    async def inner() -> tuple[tuple[str | None, str | None], tuple[str | None, str | None]]:
        before = get_assistant_ctx()
        await asyncio.sleep(0)
        after = get_assistant_ctx()
        return before, after

    async def outer() -> tuple[tuple[str | None, str | None], tuple[str | None, str | None]]:
        set_assistant_ctx("personal", "assistant")
        try:
            return await inner()
        finally:
            set_assistant_ctx(None, None)

    before, after = asyncio.run(outer())
    assert before == ("personal", "assistant")
    assert after == ("personal", "assistant")


def test_assistant_ctx_in_async_scope() -> None:
    """Spec scenario: 'Delegation updates context for the sub-agent's spans'."""
    from assistant.telemetry.context import (
        assistant_ctx,
        get_assistant_ctx,
        set_assistant_ctx,
    )

    async def sub_agent() -> tuple[str | None, str | None]:
        return get_assistant_ctx()

    async def parent() -> tuple[
        tuple[str | None, str | None],
        tuple[str | None, str | None],
        tuple[str | None, str | None],
    ]:
        set_assistant_ctx("personal", "assistant")
        before = get_assistant_ctx()
        with assistant_ctx("personal", "researcher"):
            inside = await sub_agent()
        after = get_assistant_ctx()
        return before, inside, after

    before, inside, after = asyncio.run(parent())
    assert before == ("personal", "assistant")
    assert inside == ("personal", "researcher")
    assert after == ("personal", "assistant")


def test_concurrent_delegations_are_isolated() -> None:
    """Spec scenario: 'Concurrent delegations each see their own sub-role'.

    Per spec, the implementation MUST spawn each sub-agent in a
    distinct ``asyncio.Task`` so the per-task contextvar semantics
    apply.
    """
    from assistant.telemetry.context import (
        assistant_ctx,
        get_assistant_ctx,
        set_assistant_ctx,
    )

    async def sub_agent(role: str) -> tuple[str | None, str | None]:
        # Inside its own Task, push the sub-role and read the context.
        with assistant_ctx("personal", role):
            await asyncio.sleep(0)  # force a context switch
            return get_assistant_ctx()

    async def parent() -> tuple[
        tuple[str | None, str | None],
        tuple[str | None, str | None],
        tuple[str | None, str | None],
    ]:
        set_assistant_ctx("personal", "assistant")
        # Spawn each sub-agent in its own asyncio.Task.
        results = await asyncio.gather(
            asyncio.create_task(sub_agent("researcher")),
            asyncio.create_task(sub_agent("writer")),
        )
        return results[0], results[1], get_assistant_ctx()

    r0, r1, parent_ctx = asyncio.run(parent())
    assert r0 == ("personal", "researcher")
    assert r1 == ("personal", "writer")
    assert parent_ctx == ("personal", "assistant")


def test_assistant_ctx_pops_on_exception() -> None:
    from assistant.telemetry.context import (
        assistant_ctx,
        get_assistant_ctx,
        set_assistant_ctx,
    )

    set_assistant_ctx("personal", "assistant")
    try:
        with assistant_ctx("personal", "researcher"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert get_assistant_ctx() == ("personal", "assistant")
    set_assistant_ctx(None, None)
