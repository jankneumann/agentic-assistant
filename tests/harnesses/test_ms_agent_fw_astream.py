"""Tests for MSAgentFrameworkHarness.astream_invoke (harness-ag-ui-bridge tasks 3b.1-3b.6).

TDD: these tests are written BEFORE the implementation in
``src/assistant/harnesses/sdk/ms_agent_fw.py``. They will fail (RED) until
task 3b.7 implements ``MSAgentFrameworkHarness.astream_invoke``.

Spec scenarios covered:

  3b.1  MSAF astream_invoke calls agent.run with stream=True
  3b.2  MSAF astream_invoke emits RunStarted then RunFinished
  3b.3  MSAF astream_invoke translates text updates to TextDelta
  3b.4  MSAF astream_invoke translates tool calls to lifecycle events
  3b.5  MSAF astream_invoke emits RunFinished with error on exception (two-phase)
  3b.6  MSAF astream_invoke applies @traced_harness (success + exception)

Design references:
  - design.md D8  — two-phase error contract
  - design.md D9  — @traced_harness on astream_invoke
  - design.md D11 — AgentResponseUpdate → HarnessEvent mapping table
  - specs/harness-adapter/spec.md — "MS Agent Framework Streaming Invocation"

Implementation notes:
  - agent_framework has a v1.0.1 namespace-package quirk; harness uses lazy
    imports. Tests mock at the harness call site.
  - AgentResponseUpdate carries text via ``.text`` property (concatenated
    TextContent), and tool calls via ``.contents`` list where each Content
    item has ``.type``, ``.call_id``, ``.name``, ``.arguments``, ``.result``.
  - agent.run(messages, stream=True) returns a ResponseStream (AsyncIterable),
    not a coroutine. The mock must also be iterable, not awaitable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.sdk.events import (
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness
from assistant.telemetry import factory

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _persona() -> PersonaConfig:
    return PersonaConfig(
        name="testpersona",
        display_name="Test",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={
            "ms_agent_framework": {
                "enabled": True,
                "chat_client": "openai",
                "model": "openai:gpt-4o-mini",
            }
        },
        tool_sources={},
        extensions=[],
        extensions_dir=None,  # type: ignore[arg-type]
        raw={},
    )


def _role(name: str = "assistant") -> RoleConfig:
    return RoleConfig(
        name=name,
        display_name=name.replace("_", " ").title(),
        description=f"Test role: {name}",
        prompt="You are a helpful assistant.",
        raw={},
    )


def _harness() -> MSAgentFrameworkHarness:
    """Return a harness with no external dependencies wired."""
    return MSAgentFrameworkHarness(_persona(), _role())


class _FakeUpdate:
    """Minimal AgentResponseUpdate stand-in with configurable content."""

    def __init__(
        self,
        *,
        text: str = "",
        contents: list[Any] | None = None,
        message_id: str | None = None,
    ) -> None:
        self.text = text
        self.contents = contents or []
        self.message_id = message_id


class _FakeContent:
    """Minimal Content stand-in."""

    def __init__(
        self,
        type: str,
        *,
        call_id: str | None = None,
        name: str | None = None,
        arguments: Any = None,
        result: Any = None,
    ) -> None:
        self.type = type
        self.call_id = call_id
        self.name = name
        self.arguments = arguments
        self.result = result


async def _async_iter(*updates: Any) -> AsyncIterator[Any]:
    """Yield items from an async iterator."""
    for item in updates:
        yield item


class SpyProvider:
    """Records every Protocol method call for assertion."""

    name: str = "spy"

    def __init__(self) -> None:
        self.calls: dict[str, list[dict[str, Any]]] = {
            "trace_llm_call": [],
            "trace_delegation": [],
            "trace_tool_call": [],
            "trace_memory_op": [],
            "start_span": [],
            "flush": [],
            "shutdown": [],
            "setup": [],
        }

    def setup(self, app: Any = None) -> None:
        self.calls["setup"].append({"app": app})

    def trace_llm_call(self, **kwargs: Any) -> None:
        self.calls["trace_llm_call"].append(kwargs)

    def trace_delegation(self, **kwargs: Any) -> None:
        self.calls["trace_delegation"].append(kwargs)

    def trace_tool_call(self, **kwargs: Any) -> None:
        self.calls["trace_tool_call"].append(kwargs)

    def trace_memory_op(self, **kwargs: Any) -> None:
        self.calls["trace_memory_op"].append(kwargs)

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> Any:
        from contextlib import contextmanager

        self.calls["start_span"].append({"name": name, "attributes": attributes})

        @contextmanager
        def _cm() -> Any:
            yield None

        return _cm()

    def flush(self) -> None:
        self.calls["flush"].append({})

    def shutdown(self) -> None:
        self.calls["shutdown"].append({})


@pytest.fixture(autouse=True)
def _reset_telemetry() -> None:
    factory._provider = None


@pytest.fixture
def spy() -> SpyProvider:
    return SpyProvider()


def _make_fake_stream(*updates: Any) -> MagicMock:
    """Create a MagicMock that acts as an AsyncIterable yielding updates."""

    async def _aiter(self: Any) -> AsyncIterator[Any]:
        for item in updates:
            yield item

    stream = MagicMock()
    stream.__aiter__ = _aiter
    return stream


def _make_raising_stream(*updates: Any, exc: Exception) -> MagicMock:
    """Create an AsyncIterable that yields updates then raises exc."""

    async def _aiter(self: Any) -> AsyncIterator[Any]:
        for item in updates:
            yield item
        raise exc

    stream = MagicMock()
    stream.__aiter__ = _aiter
    return stream


# ---------------------------------------------------------------------------
# Task 3b.1 — agent.run is called with stream=True
# ---------------------------------------------------------------------------


async def test_astream_invoke_calls_agent_run_with_stream_true() -> None:
    """astream_invoke MUST call agent.run(messages, stream=True)."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream()  # empty stream

    _ = [ev async for ev in h.astream_invoke(agent, "hello")]

    agent.run.assert_called_once()
    _, kwargs = agent.run.call_args
    assert kwargs.get("stream") is True, (
        f"agent.run must be called with stream=True; got kwargs={kwargs!r}"
    )


