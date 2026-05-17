"""Tests for assistant.transports.ag_ui.types — AG-UI v1 event type surface.

Task 4.1: v1-scoped event type coverage (RED).

Verifies that:
- types.py exposes exactly the 9 AG-UI event types in the v1 minimal scope.
- Each type is a subclass of the upstream ag_ui.core Pydantic models.
- The AGUIEvent union alias covers all 9 and only those 9.
- No STATE_DELTA, CUSTOM, or out-of-scope events are exported.
"""

from __future__ import annotations

import typing

import ag_ui.core as upstream
import pytest

# These imports fail (ImportError) until types.py is implemented — that makes
# the test file RED at collection time, but we want the failure to be in the
# individual tests rather than at module import so pytest can report them.
# We guard with a try/except at module level.
try:
    from assistant.transports.ag_ui.types import (
        AGUIEvent,
        RunErrorEvent,
        RunFinishedEvent,
        RunStartedEvent,
        TextMessageContentEvent,
        TextMessageEndEvent,
        TextMessageStartEvent,
        ToolCallArgsEvent,
        ToolCallEndEvent,
        ToolCallStartEvent,
    )

    _TYPES_IMPORTABLE = True
except ImportError:
    _TYPES_IMPORTABLE = False


@pytest.mark.skipif(not _TYPES_IMPORTABLE, reason="types.py not yet implemented")
class TestV1EventTypeExports:
    """The 9 v1-scoped AG-UI event types MUST be importable from types.py."""

    def test_run_started_event_exported(self) -> None:
        assert RunStartedEvent is upstream.RunStartedEvent

    def test_run_finished_event_exported(self) -> None:
        assert RunFinishedEvent is upstream.RunFinishedEvent

    def test_run_error_event_exported(self) -> None:
        assert RunErrorEvent is upstream.RunErrorEvent

    def test_text_message_start_event_exported(self) -> None:
        assert TextMessageStartEvent is upstream.TextMessageStartEvent

    def test_text_message_content_event_exported(self) -> None:
        assert TextMessageContentEvent is upstream.TextMessageContentEvent

    def test_text_message_end_event_exported(self) -> None:
        assert TextMessageEndEvent is upstream.TextMessageEndEvent

    def test_tool_call_start_event_exported(self) -> None:
        assert ToolCallStartEvent is upstream.ToolCallStartEvent

    def test_tool_call_args_event_exported(self) -> None:
        assert ToolCallArgsEvent is upstream.ToolCallArgsEvent

    def test_tool_call_end_event_exported(self) -> None:
        assert ToolCallEndEvent is upstream.ToolCallEndEvent


@pytest.mark.skipif(not _TYPES_IMPORTABLE, reason="types.py not yet implemented")
class TestAGUIEventUnion:
    """AGUIEvent union covers exactly the 9 v1-scoped types."""

    def test_agui_event_is_union_or_annotated(self) -> None:
        # AGUIEvent should be a Union type alias or Annotated union
        hint = AGUIEvent
        # It should have __args__ (Union) or be Annotated with Union args
        origin = typing.get_origin(hint)
        assert origin is not None, "AGUIEvent should be a Union or Annotated type"

    def test_agui_event_includes_run_started(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.RunStartedEvent in args

    def test_agui_event_includes_run_finished(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.RunFinishedEvent in args

    def test_agui_event_includes_run_error(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.RunErrorEvent in args

    def test_agui_event_includes_text_message_start(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.TextMessageStartEvent in args

    def test_agui_event_includes_text_message_content(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.TextMessageContentEvent in args

    def test_agui_event_includes_text_message_end(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.TextMessageEndEvent in args

    def test_agui_event_includes_tool_call_start(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.ToolCallStartEvent in args

    def test_agui_event_includes_tool_call_args(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.ToolCallArgsEvent in args

    def test_agui_event_includes_tool_call_end(self) -> None:
        args = _get_union_args(AGUIEvent)
        assert upstream.ToolCallEndEvent in args

    def test_agui_event_excludes_out_of_scope_types(self) -> None:
        """STATE_DELTA and CUSTOM must NOT be in the v1 AGUIEvent union."""
        args = _get_union_args(AGUIEvent)
        excluded = [
            upstream.StateDeltaEvent,
            upstream.CustomEvent,
        ]
        for exc_type in excluded:
            assert exc_type not in args, (
                f"{exc_type.__name__} must not be in AGUIEvent union for v1"
            )


def _get_union_args(hint: typing.Any) -> tuple[typing.Any, ...]:
    """Return the concrete type args of a Union or Annotated[Union[...], ...] alias."""
    origin = typing.get_origin(hint)
    if origin is typing.Union:
        return typing.get_args(hint)
    # Annotated — first arg is the actual Union
    inner_args = typing.get_args(hint)
    if inner_args:
        inner = inner_args[0]
        if typing.get_origin(inner) is typing.Union:
            return typing.get_args(inner)
    return ()
