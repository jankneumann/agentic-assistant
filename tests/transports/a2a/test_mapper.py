"""Tests for the HarnessEvent → A2A event mapper.

Spec scenarios: a2a-server (change openspec/changes/a2a-server) —
mapping table, two-phase D8 error contract, input-required bridge.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from assistant.a2a.types import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)
from assistant.harnesses.sdk.events import (
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)
from assistant.transports.a2a.mapper import map_harness_to_a2a
from tests.a2a.helpers import (
    error_events,
    make_run_finished,
    make_run_started,
    simple_events,
    text_events,
)


async def _stream(events: list[Any], raise_after: Exception | None = None):
    for e in events:
        yield e
    if raise_after is not None:
        raise raise_after


async def _collect(
    it: AsyncIterator[Any],
) -> list[Any]:
    return [e async for e in it]


# ---------------------------------------------------------------------------
# Lifecycle mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_maps_working_then_completed():
    events = await _collect(
        map_harness_to_a2a(_stream(simple_events()), task_id="t1", context_id="c1")
    )
    assert len(events) == 2
    assert isinstance(events[0], TaskStatusUpdateEvent)
    assert events[0].status.state is TaskState.WORKING
    assert events[0].final is False
    assert isinstance(events[1], TaskStatusUpdateEvent)
    assert events[1].status.state is TaskState.COMPLETED
    assert events[1].final is True
    assert all(e.task_id == "t1" and e.context_id == "c1" for e in events)


@pytest.mark.asyncio
async def test_text_deltas_map_to_artifact_updates_with_append():
    events = await _collect(
        map_harness_to_a2a(
            _stream(text_events("Hello", " world")),
            task_id="t1",
            context_id="c1",
        )
    )
    artifact_updates = [
        e for e in events if isinstance(e, TaskArtifactUpdateEvent)
    ]
    assert len(artifact_updates) == 2
    first, second = artifact_updates
    assert first.append is None  # opens the artifact
    assert second.append is True  # subsequent chunk appends
    assert first.artifact.artifact_id == second.artifact.artifact_id
    first_part = first.artifact.parts[0]
    second_part = second.artifact.parts[0]
    assert isinstance(first_part, TextPart)
    assert isinstance(second_part, TextPart)
    assert first_part.text == "Hello"
    assert second_part.text == " world"


@pytest.mark.asyncio
async def test_tool_call_events_are_dropped():
    rs = make_run_started()
    events_in = [
        rs,
        ToolCallStart(call_id="c1", tool_name="search"),
        ToolCallArgs(call_id="c1", args_chunk='{"q": "x"}'),
        ToolCallEnd(call_id="c1"),
        make_run_finished(rs.run_id),
    ]
    events = await _collect(
        map_harness_to_a2a(_stream(events_in), task_id="t1", context_id="c1")
    )
    # Only working + completed status updates — no tool leakage.
    assert len(events) == 2
    assert all(isinstance(e, TaskStatusUpdateEvent) for e in events)


# ---------------------------------------------------------------------------
# Two-phase D8 error contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_run_maps_to_final_failed_and_absorbs_phase_two():
    events = await _collect(
        map_harness_to_a2a(
            _stream(error_events("RuntimeError"), raise_after=RuntimeError("boom")),
            task_id="t1",
            context_id="c1",
        )
    )
    terminal = events[-1]
    assert isinstance(terminal, TaskStatusUpdateEvent)
    assert terminal.status.state is TaskState.FAILED
    assert terminal.final is True
    # Class-name-only redaction: message carries the class name, never
    # the exception text.
    assert terminal.status.message is not None
    part = terminal.status.message.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "RuntimeError"
    assert "boom" not in part.text


@pytest.mark.asyncio
async def test_raw_raise_without_terminal_propagates():
    rs = make_run_started()
    with pytest.raises(RuntimeError, match="upstream"):
        await _collect(
            map_harness_to_a2a(
                _stream([rs], raise_after=RuntimeError("upstream")),
                task_id="t1",
                context_id="c1",
            )
        )


# ---------------------------------------------------------------------------
# Input-required approval bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_denial_emits_input_required_before_failed():
    events = await _collect(
        map_harness_to_a2a(
            _stream(
                error_events("ModelCallDeniedError"),
                raise_after=PermissionError("denied"),
            ),
            task_id="t1",
            context_id="c1",
        )
    )
    states = [
        e.status.state
        for e in events
        if isinstance(e, TaskStatusUpdateEvent)
    ]
    assert states == [
        TaskState.WORKING,
        TaskState.INPUT_REQUIRED,
        TaskState.FAILED,
    ]
    input_required = next(
        e
        for e in events
        if isinstance(e, TaskStatusUpdateEvent)
        and e.status.state is TaskState.INPUT_REQUIRED
    )
    assert input_required.final is False
    assert events[-1].final is True


@pytest.mark.asyncio
async def test_approval_denial_matches_dotted_class_names():
    events = await _collect(
        map_harness_to_a2a(
            _stream(error_events("assistant.ModelCallDeniedError")),
            task_id="t1",
            context_id="c1",
        )
    )
    states = [e.status.state for e in events]
    assert TaskState.INPUT_REQUIRED in states


@pytest.mark.asyncio
async def test_non_approval_error_has_no_input_required():
    events = await _collect(
        map_harness_to_a2a(
            _stream(error_events("RuntimeError")),
            task_id="t1",
            context_id="c1",
        )
    )
    states = [e.status.state for e in events]
    assert TaskState.INPUT_REQUIRED not in states


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_task_id_raises():
    with pytest.raises(ValueError):
        await _collect(
            map_harness_to_a2a(_stream([]), task_id="", context_id="c1")
        )


@pytest.mark.asyncio
async def test_empty_context_id_raises():
    with pytest.raises(ValueError):
        await _collect(
            map_harness_to_a2a(_stream([]), task_id="t1", context_id="")
        )