async def test_astream_invoke_passes_message_as_messages_param() -> None:
    """astream_invoke MUST pass the user message via the messages parameter."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream()

    _ = [ev async for ev in h.astream_invoke(agent, "test message")]

    agent.run.assert_called_once()
    args, kwargs = agent.run.call_args
    # messages can be positional or keyword
    message_val = args[0] if args else kwargs.get("messages")
    assert message_val is not None, "agent.run must receive the user message"
    assert "test message" in str(message_val), (
        f"messages param must include the user text; got {message_val!r}"
    )


# ---------------------------------------------------------------------------
# Task 3b.2 — lifecycle bracketing: RunStarted first, RunFinished last
# ---------------------------------------------------------------------------


async def test_astream_invoke_emits_run_started_first() -> None:
    """First event MUST be RunStarted."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream(_FakeUpdate(text="hi"))

    events = [ev async for ev in h.astream_invoke(agent, "hello")]

    assert len(events) >= 2, f"Expected at least RunStarted + RunFinished; got {events!r}"
    assert isinstance(events[0], RunStarted), (
        f"First event must be RunStarted; got {type(events[0]).__name__}"
    )


async def test_astream_invoke_emits_run_finished_last() -> None:
    """Last event MUST be RunFinished with error=None on success."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream(_FakeUpdate(text="hi"))

    events = [ev async for ev in h.astream_invoke(agent, "hello")]

    assert isinstance(events[-1], RunFinished), (
        f"Last event must be RunFinished; got {type(events[-1]).__name__}"
    )
    assert events[-1].error is None, (
        f"RunFinished.error must be None on success; got {events[-1].error!r}"
    )


async def test_astream_invoke_run_started_has_non_empty_run_id() -> None:
    """RunStarted.run_id MUST be a non-empty string."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream()

    events = [ev async for ev in h.astream_invoke(agent, "hello")]

    run_started = events[0]
    assert isinstance(run_started, RunStarted)
    assert run_started.run_id and len(run_started.run_id) > 0, (
        "RunStarted.run_id must be non-empty"
    )


