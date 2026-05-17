"""Tests for HarnessEvent discriminated union (harness-ag-ui-bridge task 1.2).

TDD: these tests are written BEFORE the implementation in
``src/assistant/harnesses/sdk/events.py``. They will fail at collection
until task 1.3 is complete — collection ImportError is acceptable for
a RED test-only commit per the TDD ordering instructions.

Contract source: openspec/changes/harness-ag-ui-bridge/contracts/events/harness-event.schema.json
Spec scenarios:
  - "HarnessEvent variants are exhaustive for v1"
  - "RunStarted carries an opaque run identifier"
  - "TextDelta carries partial text chunks"
  - "Tool call lifecycle events share a call_id"
  - "RunFinished.error field is class-name-only when populated"
"""

from __future__ import annotations

import re

import pytest
from pydantic import TypeAdapter, ValidationError

# Collection-time import — will ImportError until task 1.3 creates events.py.
from assistant.harnesses.sdk.events import (
    HarnessEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLASS_NAME_RE = re.compile(
    r"^(?:[a-z_][a-zA-Z0-9_]*\.)*[A-Z][A-Za-z0-9_]*$"
)

# ---------------------------------------------------------------------------
# Scenario: HarnessEvent variants are exhaustive for v1
# ---------------------------------------------------------------------------


def test_harness_event_six_variants() -> None:
    """Exactly six variant classes must be present in the union."""
    import assistant.harnesses.sdk.events as events_mod

    for name in (
        "RunStarted",
        "RunFinished",
        "TextDelta",
        "ToolCallStart",
        "ToolCallArgs",
        "ToolCallEnd",
    ):
        assert hasattr(events_mod, name), f"Variant class {name!r} not found in events module"


def test_harness_event_union_exists() -> None:
    """HarnessEvent must be importable from assistant.harnesses.sdk.events."""
    import assistant.harnesses.sdk.events as events_mod

    assert hasattr(events_mod, "HarnessEvent"), "HarnessEvent not defined"


# ---------------------------------------------------------------------------
# Scenario: RunStarted carries an opaque run identifier
# ---------------------------------------------------------------------------


def test_run_started_fields() -> None:
    ev = RunStarted(run_id="r-001", started_at="2026-05-16T09:00:00Z")
    assert ev.kind == "run_started"
    assert ev.run_id == "r-001"
    assert ev.started_at == "2026-05-16T09:00:00Z"


def test_run_started_requires_run_id() -> None:
    # Pydantic raises ValidationError when required field is omitted
    with pytest.raises((ValidationError, TypeError)):
        RunStarted.model_validate({"started_at": "2026-05-16T09:00:00Z"})


def test_run_started_requires_started_at() -> None:
    # Pydantic raises ValidationError when required field is omitted
    with pytest.raises((ValidationError, TypeError)):
        RunStarted.model_validate({"run_id": "r-001"})


def test_run_started_discriminator_is_run_started() -> None:
    ev = RunStarted(run_id="r-001", started_at="2026-05-16T09:00:00Z")
    assert ev.kind == "run_started"


# ---------------------------------------------------------------------------
# Scenario: RunFinished — success and error paths
# ---------------------------------------------------------------------------


def test_run_finished_success() -> None:
    ev = RunFinished(run_id="r-001", finished_at="2026-05-16T09:00:02Z", error=None)
    assert ev.kind == "run_finished"
    assert ev.error is None


def test_run_finished_error_class_name() -> None:
    ev = RunFinished(run_id="r-001", finished_at="2026-05-16T09:00:02Z", error="RuntimeError")
    assert ev.error == "RuntimeError"
    assert _CLASS_NAME_RE.match(ev.error), f"error {ev.error!r} does not match pattern"


def test_run_finished_error_dotted_module() -> None:
    ev = RunFinished(
        run_id="r-001",
        finished_at="2026-05-16T09:00:02Z",
        error="asyncio.CancelledError",
    )
    assert ev.error == "asyncio.CancelledError"
    assert _CLASS_NAME_RE.match(ev.error)


def test_run_finished_error_invalid_pattern_rejected() -> None:
    """error must match class-name-only pattern — raw message text is rejected."""
    with pytest.raises(ValidationError):
        RunFinished(
            run_id="r-001",
            finished_at="2026-05-16T09:00:02Z",
            error="quota exceeded",  # message body — not a class name
        )


def test_run_finished_error_defaults_none() -> None:
    ev = RunFinished(run_id="r-001", finished_at="2026-05-16T09:00:02Z")
    assert ev.error is None


# ---------------------------------------------------------------------------
# Scenario: TextDelta carries partial text chunks
# ---------------------------------------------------------------------------


def test_text_delta_fields() -> None:
    ev = TextDelta(message_id="m-001", text="Decorators are ")
    assert ev.kind == "text_delta"
    assert ev.message_id == "m-001"
    assert ev.text == "Decorators are "


def test_text_delta_text_may_be_empty() -> None:
    ev = TextDelta(message_id="m-001", text="")
    assert ev.text == ""


def test_text_delta_requires_message_id() -> None:
    with pytest.raises((ValidationError, TypeError)):
        TextDelta.model_validate({"text": "hello"})


# ---------------------------------------------------------------------------
# Scenario: Tool call lifecycle events share a call_id
# ---------------------------------------------------------------------------


def test_tool_call_start_fields() -> None:
    ev = ToolCallStart(call_id="c-001", tool_name="search")
    assert ev.kind == "tool_call_start"
    assert ev.call_id == "c-001"
    assert ev.tool_name == "search"


def test_tool_call_args_fields() -> None:
    ev = ToolCallArgs(call_id="c-001", args_chunk='{"q":"py')
    assert ev.kind == "tool_call_args"
    assert ev.call_id == "c-001"
    assert ev.args_chunk == '{"q":"py'


def test_tool_call_end_fields() -> None:
    ev = ToolCallEnd(call_id="c-001")
    assert ev.kind == "tool_call_end"
    assert ev.call_id == "c-001"


def test_tool_call_end_optional_result() -> None:
    ev = ToolCallEnd(call_id="c-001", result=[{"title": "Python decorators"}])
    assert ev.result == [{"title": "Python decorators"}]


def test_tool_call_lifecycle_shared_call_id() -> None:
    """ToolCallStart, ToolCallArgs, ToolCallEnd must all share the same call_id."""
    call_id = "c1"
    start = ToolCallStart(call_id=call_id, tool_name="search")
    args = ToolCallArgs(call_id=call_id, args_chunk='{"q":"decorators"}')
    end = ToolCallEnd(call_id=call_id)

    assert start.call_id == args.call_id == end.call_id == call_id


# ---------------------------------------------------------------------------
# Scenario: discriminated union TypeAdapter dispatch
# ---------------------------------------------------------------------------


def test_harness_event_discriminated_union_parse() -> None:
    """TypeAdapter(HarnessEvent) dispatches on 'kind' field."""
    adapter: TypeAdapter[HarnessEvent] = TypeAdapter(HarnessEvent)
    ev = adapter.validate_python(
        {"kind": "run_started", "run_id": "r-001", "started_at": "2026-05-16T09:00:00Z"}
    )
    assert isinstance(ev, RunStarted)


def test_harness_event_union_text_delta_parse() -> None:
    adapter: TypeAdapter[HarnessEvent] = TypeAdapter(HarnessEvent)
    ev = adapter.validate_python({"kind": "text_delta", "message_id": "m-1", "text": "hi"})
    assert isinstance(ev, TextDelta)


def test_harness_event_union_run_finished_error_parse() -> None:
    adapter: TypeAdapter[HarnessEvent] = TypeAdapter(HarnessEvent)
    ev = adapter.validate_python(
        {
            "kind": "run_finished",
            "run_id": "r-001",
            "finished_at": "2026-05-16T09:00:02Z",
            "error": "RuntimeError",
        }
    )
    assert isinstance(ev, RunFinished)
    assert ev.error == "RuntimeError"


def test_harness_event_union_rejects_unknown_kind() -> None:
    adapter: TypeAdapter[HarnessEvent] = TypeAdapter(HarnessEvent)
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "unknown_variant"})


def test_harness_event_union_tool_call_end_parse() -> None:
    """Verify ToolCallEnd uses kind='tool_call_end' (not 'tool_call_id')."""
    adapter: TypeAdapter[HarnessEvent] = TypeAdapter(HarnessEvent)
    ev = adapter.validate_python({"kind": "tool_call_end", "call_id": "c-001"})
    assert isinstance(ev, ToolCallEnd)
