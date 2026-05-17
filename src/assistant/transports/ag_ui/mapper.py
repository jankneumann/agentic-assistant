"""AG-UI mapper: HarnessEvent async-iterator → AG-UI protocol event async-iterator.

Transport-agnostic; knows nothing about HTTP, SSE, or FastAPI.

Contract: ``map_harness_to_ag_ui(stream, *, thread_id)`` is an async generator
function.  Calling it returns an ``AsyncIterator[AGUIEvent]``.

Import direction (D6): this module imports from:
  - ``assistant.harnesses.sdk.events``  (downward — harness layer)
  - ``assistant.transports.ag_ui.types``  (sibling — same layer)
  - ``ag_ui.core``  (external package, already imported via types)

Nothing in this module may import from ``assistant.web``.

Two-phase D8 error contract
----------------------------
Phase 1: harness yields terminal ``RunFinished(error='<ClassName>')``.
  - Mapper emits one ``RunErrorEvent`` (NOT ``RunFinishedEvent``).
  - ``message`` and ``code`` are both set to the class-name string.

Phase 2: after yielding the terminal event, harness re-raises the original
  exception.  Mapper catches and absorbs it (no further events emitted).

Raw raise (misbehaving harness): if the harness raises WITHOUT first
yielding a terminal ``RunFinished``, the exception propagates to the mapper's
caller unchanged (no synthesis of terminal events).

Message-id bracketing
---------------------
TextDelta events are unbounded deltas.  The mapper brackets them:

  First TextDelta(msg_id=X)  →  TextMessageStart(X) + TextMessageContent(X)
  Subsequent TextDelta(X)    →  TextMessageContent(X)
  TextDelta(msg_id=Y ≠ X)   →  TextMessageEnd(X) + TextMessageStart(Y) + TextMessageContent(Y)
  Before terminal event       →  TextMessageEnd(X)   [closes any open message]
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from assistant.harnesses.sdk.events import (
    HarnessEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)
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


async def map_harness_to_ag_ui(
    stream: AsyncIterator[HarnessEvent],
    *,
    thread_id: str,
) -> AsyncIterator[AGUIEvent]:
    """Map a ``HarnessEvent`` async iterator to an ``AGUIEvent`` async iterator.

    Args:
        stream: Async iterator of ``HarnessEvent`` instances from a harness's
            ``astream_invoke()`` call.
        thread_id: Non-empty AG-UI thread identifier (keyword-only). Passed
            in by the transport layer, typically ``harness.thread_id``.
            Attached to every ``RUN_STARTED`` and ``RUN_FINISHED`` event.

    Yields:
        ``AGUIEvent`` instances in protocol order.

    Raises:
        ValueError: If ``thread_id`` is empty or ``None``.
        Any exception raised by a misbehaving harness that skips the
        terminal ``RunFinished`` event (raw raise without Phase 1 signal).
    """
    if not thread_id:
        raise ValueError("thread_id must be a non-empty string")

    # Track open text-message state for bracketing.
    _open_message_id: str | None = None

    async def _close_message() -> AsyncIterator[AGUIEvent]:
        """Yield TextMessageEnd for the currently-open message, if any."""
        nonlocal _open_message_id
        if _open_message_id is not None:
            yield TextMessageEndEvent(message_id=_open_message_id)
            _open_message_id = None

    # The generator loop.  We use a try/except around the iterator consumption
    # to absorb Phase 2 re-raises (the harness raises AFTER yielding the
    # terminal RunFinished with error).  We track whether we have already
    # emitted a terminal event to know if a subsequent exception is Phase 2.
    terminal_emitted = False

    try:
        async for event in stream:
            if isinstance(event, RunStarted):
                yield RunStartedEvent(thread_id=thread_id, run_id=event.run_id)

            elif isinstance(event, TextDelta):
                if event.message_id != _open_message_id:
                    # Close any previously open message first.
                    async for close_evt in _close_message():
                        yield close_evt
                    # Open new message.
                    _open_message_id = event.message_id
                    yield TextMessageStartEvent(message_id=event.message_id)
                yield TextMessageContentEvent(
                    message_id=event.message_id,
                    delta=event.text,
                )

            elif isinstance(event, ToolCallStart):
                yield ToolCallStartEvent(
                    tool_call_id=event.call_id,
                    tool_call_name=event.tool_name,
                )

            elif isinstance(event, ToolCallArgs):
                yield ToolCallArgsEvent(
                    tool_call_id=event.call_id,
                    delta=event.args_chunk,
                )

            elif isinstance(event, ToolCallEnd):
                yield ToolCallEndEvent(tool_call_id=event.call_id)

            elif isinstance(event, RunFinished):
                # Close any open text message before the terminal event.
                async for close_evt in _close_message():
                    yield close_evt

                if event.error is not None:
                    # Phase 1 of D8 two-phase error contract.
                    terminal_emitted = True
                    yield RunErrorEvent(message=event.error, code=event.error)
                else:
                    # Successful run.
                    terminal_emitted = True
                    yield RunFinishedEvent(thread_id=thread_id, run_id=event.run_id)

    except Exception:
        if terminal_emitted:
            # Phase 2 of D8 contract: absorb the re-raise.  The terminal
            # RunErrorEvent was already yielded in Phase 1; no further events.
            return
        # Misbehaving harness: raised without yielding terminal RunFinished.
        # Propagate so the bug is observable upstream.
        raise