async def test_astream_invoke_run_finished_has_matching_run_id() -> None:
    """RunFinished.run_id MUST equal RunStarted.run_id."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream()

    events = [ev async for ev in h.astream_invoke(agent, "hello")]

    started = events[0]
    finished = events[-1]
    assert isinstance(started, RunStarted)
    assert isinstance(finished, RunFinished)
    assert started.run_id == finished.run_id, (
        f"RunFinished.run_id ({finished.run_id!r}) must equal "
        f"RunStarted.run_id ({started.run_id!r})"
    )


async def test_astream_invoke_stable_thread_id() -> None:
    """thread_id property MUST return a stable non-empty string across calls."""
    h = _harness()
    tid1 = h.thread_id
    tid2 = h.thread_id
    assert tid1 == tid2, "thread_id must be stable (not regenerated per-access)"
    assert len(tid1) > 0, "thread_id must be non-empty"


# ---------------------------------------------------------------------------
# Task 3b.3 — AgentResponseUpdate → TextDelta mapping
# ---------------------------------------------------------------------------


async def test_astream_invoke_translates_text_update_to_text_delta() -> None:
    """Text content in AgentResponseUpdate MUST yield TextDelta events."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream(
        _FakeUpdate(text="Hello"),
        _FakeUpdate(text=" world"),
    )

    events = [ev async for ev in h.astream_invoke(agent, "hi")]

    text_deltas = [ev for ev in events if isinstance(ev, TextDelta)]
    assert len(text_deltas) >= 1, (
        f"Expected at least 1 TextDelta; got events={[type(e).__name__ for e in events]}"
    )
    combined = "".join(ev.text for ev in text_deltas)
    assert "Hello" in combined and "world" in combined, (
        f"TextDelta events must carry the text chunks; combined={combined!r}"
    )


async def test_astream_invoke_text_delta_message_id_stable() -> None:
    """message_id MUST be stable across consecutive text updates."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream(
        _FakeUpdate(text="chunk1"),
        _FakeUpdate(text="chunk2"),
        _FakeUpdate(text="chunk3"),
    )

    events = [ev async for ev in h.astream_invoke(agent, "hi")]

    text_deltas = [ev for ev in events if isinstance(ev, TextDelta)]
    assert len(text_deltas) >= 2, "Expected multiple TextDelta events"
    message_ids = {ev.message_id for ev in text_deltas}
    assert len(message_ids) == 1, (
        f"All TextDelta events in one message must share the same message_id; "
        f"got {message_ids!r}"
    )


async def test_astream_invoke_skips_empty_text_updates() -> None:
    """Updates with empty text MUST NOT produce TextDelta events (no keepalive spam)."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream(
        _FakeUpdate(text=""),  # no text, no tool call — skip
        _FakeUpdate(text="real"),
    )

    events = [ev async for ev in h.astream_invoke(agent, "hi")]

    text_deltas = [ev for ev in events if isinstance(ev, TextDelta)]
    # Only the "real" update should produce a TextDelta
    assert all(ev.text != "" for ev in text_deltas), (
        f"Empty text updates must not produce TextDelta; got {text_deltas!r}"
    )


# ---------------------------------------------------------------------------
# Task 3b.4 — MSAF tool-call lifecycle translation
# ---------------------------------------------------------------------------


async def test_astream_invoke_translates_function_call_start() -> None:
    """An update with a function_call Content MUST yield ToolCallStart."""
    h = _harness()
    agent = MagicMock()
    tool_start_update = _FakeUpdate(
        contents=[
            _FakeContent(
                "function_call",
                call_id="c-1",
                name="search",
                arguments='{"q": "decorators"}',
            )
        ]
    )
    agent.run.return_value = _make_fake_stream(tool_start_update)

    events = [ev async for ev in h.astream_invoke(agent, "hi")]

    starts = [ev for ev in events if isinstance(ev, ToolCallStart)]
    assert len(starts) >= 1, (
        f"Expected ToolCallStart for function_call content; "
        f"got {[type(e).__name__ for e in events]}"
    )
    assert starts[0].tool_name == "search", (
        f"ToolCallStart.tool_name must be 'search'; got {starts[0].tool_name!r}"
    )
    assert starts[0].call_id == "c-1", (
        f"ToolCallStart.call_id must be 'c-1'; got {starts[0].call_id!r}"
    )


