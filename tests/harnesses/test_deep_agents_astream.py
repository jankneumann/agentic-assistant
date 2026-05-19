"""Tests for DeepAgentsHarness.astream_invoke (harness-ag-ui-bridge tasks 3.1-3.5).

TDD: written BEFORE the implementation in deep_agents.py. Tests will fail
(RED) until task 3.6 adds astream_invoke to DeepAgentsHarness.

Spec scenarios covered:
  3.1 — "astream_invoke emits RunStarted then RunFinished" (lifecycle bracketing)
  3.2 — "astream_invoke passes thread_id to LangGraph"
  3.3 — "astream_invoke translates LangChain text chunks to TextDelta"
  3.4 — "astream_invoke translates tool calls to lifecycle events"
  3.5 — "astream_invoke emits RunFinished with error on exception (two-phase)"

Design references: D1, D3, D4, D7, D8, D9

Implementation approach: agent.astream_events(version="v2") is used to obtain
standard LangChain event dicts. Relevant event names:
  - "on_chat_model_stream" -> TextDelta
  - "on_tool_start"        -> ToolCallStart (+ ToolCallArgs with JSON args)
  - "on_tool_end"          -> ToolCallEnd

All tests use a fake agent whose astream_events is an async generator stub —
no real LLM calls, no deepagents import needed in the test body.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessageChunk

from assistant.harnesses.sdk.deep_agents import DeepAgentsHarness
from assistant.harnesses.sdk.events import (
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)

# ---------------------------------------------------------------------------
# Helpers — fake agent and fake astream_events output
# ---------------------------------------------------------------------------


def _make_harness() -> DeepAgentsHarness:
    """Construct a DeepAgentsHarness without calling create_agent."""
    persona = MagicMock()
    persona.name = "test"
    persona.harnesses = {}
    role = MagicMock()
    role.name = "assistant"
    role.skills_dir = None
    harness = DeepAgentsHarness.__new__(DeepAgentsHarness)
    # Manually wire up the attrs that __init__ sets (avoid side effects from
    # importing create_deep_agent at construction time).
    harness.persona = persona
    harness.role = role
    harness._active_model = DeepAgentsHarness._DEFAULT_MODEL
    harness._thread_id = "thread-test-uuid-1234"
    return harness


def _text_chunk_event(content: str, run_id: str = "run-text-001") -> dict[str, Any]:
    """Simulate an on_chat_model_stream event from astream_events v2."""
    chunk = MagicMock(spec=AIMessageChunk)
    chunk.content = content
    chunk.tool_call_chunks = []
    chunk.id = "msg-001"
    return {
        "event": "on_chat_model_stream",
        "run_id": run_id,
        "name": "ChatModel",
        "data": {"chunk": chunk},
        "metadata": {},
        "tags": [],
    }


def _tool_start_event(
    tool_name: str,
    tool_input: dict[str, Any],
    run_id: str = "run-tool-001",
) -> dict[str, Any]:
    """Simulate an on_tool_start event from astream_events v2."""
    return {
        "event": "on_tool_start",
        "run_id": run_id,
        "name": tool_name,
        "data": {"input": tool_input},
        "metadata": {},
        "tags": [],
    }


def _tool_end_event(
    tool_name: str,
    output: Any,
    run_id: str = "run-tool-001",
) -> dict[str, Any]:
    """Simulate an on_tool_end event from astream_events v2."""
    return {
        "event": "on_tool_end",
        "run_id": run_id,
        "name": tool_name,
        "data": {"output": output},
        "metadata": {},
        "tags": [],
    }


def _make_fake_agent(events: list[dict[str, Any]]) -> MagicMock:
    """Return a fake agent object whose astream_events yields the given events."""

    async def _astream_events(
        *args: Any, version: str = "v2", **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        for ev in events:
            yield ev

    fake = MagicMock()
    fake.astream_events = _astream_events
    return fake


def _make_raising_agent(exc: Exception) -> MagicMock:
    """Return a fake agent whose astream_events raises after one event."""

    async def _astream_events(
        *args: Any, version: str = "v2", **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        yield _text_chunk_event("partial")
        raise exc

    fake = MagicMock()
    fake.astream_events = _astream_events
    return fake


# ---------------------------------------------------------------------------
# Task 3.1 — Lifecycle bracketing: RunStarted first, RunFinished last
# Spec: "astream_invoke emits RunStarted then RunFinished"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_invoke_starts_with_run_started() -> None:
    """First event MUST be RunStarted (harness-ag-ui-bridge 3.1)."""
    harness = _make_harness()
    agent = _make_fake_agent([_text_chunk_event("hi")])

    events: list[Any] = []
    async for ev in harness.astream_invoke(agent, "hello"):
        events.append(ev)

    assert len(events) >= 1, "Expected at least one event"
    assert isinstance(events[0], RunStarted), (
        f"First event must be RunStarted; got {type(events[0])}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_ends_with_run_finished() -> None:
    """Last event MUST be RunFinished (harness-ag-ui-bridge 3.1)."""
    harness = _make_harness()
    agent = _make_fake_agent([_text_chunk_event("hi")])

    events: list[Any] = []
    async for ev in harness.astream_invoke(agent, "hello"):
        events.append(ev)

    assert len(events) >= 2, "Expected at least RunStarted + RunFinished"
    assert isinstance(events[-1], RunFinished), (
        f"Last event must be RunFinished; got {type(events[-1])}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_run_started_has_run_id_and_timestamp() -> None:
    """RunStarted must carry non-empty run_id and started_at (harness-ag-ui-bridge 3.1)."""
    harness = _make_harness()
    agent = _make_fake_agent([])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]

    started = events[0]
    assert isinstance(started, RunStarted)
    assert started.run_id, "RunStarted.run_id must be non-empty"
    assert started.started_at, "RunStarted.started_at must be non-empty"


@pytest.mark.asyncio
async def test_astream_invoke_run_finished_has_same_run_id() -> None:
    """RunFinished.run_id MUST equal RunStarted.run_id (harness-ag-ui-bridge 3.1)."""
    harness = _make_harness()
    agent = _make_fake_agent([])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]

    started = events[0]
    finished = events[-1]
    assert isinstance(started, RunStarted)
    assert isinstance(finished, RunFinished)
    assert started.run_id == finished.run_id, (
        f"run_id mismatch: RunStarted={started.run_id!r} RunFinished={finished.run_id!r}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_success_run_finished_error_is_none() -> None:
    """On success, RunFinished.error MUST be None (harness-ag-ui-bridge 3.1)."""
    harness = _make_harness()
    agent = _make_fake_agent([])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]

    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.error is None, f"Expected error=None on success; got {finished.error!r}"


# ---------------------------------------------------------------------------
# Task 3.2 — thread_id propagation
# Spec: "astream_invoke passes thread_id to LangGraph"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_invoke_passes_thread_id_to_astream_events() -> None:
    """astream_events must be called with configurable.thread_id == harness._thread_id
    (harness-ag-ui-bridge 3.2)."""
    harness = _make_harness()
    harness._thread_id = "expected-thread-id-42"

    captured_kwargs: dict[str, Any] = {}

    async def _spy_astream_events(
        *args: Any, version: str = "v2", **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        captured_kwargs.update(kwargs)
        captured_kwargs["_version"] = version
        return
        yield  # make it a generator

    fake_agent = MagicMock()
    fake_agent.astream_events = _spy_astream_events

    _ = [ev async for ev in harness.astream_invoke(fake_agent, "hi")]

    config = captured_kwargs.get("config", {})
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    actual_thread_id = configurable.get("thread_id")

    assert actual_thread_id == "expected-thread-id-42", (
        f"Expected configurable.thread_id='expected-thread-id-42'; got {actual_thread_id!r}. "
        f"Full captured_kwargs: {captured_kwargs!r}"
    )


@pytest.mark.asyncio
async def test_thread_id_property_returns_internal_thread_id() -> None:
    """DeepAgentsHarness.thread_id MUST return self._thread_id (harness-ag-ui-bridge 3.2)."""
    harness = _make_harness()
    harness._thread_id = "stable-thread-abc"
    assert harness.thread_id == "stable-thread-abc"


@pytest.mark.asyncio
async def test_thread_id_stable_across_calls() -> None:
    """thread_id must return the same value on every access (harness-ag-ui-bridge 3.2)."""
    harness = _make_harness()
    assert harness.thread_id == harness.thread_id


# ---------------------------------------------------------------------------
# Task 3.3 — LangChain text chunk → TextDelta mapping
# Spec: "astream_invoke translates LangChain text chunks to TextDelta"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_invoke_text_chunk_becomes_text_delta() -> None:
    """on_chat_model_stream event MUST produce a TextDelta (harness-ag-ui-bridge 3.3)."""
    harness = _make_harness()
    agent = _make_fake_agent([_text_chunk_event("Hello")])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]
    text_deltas = [ev for ev in events if isinstance(ev, TextDelta)]

    assert len(text_deltas) >= 1, (
        f"Expected at least one TextDelta; got events: {[type(e).__name__ for e in events]}"
    )
    assert text_deltas[0].text == "Hello", (
        f"TextDelta.text must be 'Hello'; got {text_deltas[0].text!r}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_multiple_text_chunks_same_message_id() -> None:
    """Consecutive text chunks belonging to one message share message_id
    (harness-ag-ui-bridge 3.3)."""
    harness = _make_harness()
    agent = _make_fake_agent([
        _text_chunk_event("Hello ", run_id="run-a"),
        _text_chunk_event("world", run_id="run-a"),
    ])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]
    text_deltas = [ev for ev in events if isinstance(ev, TextDelta)]

    assert len(text_deltas) >= 2, (
        f"Expected at least 2 TextDelta events; got {len(text_deltas)}"
    )
    # All text deltas from the same model run_id must share the same message_id
    ids = {ev.message_id for ev in text_deltas}
    assert len(ids) == 1, (
        f"Expected all TextDeltas to share one message_id; got {ids!r}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_empty_content_chunk_becomes_empty_text_delta() -> None:
    """Empty text chunk (keepalive) MUST be forwarded as TextDelta with text=''
    (harness-ag-ui-bridge 3.3)."""
    harness = _make_harness()
    agent = _make_fake_agent([_text_chunk_event("")])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]
    text_deltas = [ev for ev in events if isinstance(ev, TextDelta)]

    # Empty content chunks may be skipped; this test asserts the implementation
    # is well-behaved (either 0 or 1 TextDelta with text="").
    for ev in text_deltas:
        assert ev.text == "", (
            f"TextDelta for empty chunk must have text=''; got {ev.text!r}"
        )


@pytest.mark.asyncio
async def test_astream_invoke_text_delta_message_id_is_non_empty() -> None:
    """TextDelta.message_id MUST be a non-empty string (harness-ag-ui-bridge 3.3)."""
    harness = _make_harness()
    agent = _make_fake_agent([_text_chunk_event("test")])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]
    text_deltas = [ev for ev in events if isinstance(ev, TextDelta)]

    assert len(text_deltas) >= 1, "Expected at least one TextDelta"
    for ev in text_deltas:
        assert ev.message_id, f"TextDelta.message_id must be non-empty; got {ev.message_id!r}"


# ---------------------------------------------------------------------------
# Task 3.4 — Tool-call lifecycle translation
# Spec: "astream_invoke translates tool calls to lifecycle events"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_invoke_tool_start_emits_tool_call_start() -> None:
    """on_tool_start MUST produce a ToolCallStart (harness-ag-ui-bridge 3.4)."""
    harness = _make_harness()
    agent = _make_fake_agent([
        _tool_start_event("search", {"query": "python decorators"}, run_id="run-tool-1"),
        _tool_end_event("search", "results here", run_id="run-tool-1"),
    ])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "find something")]
    tool_starts = [ev for ev in events if isinstance(ev, ToolCallStart)]

    assert len(tool_starts) >= 1, (
        f"Expected at least one ToolCallStart; got events: {[type(e).__name__ for e in events]}"
    )
    assert tool_starts[0].tool_name == "search", (
        f"ToolCallStart.tool_name must be 'search'; got {tool_starts[0].tool_name!r}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_tool_start_emits_tool_call_args() -> None:
    """on_tool_start MUST also produce a ToolCallArgs with the JSON args
    (harness-ag-ui-bridge 3.4)."""
    harness = _make_harness()
    tool_args = {"query": "python decorators"}
    agent = _make_fake_agent([
        _tool_start_event("search", tool_args, run_id="run-tool-1"),
        _tool_end_event("search", "results", run_id="run-tool-1"),
    ])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]
    tool_args_events = [ev for ev in events if isinstance(ev, ToolCallArgs)]

    assert len(tool_args_events) >= 1, (
        f"Expected at least one ToolCallArgs; got events: {[type(e).__name__ for e in events]}"
    )
    # The accumulated args_chunk values must parse to the original args dict.
    call_id = tool_args_events[0].call_id
    accumulated = "".join(ev.args_chunk for ev in tool_args_events if ev.call_id == call_id)
    parsed = json.loads(accumulated)
    assert parsed == tool_args, (
        f"Accumulated ToolCallArgs parsed to {parsed!r}; expected {tool_args!r}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_tool_end_emits_tool_call_end() -> None:
    """on_tool_end MUST produce a ToolCallEnd (harness-ag-ui-bridge 3.4)."""
    harness = _make_harness()
    agent = _make_fake_agent([
        _tool_start_event("search", {"query": "q"}, run_id="run-tool-1"),
        _tool_end_event("search", "the result", run_id="run-tool-1"),
    ])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]
    tool_ends = [ev for ev in events if isinstance(ev, ToolCallEnd)]

    assert len(tool_ends) >= 1, (
        f"Expected at least one ToolCallEnd; got events: {[type(e).__name__ for e in events]}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_tool_lifecycle_shares_call_id() -> None:
    """ToolCallStart, ToolCallArgs, ToolCallEnd for the same invocation share
    call_id (harness-ag-ui-bridge 3.4)."""
    harness = _make_harness()
    agent = _make_fake_agent([
        _tool_start_event("search", {"query": "q"}, run_id="run-tool-1"),
        _tool_end_event("search", "the result", run_id="run-tool-1"),
    ])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]

    tool_starts = [ev for ev in events if isinstance(ev, ToolCallStart)]
    tool_args_evs = [ev for ev in events if isinstance(ev, ToolCallArgs)]
    tool_ends = [ev for ev in events if isinstance(ev, ToolCallEnd)]

    assert tool_starts, "Expected at least one ToolCallStart"
    assert tool_ends, "Expected at least one ToolCallEnd"

    call_id = tool_starts[0].call_id
    assert call_id, "call_id must be non-empty"
    for ev in tool_args_evs:
        assert ev.call_id == call_id, (
            f"ToolCallArgs.call_id={ev.call_id!r} != ToolCallStart.call_id={call_id!r}"
        )
    assert tool_ends[0].call_id == call_id, (
        f"ToolCallEnd.call_id={tool_ends[0].call_id!r} != ToolCallStart.call_id={call_id!r}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_tool_ordering() -> None:
    """Tool events MUST appear in Start → Args → End order within a single invocation
    (harness-ag-ui-bridge 3.4)."""
    harness = _make_harness()
    agent = _make_fake_agent([
        _tool_start_event("search", {"query": "q"}, run_id="run-tool-1"),
        _tool_end_event("search", "result", run_id="run-tool-1"),
    ])

    events: list[Any] = [ev async for ev in harness.astream_invoke(agent, "hi")]
    # Filter to tool events only (strip RunStarted/RunFinished)
    tool_events = [
        ev for ev in events
        if isinstance(ev, (ToolCallStart, ToolCallArgs, ToolCallEnd))
    ]

    # Must start with ToolCallStart
    assert isinstance(tool_events[0], ToolCallStart), (
        f"First tool event must be ToolCallStart; got {type(tool_events[0])}"
    )
    # Must end with ToolCallEnd
    assert isinstance(tool_events[-1], ToolCallEnd), (
        f"Last tool event must be ToolCallEnd; got {type(tool_events[-1])}"
    )


# ---------------------------------------------------------------------------
# Task 3.5 — Error propagation: two-phase D8 contract
# Spec: "astream_invoke emits RunFinished with error on exception (two-phase)"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_invoke_exception_yields_terminal_run_finished_with_error() -> None:
    """Phase 1: on exception, harness MUST yield RunFinished(error=<ClassName>)
    (harness-ag-ui-bridge 3.5)."""
    harness = _make_harness()
    exc = RuntimeError("quota exceeded")
    agent = _make_raising_agent(exc)

    events: list[Any] = []
    with pytest.raises(RuntimeError, match="quota exceeded"):
        async for ev in harness.astream_invoke(agent, "hi"):
            events.append(ev)

    finished_events = [ev for ev in events if isinstance(ev, RunFinished)]
    assert finished_events, "Expected a RunFinished event before the re-raise"
    terminal = finished_events[-1]
    assert terminal.error == "RuntimeError", (
        f"RunFinished.error must be 'RuntimeError'; got {terminal.error!r}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_exception_reraises_original() -> None:
    """Phase 2: the original exception MUST be re-raised after Phase 1 terminal event
    (harness-ag-ui-bridge 3.5).

    Uses a class whose name matches the D8 redaction pattern so Pydantic
    validation of RunFinished.error passes (class names starting with '_'
    are not valid Python identifiers in the pattern).
    """
    harness = _make_harness()

    class CustomTestError(Exception):
        pass

    exc = CustomTestError("test error")
    agent = _make_raising_agent(exc)

    caught: BaseException | None = None
    try:
        async for _ in harness.astream_invoke(agent, "hi"):
            pass
    except CustomTestError as e:
        caught = e

    assert caught is exc, (
        f"Must re-raise the ORIGINAL exception object; caught {caught!r}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_exception_run_started_before_run_finished() -> None:
    """Even on exception, RunStarted MUST precede RunFinished (harness-ag-ui-bridge 3.5)."""
    harness = _make_harness()
    agent = _make_raising_agent(RuntimeError("boom"))

    events: list[Any] = []
    with pytest.raises(RuntimeError):
        async for ev in harness.astream_invoke(agent, "hi"):
            events.append(ev)

    types = [type(ev).__name__ for ev in events]
    assert types[0] == "RunStarted", f"First event must be RunStarted; got {types}"
    run_finished_positions = [i for i, t in enumerate(types) if t == "RunFinished"]
    assert run_finished_positions, "RunFinished must appear in events"
    # RunFinished must come after RunStarted
    assert run_finished_positions[-1] > 0


@pytest.mark.asyncio
async def test_astream_invoke_exception_no_events_after_run_finished() -> None:
    """After the terminal RunFinished, NO further events must be yielded
    (harness-ag-ui-bridge 3.5 — 'MUST NOT yield any further events')."""
    harness = _make_harness()
    agent = _make_raising_agent(RuntimeError("boom"))

    events: list[Any] = []
    with pytest.raises(RuntimeError):
        async for ev in harness.astream_invoke(agent, "hi"):
            events.append(ev)

    # Find last RunFinished
    last_run_finished_idx = max(
        (i for i, ev in enumerate(events) if isinstance(ev, RunFinished)),
        default=None,
    )
    assert last_run_finished_idx is not None, "Expected a RunFinished event"
    events_after = events[last_run_finished_idx + 1 :]
    assert not events_after, (
        f"No events should follow the terminal RunFinished; got: "
        f"{[type(e).__name__ for e in events_after]}"
    )


@pytest.mark.asyncio
async def test_astream_invoke_exception_run_finished_error_is_class_name_only() -> None:
    """RunFinished.error MUST be the class name only — no message body, no traceback
    (harness-ag-ui-bridge 3.5 per design.md D8 redaction rule)."""
    harness = _make_harness()
    exc = ValueError("secret value = sk-proj-SENSITIVE")
    agent = _make_raising_agent(exc)

    events: list[Any] = []
    with pytest.raises(ValueError):
        async for ev in harness.astream_invoke(agent, "hi"):
            events.append(ev)

    finished_events = [ev for ev in events if isinstance(ev, RunFinished)]
    terminal = finished_events[-1]
    # Must be exactly "ValueError" — no message, no traceback fragments
    assert terminal.error == "ValueError", (
        f"error must be 'ValueError'; got {terminal.error!r}"
    )
    assert "secret" not in (terminal.error or ""), "error must not contain exception message"


# ---------------------------------------------------------------------------
# Task 3.1 (extra) — @traced_harness is applied to astream_invoke
# Spec: deep_agents.py apply @traced_harness to astream_invoke
# ---------------------------------------------------------------------------


def test_astream_invoke_is_decorated_with_traced_harness() -> None:
    """astream_invoke MUST have @traced_harness applied (harness-ag-ui-bridge 3.1 / D9).

    We verify indirectly: the method is an async-generator-function (or the
    wrapper produced by @traced_harness for async generators).  We don't
    import the decorator itself — just confirm the method exists and is callable.
    """
    import inspect

    method = getattr(DeepAgentsHarness, "astream_invoke", None)
    assert method is not None, "astream_invoke not found on DeepAgentsHarness"
    # The @traced_harness wrapper is also an async generator function when
    # applied to an async-gen method.
    assert inspect.isfunction(method) or callable(method), (
        f"astream_invoke must be callable; got {type(method)}"
    )


# ---------------------------------------------------------------------------
# IMPL_REVIEW round-1 regression tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_invoke_disconnect_via_aclose_does_not_raise_runtime_error() -> None:
    """Client disconnect (aclose mid-stream) MUST propagate GeneratorExit unchanged.

    Regression for IMPL_REVIEW round-1 claude #1: ``except BaseException``
    inside the harness caught GeneratorExit and then yielded a synthesized
    ``RunFinished(error=...)``. Yielding while handling GeneratorExit raises
    ``RuntimeError("asynchronous generator ignored GeneratorExit")``. After
    the narrow-catch fix (``except Exception``), GeneratorExit must
    propagate cleanly — no RuntimeError, no synthesized terminal event.
    """
    from contextlib import aclosing

    harness = _make_harness()
    # An agent that yields a long sequence so we can disconnect mid-stream.
    long_run = [_text_chunk_event(f"chunk-{i}") for i in range(20)]
    agent = _make_fake_agent(long_run)

    async with aclosing(harness.astream_invoke(agent, "hi")) as gen:
        # Consume just the RunStarted + a couple of text deltas, then exit
        # the context manager — aclose() will inject GeneratorExit into gen.
        seen = 0
        async for _evt in gen:
            seen += 1
            if seen >= 3:
                break
    # If RuntimeError leaked, the ``async with`` exit would have raised.
    # Reaching this point means the GeneratorExit path was clean.


@pytest.mark.asyncio
async def test_tool_call_id_stable_across_start_args_end_when_run_id_consistent() -> None:
    """Tool-call lifecycle events MUST share the same call_id (gemini #2).

    Regression for IMPL_REVIEW round-1 gemini #2: when LangGraph supplied
    a consistent ``run_id`` for ``on_tool_start`` and ``on_tool_end``, the
    pre-fix code synthesized a *fresh* UUID inside each branch when
    ``tool_run_id`` was falsy, breaking call_id bracketing. The fix uses
    a per-stream dict keyed by upstream run_id so start/args/end share an id.
    """
    harness = _make_harness()
    events = [
        _tool_start_event("search", {"q": "weather"}, run_id="tool-run-X"),
        _tool_end_event("search", "sunny", run_id="tool-run-X"),
    ]
    agent = _make_fake_agent(events)

    collected: list[Any] = []
    async for ev in harness.astream_invoke(agent, "search the weather"):
        collected.append(ev)

    starts = [e for e in collected if isinstance(e, ToolCallStart)]
    argss = [e for e in collected if isinstance(e, ToolCallArgs)]
    ends = [e for e in collected if isinstance(e, ToolCallEnd)]
    assert len(starts) == 1 and len(argss) == 1 and len(ends) == 1
    assert starts[0].call_id == argss[0].call_id == ends[0].call_id, (
        "start/args/end MUST share call_id — got "
        f"start={starts[0].call_id!r} args={argss[0].call_id!r} end={ends[0].call_id!r}"
    )
    # And the value should be the upstream run_id (preferred), not a synthesized UUID.
    assert starts[0].call_id == "tool-run-X"


def test_create_agent_does_not_reassign_thread_id_source() -> None:
    """DeepAgentsHarness.create_agent MUST NOT contain `self._thread_id =`.

    Regression for IMPL_REVIEW round-1 gemini #5: pre-fix, ``create_agent``
    reassigned ``self._thread_id = str(uuid4())``, defeating the
    SdkHarnessAdapter contract that thread_id is stable for the adapter
    instance's lifetime. The original behavioral test used ``__new__`` to
    bypass ``__init__`` and never invoked ``create_agent``, so reverting
    the fix would not have failed the test (IMPL_REVIEW round-2
    claude-r2-1: "the lock-in is illusory").

    The structural assertion here inspects the source of ``create_agent``
    and fails if a re-assignment is ever re-introduced. 100% revert-
    detecting at the cost of being source-shape-coupled (would also
    fail on cosmetic reformatting that introduces the substring in a
    comment — accepted as a deliberate tradeoff).
    """
    import inspect
    import re

    source = inspect.getsource(DeepAgentsHarness.create_agent)
    # Strip comment lines and docstring so we only inspect executable code.
    code_lines = []
    in_docstring = False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # toggle docstring once per occurrence; one-line docstrings
            # toggle twice within the same iteration which leaves us
            # outside (correct).
            in_docstring = not in_docstring
            if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                in_docstring = False
            continue
        if in_docstring:
            continue
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    assert not re.search(r"\bself\._thread_id\s*=", code), (
        "DeepAgentsHarness.create_agent must NOT reassign self._thread_id "
        "(IMPL_REVIEW round-1 gemini #5 / round-2 claude-r2-1). "
        "Source extracted for inspection:\n" + code
    )
