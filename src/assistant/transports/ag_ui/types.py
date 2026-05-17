"""AG-UI event type aliases — v1 minimal scope re-exports from ag_ui.core.

This module provides a single stable import path for the v1-scoped AG-UI event
types used by the mapper and the web transport layer. It is a thin re-export
shim over the upstream ``ag_ui`` package (``ag-ui-protocol>=0.1,<1.0``).

**v1 scope** (nine event types, per design.md D5 and spec):
  - RUN_STARTED, RUN_FINISHED, RUN_ERROR  (lifecycle)
  - TEXT_MESSAGE_START, TEXT_MESSAGE_CONTENT, TEXT_MESSAGE_END  (assistant text)
  - TOOL_CALL_START, TOOL_CALL_ARGS, TOOL_CALL_END  (tool invocations)

STATE_DELTA, CUSTOM, step events, and all other upstream types are
intentionally **not** re-exported here.

Import direction (D6): ``transports/ag_ui/`` → ``ag_ui.core`` (external).
Nothing in ``harnesses/`` or ``web/`` should import from ``ag_ui.core``
directly; they should use this module or ``assistant.transports.ag_ui``.
"""

from __future__ import annotations

from typing import Union

from ag_ui.core import (
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

__all__ = [
    "AGUIEvent",
    "RunErrorEvent",
    "RunFinishedEvent",
    "RunStartedEvent",
    "TextMessageContentEvent",
    "TextMessageEndEvent",
    "TextMessageStartEvent",
    "ToolCallArgsEvent",
    "ToolCallEndEvent",
    "ToolCallStartEvent",
]

# Stable v1 union alias — callers should annotate return types with AGUIEvent.
# This is a plain Union (not the upstream ag_ui.core.Event which includes all
# out-of-scope types like STATE_DELTA and CUSTOM).
AGUIEvent = Union[
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
]