async def test_astream_invoke_emits_tool_call_args_for_function_call() -> None:
    """A function_call Content with arguments MUST yield at least one ToolCallArgs."""
    h = _harness()
    agent = MagicMock()
    tool_update = _FakeUpdate(
        contents=[
            _FakeContent(
                "function_call",
                call_id="c-2",
                name="search",
                arguments='{"q": "python"}',
            )
        ]
    )
    agent.run.return_value = _make_fake_stream(tool_update)

    events = [ev async for ev in h.astream_invoke(agent, "hi")]

    args_events = [ev for ev in events if isinstance(ev, ToolCallArgs) and ev.call_id == "c-2"]
    assert len(args_events) >= 1, (
        f"Expected ToolCallArgs for call_id='c-2'; "
        f"got {[type(e).__name__ for e in events]}"
    )
    combined_args = "".join(ev.args_chunk for ev in args_events)
    assert "python" in combined_args, (
        f"ToolCallArgs must carry arguments; combined={combined_args!r}"
    )


async def test_astream_invoke_emits_tool_call_end_for_function_result() -> None:
    """A function_result Content MUST yield ToolCallEnd."""
    h = _harness()
    agent = MagicMock()
    result_update = _FakeUpdate(
        contents=[
            _FakeContent(
                "function_result",
                call_id="c-3",
                result="found it",
            )
        ]
    )
    agent.run.return_value = _make_fake_stream(result_update)

    events = [ev async for ev in h.astream_invoke(agent, "hi")]

    ends = [ev for ev in events if isinstance(ev, ToolCallEnd) and ev.call_id == "c-3"]
    assert len(ends) >= 1, (
        f"Expected ToolCallEnd for call_id='c-3'; "
        f"got {[type(e).__name__ for e in events]}"
    )


async def test_astream_invoke_tool_call_lifecycle_shared_call_id() -> None:
    """ToolCallStart, ToolCallArgs, ToolCallEnd MUST share the same call_id."""
    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream(
        _FakeUpdate(
            contents=[
                _FakeContent(
                    "function_call",
                    call_id="c-shared",
                    name="calc",
                    arguments='{"x": 1}',
                )
            ]
        ),
        _FakeUpdate(
            contents=[
                _FakeContent(
                    "function_result",
                    call_id="c-shared",
                    result=42,
                )
            ]
        ),
    )

    events = [ev async for ev in h.astream_invoke(agent, "hi")]

    tool_events = [
        ev
        for ev in events
        if isinstance(ev, (ToolCallStart, ToolCallArgs, ToolCallEnd))
    ]
    call_ids = {ev.call_id for ev in tool_events}
    assert "c-shared" in call_ids, (
        f"All tool-call events must carry call_id='c-shared'; "
        f"got call_ids={call_ids!r}"
    )


# ---------------------------------------------------------------------------
# Task 3b.5 — error propagation (two-phase D8 contract)
# ---------------------------------------------------------------------------


async def test_astream_invoke_emits_run_finished_with_error_on_exception() -> None:
    """Phase 1: a terminal RunFinished(error=<ClassName>) MUST be yielded before re-raise."""
    h = _harness()
    agent = MagicMock()
    exc = RuntimeError("quota exceeded")
    agent.run.return_value = _make_raising_stream(
        _FakeUpdate(text="partial"),
        exc=exc,
    )

    events = []
    with pytest.raises(RuntimeError, match="quota exceeded"):
        async for ev in h.astream_invoke(agent, "hi"):
            events.append(ev)

    terminal = [ev for ev in events if isinstance(ev, RunFinished)]
    assert len(terminal) == 1, (
        f"Expected exactly one RunFinished on error; got {terminal!r}"
    )
    assert terminal[0].error == "RuntimeError", (
        f"RunFinished.error must be the class name 'RuntimeError'; "
        f"got {terminal[0].error!r}"
    )


async def test_astream_invoke_reraises_original_exception() -> None:
    """Phase 2: the original exception MUST be re-raised after the terminal event."""
    h = _harness()
    agent = MagicMock()
    original = RuntimeError("original error")
    agent.run.return_value = _make_raising_stream(exc=original)

    with pytest.raises(RuntimeError) as exc_info:
        async for _ in h.astream_invoke(agent, "hi"):
            pass

    assert exc_info.value is original, (
        "The re-raised exception must be the same object as the original"
    )


