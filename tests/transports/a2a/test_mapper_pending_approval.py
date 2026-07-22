"""A2A mapper approval handling (P30): PendingApprovalError maps to a
REAL non-terminal ``input-required`` task state (final stream event,
NO ``failed`` update), while the P13 deny fallback
(ModelCallDeniedError) keeps its observational input-required → failed
sequence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from assistant.a2a.types import (
    TaskState,
    TaskStatusUpdateEvent,
)
from assistant.transports.a2a.mapper import map_harness_to_a2a
from tests.a2a.helpers import error_events


async def _collect(events: list[Any]) -> list[Any]:
    async def _stream() -> AsyncIterator[Any]:
        for event in events:
            yield event

    out: list[Any] = []
    async for mapped in map_harness_to_a2a(
        _stream(), task_id="task-1", context_id="ctx-1"
    ):
        out.append(mapped)
    return out


def _status_states(events: list[Any]) -> list[TaskState]:
    return [
        e.status.state
        for e in events
        if isinstance(e, TaskStatusUpdateEvent)
    ]


async def test_pending_approval_maps_to_final_input_required():
    mapped = await _collect(error_events("PendingApprovalError"))
    states = _status_states(mapped)
    assert states == [TaskState.WORKING, TaskState.INPUT_REQUIRED]
    terminal = mapped[-1]
    assert isinstance(terminal, TaskStatusUpdateEvent)
    assert terminal.status.state is TaskState.INPUT_REQUIRED
    assert terminal.final is True


async def test_pending_approval_never_fails_the_task():
    mapped = await _collect(error_events("PendingApprovalError"))
    assert TaskState.FAILED not in _status_states(mapped)


async def test_pending_approval_message_points_at_the_cli():
    mapped = await _collect(error_events("PendingApprovalError"))
    terminal = mapped[-1]
    assert terminal.status.message is not None
    text = terminal.status.message.parts[0].text
    assert "assistant approvals" in text


async def test_dotted_module_qualifier_matches_leaf_class():
    mapped = await _collect(
        error_events("assistant.core.capabilities.approvals.PendingApprovalError")
    )
    states = _status_states(mapped)
    assert states == [TaskState.WORKING, TaskState.INPUT_REQUIRED]


async def test_deny_fallback_keeps_input_required_then_failed():
    mapped = await _collect(error_events("ModelCallDeniedError"))
    states = _status_states(mapped)
    assert states == [
        TaskState.WORKING,
        TaskState.INPUT_REQUIRED,
        TaskState.FAILED,
    ]
    terminal = mapped[-1]
    assert terminal.status.state is TaskState.FAILED
    assert terminal.final is True


async def test_ordinary_failure_skips_input_required():
    mapped = await _collect(error_events("RuntimeError"))
    states = _status_states(mapped)
    assert TaskState.INPUT_REQUIRED not in states
    assert states[-1] is TaskState.FAILED
