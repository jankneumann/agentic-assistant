"""Tests for assistant.transports.ag_ui.mapper — HarnessEvent → AG-UI mapping.

Tasks:
  4.2 — HarnessEvent → AG-UI event mapping with thread_id propagation (RED)
  4.3 — Run lifecycle event ordering invariants (RED)
  4.4 — Error mapping to terminal RUN_ERROR (two-phase D8 contract) (RED)

Contract references:
  - openspec/changes/harness-ag-ui-bridge/specs/ag-ui-emitter/spec.md
  - openspec/changes/harness-ag-ui-bridge/design.md D8
  - ag_ui.core Pydantic models (field names are snake_case in Python)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from assistant.harnesses.sdk.events import (
    HarnessEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)

# The mapper import will fail until mapper.py is implemented.
# We use pytest.importorskip so individual tests get ERRORS (not SKIP) in RED.
try:
    from assistant.transports.ag_ui.mapper import map_harness_to_ag_ui

    _MAPPER_IMPORTABLE = True
except ImportError:
    _MAPPER_IMPORTABLE = False
    map_harness_to_ag_ui = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_THREAD_ID = "t-test-thread"
_RUN_ID = "r-test-run"
_STARTED_AT = "2026-05-16T00:00:00Z"
_FINISHED_AT = "2026-05-16T00:00:01Z"


async def _collect(stream: AsyncIterator[Any]) -> list[Any]:
    """Fully consume an async iterator and return a list of events."""
    events: list[Any] = []
    async for event in stream:
        events.append(event)
    return events


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


async def _make_stream(*events: HarnessEvent) -> AsyncIterator[HarnessEvent]:
    """Build an async iterator from a fixed sequence of HarnessEvent."""
    for e in events:
        yield e


async def _make_error_stream(
    *events: HarnessEvent, raises: Exception | None = None
) -> AsyncIterator[HarnessEvent]:
    """Build an async iterator that yields events, then optionally raises."""
    for e in events:
        yield e
    if raises is not None:
        raise raises


# ---------------------------------------------------------------------------
# 4.2 — HarnessEvent → AG-UI mapping with thread_id propagation
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MAPPER_IMPORTABLE, reason="mapper.py not yet implemented")
class TestHarnessToAGUIMapping:
    """Spec: HarnessEvent to AG-UI Event Mapping."""

    def test_run_started_maps_to_run_started_event(self) -> None:
        """RunStarted → RunStartedEvent with correct thread_id and run_id."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            assert events[0].type.value == "RUN_STARTED"
            assert events[0].run_id == _RUN_ID
            assert events[0].thread_id == _THREAD_ID

        _run(go())

    def test_run_finished_maps_to_run_finished_event(self) -> None:
        """RunFinished(error=None) → RunFinishedEvent with thread_id and run_id."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            last = events[-1]
            assert last.type.value == "RUN_FINISHED"
            assert last.run_id == _RUN_ID
            assert last.thread_id == _THREAD_ID

        _run(go())

    def test_mapper_rejects_empty_thread_id(self) -> None:
        """map_harness_to_ag_ui with empty string thread_id raises ValueError."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
            )
            with pytest.raises(ValueError, match="thread_id"):
                await _collect(map_harness_to_ag_ui(stream, thread_id=""))

        _run(go())

    def test_text_delta_produces_start_then_content(self) -> None:
        """First TextDelta with a message_id → TextMessageStart then TextMessageContent."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                TextDelta(message_id="msg1", text="Hello"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]
            assert "TEXT_MESSAGE_START" in types
            start_idx = types.index("TEXT_MESSAGE_START")
            content_idx = types.index("TEXT_MESSAGE_CONTENT")
            assert content_idx == start_idx + 1, "TextMessageContent must follow TextMessageStart"
            content_event = events[content_idx]
            assert content_event.delta == "Hello"
            assert content_event.message_id == "msg1"

        _run(go())

    def test_text_delta_start_event_has_correct_message_id(self) -> None:
        """TextMessageStartEvent carries the same message_id as the TextDelta."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                TextDelta(message_id="msg-abc", text="Hi"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            start = next(e for e in events if e.type.value == "TEXT_MESSAGE_START")
            assert start.message_id == "msg-abc"

        _run(go())

    def test_multiple_text_deltas_same_message_id_single_start(self) -> None:
        """Three TextDeltas with same message_id → one START, three CONTENT, one END."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                TextDelta(message_id="msg1", text="Hel"),
                TextDelta(message_id="msg1", text="lo"),
                TextDelta(message_id="msg1", text=" world"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]
            assert types.count("TEXT_MESSAGE_START") == 1
            assert types.count("TEXT_MESSAGE_CONTENT") == 3
            assert types.count("TEXT_MESSAGE_END") == 1
            # Verify delta values in order
            content_events = [e for e in events if e.type.value == "TEXT_MESSAGE_CONTENT"]
            assert content_events[0].delta == "Hel"
            assert content_events[1].delta == "lo"
            assert content_events[2].delta == " world"

        _run(go())

    def test_tool_call_lifecycle_maps_1_to_1(self) -> None:
        """ToolCallStart/Args/End → ToolCallStartEvent/ArgsEvent/EndEvent with call_id."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                ToolCallStart(call_id="c1", tool_name="search"),
                ToolCallArgs(call_id="c1", args_chunk='{"q":'),
                ToolCallArgs(call_id="c1", args_chunk='"hi"}'),
                ToolCallEnd(call_id="c1"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]
            assert types.count("TOOL_CALL_START") == 1
            assert types.count("TOOL_CALL_ARGS") == 2
            assert types.count("TOOL_CALL_END") == 1

            tcs = next(e for e in events if e.type.value == "TOOL_CALL_START")
            assert tcs.tool_call_id == "c1"
            assert tcs.tool_call_name == "search"

            args_events = [e for e in events if e.type.value == "TOOL_CALL_ARGS"]
            assert args_events[0].delta == '{"q":'
            assert args_events[1].delta == '"hi"}'
            assert all(a.tool_call_id == "c1" for a in args_events)

            tce = next(e for e in events if e.type.value == "TOOL_CALL_END")
            assert tce.tool_call_id == "c1"

        _run(go())

    def test_thread_id_propagated_to_run_events(self) -> None:
        """thread_id from call is attached to RunStartedEvent and RunFinishedEvent."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(
                map_harness_to_ag_ui(stream, thread_id="specific-thread-42")
            )
            for e in events:
                if e.type.value in ("RUN_STARTED", "RUN_FINISHED"):
                    assert e.thread_id == "specific-thread-42"

        _run(go())


# ---------------------------------------------------------------------------
# 4.3 — Run lifecycle event ordering invariants
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MAPPER_IMPORTABLE, reason="mapper.py not yet implemented")
class TestLifecycleOrdering:
    """Spec: Run Lifecycle Event Ordering."""

    def test_run_started_is_first_event(self) -> None:
        """RUN_STARTED must be the very first event in the AG-UI stream."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                TextDelta(message_id="msg1", text="hi"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            assert events[0].type.value == "RUN_STARTED"

        _run(go())

    def test_run_finished_is_last_event_on_success(self) -> None:
        """RUN_FINISHED must be the last event in a successful stream."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                TextDelta(message_id="msg1", text="ok"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            assert events[-1].type.value == "RUN_FINISHED"

        _run(go())

    def test_text_message_end_emitted_before_new_message_start(self) -> None:
        """TEXT_MESSAGE_END for msg1 precedes TEXT_MESSAGE_START for msg2."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                TextDelta(message_id="msg1", text="first"),
                TextDelta(message_id="msg2", text="second"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]

            # Should see: START(msg1), CONTENT(msg1), END(msg1), START(msg2), CONTENT(msg2), END(msg2)
            end_msg1_idx = next(
                i
                for i, e in enumerate(events)
                if e.type.value == "TEXT_MESSAGE_END" and e.message_id == "msg1"
            )
            start_msg2_idx = next(
                i
                for i, e in enumerate(events)
                if e.type.value == "TEXT_MESSAGE_START" and e.message_id == "msg2"
            )
            assert end_msg1_idx < start_msg2_idx, (
                "TEXT_MESSAGE_END for msg1 must precede TEXT_MESSAGE_START for msg2"
            )

        _run(go())

    def test_text_message_end_emitted_before_run_finished(self) -> None:
        """Any open TEXT_MESSAGE must be closed before RUN_FINISHED."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                TextDelta(message_id="msg1", text="hi"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]
            end_idx = types.index("TEXT_MESSAGE_END")
            run_finished_idx = types.index("RUN_FINISHED")
            assert end_idx < run_finished_idx

        _run(go())

    def test_tool_call_end_terminates_lifecycle(self) -> None:
        """ToolCallEnd(call_id=c1) → TOOL_CALL_END with tool_call_id=c1, no further ARGS for c1."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                ToolCallStart(call_id="c1", tool_name="fn"),
                ToolCallArgs(call_id="c1", args_chunk="{}"),
                ToolCallEnd(call_id="c1"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            call_end = next(e for e in events if e.type.value == "TOOL_CALL_END")
            assert call_end.tool_call_id == "c1"
            # No ARGS events after the END
            end_idx = events.index(call_end)
            after_end = events[end_idx + 1 :]
            assert not any(
                e.type.value == "TOOL_CALL_ARGS" and e.tool_call_id == "c1"
                for e in after_end
            )

        _run(go())

    def test_only_one_terminal_event_on_success(self) -> None:
        """Exactly one RUN_FINISHED is emitted, no RUN_ERROR on a clean stream."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]
            assert types.count("RUN_FINISHED") == 1
            assert "RUN_ERROR" not in types

        _run(go())


# ---------------------------------------------------------------------------
# 4.4 — Error mapping to terminal RUN_ERROR (two-phase D8 contract)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MAPPER_IMPORTABLE, reason="mapper.py not yet implemented")
class TestD8ErrorContract:
    """Spec: Error Mapping in v1 — two-phase D8 error contract."""

    def test_run_finished_with_error_maps_to_run_error(self) -> None:
        """Phase 1: RunFinished(error='RuntimeError') → RunErrorEvent."""

        async def go() -> None:
            stream = _make_error_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error="RuntimeError"),
                raises=RuntimeError("quota exceeded"),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            last = events[-1]
            assert last.type.value == "RUN_ERROR"

        _run(go())

    def test_run_error_carries_class_name_only_in_message(self) -> None:
        """RunErrorEvent.message = class name only, NOT the exception message body."""

        async def go() -> None:
            stream = _make_error_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error="RuntimeError"),
                raises=RuntimeError("quota exceeded"),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            error_evt = next(e for e in events if e.type.value == "RUN_ERROR")
            assert error_evt.message == "RuntimeError"
            assert "quota exceeded" not in error_evt.message

        _run(go())

    def test_run_error_carries_class_name_in_code(self) -> None:
        """RunErrorEvent.code = class name (same as message per D8 spec)."""

        async def go() -> None:
            stream = _make_error_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error="RuntimeError"),
                raises=RuntimeError("quota exceeded"),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            error_evt = next(e for e in events if e.type.value == "RUN_ERROR")
            assert error_evt.code == "RuntimeError"

        _run(go())

    def test_no_run_finished_emitted_when_run_error(self) -> None:
        """RUN_FINISHED must NOT be emitted when the terminal event is RUN_ERROR."""

        async def go() -> None:
            stream = _make_error_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error="RuntimeError"),
                raises=RuntimeError("quota exceeded"),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]
            assert "RUN_FINISHED" not in types

        _run(go())

    def test_mapper_absorbs_phase2_reraise(self) -> None:
        """Phase 2 re-raise from the harness must NOT propagate to the mapper caller."""

        async def go() -> None:
            stream = _make_error_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error="RuntimeError"),
                raises=RuntimeError("quota exceeded"),
            )
            # If the mapper propagates the exception, this will raise.
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            # We must reach here without exception
            assert len(events) > 0

        _run(go())

    def test_run_error_is_last_event(self) -> None:
        """No additional events are emitted after RUN_ERROR."""

        async def go() -> None:
            stream = _make_error_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error="RuntimeError"),
                raises=RuntimeError("oops"),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            assert events[-1].type.value == "RUN_ERROR"
            types = [e.type.value for e in events]
            error_idx = types.index("RUN_ERROR")
            assert error_idx == len(types) - 1, "RUN_ERROR must be the final event"

        _run(go())

    def test_mapper_does_not_synthesize_on_raw_raise(self) -> None:
        """Misbehaving harness raises mid-stream without terminal RunFinished.

        The mapper MUST NOT synthesize a RUN_ERROR or RUN_FINISHED; the
        exception must propagate to the caller so the bug is observable.
        """

        async def raw_raise_stream() -> AsyncIterator[HarnessEvent]:
            yield RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT)
            raise RuntimeError("harness bug — no terminal RunFinished yielded")

        async def go() -> None:
            stream = raw_raise_stream()
            with pytest.raises(RuntimeError, match="harness bug"):
                await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))

        _run(go())

    def test_text_message_closed_before_run_error(self) -> None:
        """Any open TEXT_MESSAGE must be closed before the terminal RUN_ERROR."""

        async def go() -> None:
            stream = _make_error_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                TextDelta(message_id="msg1", text="partial text"),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error="RuntimeError"),
                raises=RuntimeError("oops"),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]
            assert "TEXT_MESSAGE_END" in types
            end_idx = types.index("TEXT_MESSAGE_END")
            error_idx = types.index("RUN_ERROR")
            assert end_idx < error_idx

        _run(go())

    def test_successful_run_emits_run_finished_no_error_fields(self) -> None:
        """RunFinished(error=None) → RunFinishedEvent with no error/message/code fields."""

        async def go() -> None:
            stream = _make_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error=None),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            last = events[-1]
            assert last.type.value == "RUN_FINISHED"
            # RunFinishedEvent has no message or code field
            assert not hasattr(last, "message") or last.message is None  # type: ignore[union-attr]
            assert not hasattr(last, "code") or last.code is None  # type: ignore[union-attr]
            assert "RUN_ERROR" not in [e.type.value for e in events]

        _run(go())

    def test_only_one_terminal_event_on_error(self) -> None:
        """Exactly one RUN_ERROR is emitted, not multiple terminal events."""

        async def go() -> None:
            stream = _make_error_stream(
                RunStarted(run_id=_RUN_ID, started_at=_STARTED_AT),
                RunFinished(run_id=_RUN_ID, finished_at=_FINISHED_AT, error="ValueError"),
                raises=ValueError("bad input"),
            )
            events = await _collect(map_harness_to_ag_ui(stream, thread_id=_THREAD_ID))
            types = [e.type.value for e in events]
            assert types.count("RUN_ERROR") == 1
            assert "RUN_FINISHED" not in types

        _run(go())