async def test_astream_invoke_no_events_after_terminal_run_finished() -> None:
    """No events MUST be emitted after the terminal RunFinished on error."""
    h = _harness()
    agent = MagicMock()
    exc = ValueError("bad input")
    agent.run.return_value = _make_raising_stream(exc=exc)

    events = []
    with pytest.raises(ValueError):
        async for ev in h.astream_invoke(agent, "hi"):
            events.append(ev)

    # Find the index of the terminal RunFinished
    terminal_idxs = [i for i, ev in enumerate(events) if isinstance(ev, RunFinished)]
    assert terminal_idxs, "Must emit a RunFinished on error"
    last_terminal_idx = terminal_idxs[-1]
    assert last_terminal_idx == len(events) - 1, (
        f"RunFinished must be the LAST collected event; "
        f"events after it: {events[last_terminal_idx + 1:]!r}"
    )


async def test_astream_invoke_error_field_is_class_name_only() -> None:
    """RunFinished.error MUST be the class name only, not the message body."""
    h = _harness()
    agent = MagicMock()
    exc = PermissionError("access denied to secret key: sk-abc123")
    agent.run.return_value = _make_raising_stream(exc=exc)

    events = []
    with pytest.raises(PermissionError):
        async for ev in h.astream_invoke(agent, "hi"):
            events.append(ev)

    terminal = next(ev for ev in events if isinstance(ev, RunFinished))
    assert terminal.error == "PermissionError", (
        f"error field must be class name only; got {terminal.error!r}"
    )
    assert "secret" not in (terminal.error or ""), "error must not leak message body"
    assert "sk-abc123" not in (terminal.error or ""), "error must not leak sensitive content"


# ---------------------------------------------------------------------------
# Task 3b.6 — @traced_harness applied (success + exception)
# ---------------------------------------------------------------------------


async def test_traced_harness_emits_trace_on_success(
    spy: SpyProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """@traced_harness MUST emit exactly one trace_llm_call with streaming=True on success."""
    monkeypatch.setattr(factory, "_provider", spy)

    h = _harness()
    agent = MagicMock()
    agent.run.return_value = _make_fake_stream(_FakeUpdate(text="hello"))

    _ = [ev async for ev in h.astream_invoke(agent, "hi")]

    calls = spy.calls["trace_llm_call"]
    assert len(calls) == 1, f"Expected exactly 1 trace_llm_call on success; got {len(calls)}"
    call = calls[0]
    assert isinstance(call.get("metadata"), dict), (
        f"metadata must be a dict; got {call.get('metadata')!r}"
    )
    assert call["metadata"].get("streaming") is True, (
        f"metadata must include streaming=True; got {call['metadata']!r}"
    )
    # Must include model / persona / role
    assert call.get("model") is not None, "trace must include model field"
    assert isinstance(call.get("duration_ms"), float), "trace must include duration_ms"


async def test_traced_harness_emits_trace_on_exception(
    spy: SpyProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """@traced_harness MUST emit trace with streaming=True + error on exception."""
    monkeypatch.setattr(factory, "_provider", spy)

    h = _harness()
    agent = MagicMock()
    exc = RuntimeError("quota exceeded")
    agent.run.return_value = _make_raising_stream(exc=exc)

    with pytest.raises(RuntimeError):
        async for _ in h.astream_invoke(agent, "hi"):
            pass

    calls = spy.calls["trace_llm_call"]
    assert len(calls) == 1, f"Expected exactly 1 trace_llm_call on exception; got {len(calls)}"
    call = calls[0]
    assert isinstance(call.get("metadata"), dict), (
        f"metadata must be a dict on exception; got {call.get('metadata')!r}"
    )
    assert call["metadata"].get("streaming") is True, (
        f"metadata must include streaming=True on exception; got {call['metadata']!r}"
    )
    assert call["metadata"].get("error") == "RuntimeError", (
        f"metadata must include error=RuntimeError on exception; got {call['metadata']!r}"
    )


async def test_traced_harness_emits_trace_exactly_once_per_invocation(
    spy: SpyProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """@traced_harness must NOT emit one trace per yielded event."""
    monkeypatch.setattr(factory, "_provider", spy)

    h = _harness()
    agent = MagicMock()
    # Many updates — should still produce exactly 1 trace
    agent.run.return_value = _make_fake_stream(
        _FakeUpdate(text="a"),
        _FakeUpdate(text="b"),
        _FakeUpdate(text="c"),
    )

    _ = [ev async for ev in h.astream_invoke(agent, "hi")]

    calls = spy.calls["trace_llm_call"]
    assert len(calls) == 1, (
        f"Must emit exactly 1 trace_llm_call regardless of event count; got {len(calls)}"
    )


async def test_traced_harness_reraises_exception_after_trace(
    spy: SpyProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The original exception must propagate AFTER the trace is emitted."""
    monkeypatch.setattr(factory, "_provider", spy)

    h = _harness()
    original = RuntimeError("original")
    agent = MagicMock()
    agent.run.return_value = _make_raising_stream(exc=original)

    with pytest.raises(RuntimeError) as exc_info:
        async for _ in h.astream_invoke(agent, "hi"):
            pass

    assert exc_info.value is original, "Must re-raise the exact original exception"
    # Trace must have been emitted
    assert len(spy.calls["trace_llm_call"]) == 1, "Trace must be emitted even on exception"


# ---------------------------------------------------------------------------
# IMPL_REVIEW round-2 regression — parallel missing-id orphan tool calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_invoke_parallel_missing_id_orphans_bracket_via_fifo() -> None:
    """Parallel missing-id tool calls MUST bracket via the FIFO deque.

    Regression for IMPL_REVIEW round-2 cross-vendor (claude-r2-2 + codex-r2-1):
    pre-fix, ms_agent_fw.py used a single ``pending_orphan_call_id`` slot —
    when the SDK emitted two missing-id function_call items before any
    function_result, the second start overwrote the slot, so the *first*
    function_result paired with the *second* start's synthesized UUID, and
    the second function_result fell through to a fresh UUID. Both calls
    ended up mis-bracketed. After the fix the slot is a ``deque[str]``
    with FIFO semantics: the oldest unpaired start matches the next
    missing-id result.
    """
    h = _harness()
    agent = MagicMock()
    # Two missing-id starts (call_id=None), then two missing-id results.
    # No SDK-provided call_id on any of these four items.
    agent.run.return_value = _make_fake_stream(
        _FakeUpdate(
            contents=[
                _FakeContent("function_call", name="search", call_id=None),
            ]
        ),
        _FakeUpdate(
            contents=[
                _FakeContent("function_call", name="weather", call_id=None),
            ]
        ),
        _FakeUpdate(
            contents=[
                _FakeContent("function_result", call_id=None, result="result-A"),
            ]
        ),
        _FakeUpdate(
            contents=[
                _FakeContent("function_result", call_id=None, result="result-B"),
            ]
        ),
    )

    events = [ev async for ev in h.astream_invoke(agent, "hi")]
    starts = [e for e in events if isinstance(e, ToolCallStart)]
    ends = [e for e in events if isinstance(e, ToolCallEnd)]
    assert len(starts) == 2 and len(ends) == 2, (
        f"Expected 2 starts + 2 ends; got starts={len(starts)}, ends={len(ends)}"
    )
    # FIFO contract: ends[0].call_id == starts[0].call_id (oldest start),
    #                ends[1].call_id == starts[1].call_id (newer start).
    assert ends[0].call_id == starts[0].call_id, (
        "First result must pair with the oldest unmatched start "
        f"(FIFO). Got starts={[s.call_id for s in starts]}, "
        f"ends={[e.call_id for e in ends]}"
    )
    assert ends[1].call_id == starts[1].call_id, (
        "Second result must pair with the next-oldest unmatched start "
        f"(FIFO). Got starts={[s.call_id for s in starts]}, "
        f"ends={[e.call_id for e in ends]}"
    )
    # And the two pairs MUST be distinct from each other.
    assert starts[0].call_id != starts[1].call_id, (
        "Each missing-id start must synthesize a unique UUID"
    )
