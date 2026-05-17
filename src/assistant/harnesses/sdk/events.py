"""HarnessEvent discriminated union — harness-agnostic streaming event types.

All six variants are Pydantic v2 BaseModel subclasses using ``kind`` as the
discriminator field. Field names are intentionally harness-agnostic (no
LangChain terminology) and protocol-agnostic (no AG-UI terminology) per D1.

Module location: ``harnesses/sdk/events.py`` — in the harness layer so that
concrete harnesses can construct events inside ``astream_invoke()`` without
importing upward into the transport layer. The transports layer imports
``HarnessEvent`` from here (downward direction) per D6.

Contract: openspec/changes/harness-ag-ui-bridge/contracts/events/harness-event.schema.json
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# The class-name-only pattern from D8 / harness-event.schema.json:
# Matches a Python class identifier with optional dotted module qualifier —
# lowercase or underscore-leading module segments followed by an uppercase-
# leading class name.  Examples: RuntimeError, asyncio.CancelledError,
# agent_framework.QuotaError
_CLASS_NAME_PATTERN = r"^(?:[a-z_][a-zA-Z0-9_]*\.)*[A-Z][A-Za-z0-9_]*$"


class RunStarted(BaseModel):
    """Marks the beginning of a harness invocation.

    MUST be the first event in any stream.
    """

    kind: Literal["run_started"] = "run_started"
    run_id: str = Field(..., min_length=1, description="Opaque run identifier, unique per run.")
    started_at: str = Field(..., description="ISO 8601 UTC timestamp.")


class RunFinished(BaseModel):
    """Marks the end of a harness invocation.

    MUST be the last event. If ``error`` is non-null, the run failed
    (Phase 1 of the D8 two-phase error contract).
    """

    kind: Literal["run_finished"] = "run_finished"
    run_id: str = Field(..., min_length=1)
    finished_at: str = Field(..., description="ISO 8601 UTC timestamp.")
    error: str | None = Field(
        default=None,
        pattern=_CLASS_NAME_PATTERN,
        description=(
            "Exception class name only on failure (per D8 redaction rule). "
            "Null on success. MUST NOT contain the exception message body, "
            "traceback, or any nested-exception detail."
        ),
    )


class TextDelta(BaseModel):
    """A partial chunk of an assistant text message.

    Multiple ``TextDelta`` events with the same ``message_id`` concatenate
    into one logical assistant message.
    """

    kind: Literal["text_delta"] = "text_delta"
    message_id: str = Field(..., min_length=1, description="Stable within one logical message.")
    text: str = Field(default="", description="Partial chunk; MAY be empty (keepalive).")


class ToolCallStart(BaseModel):
    """Marks the start of a tool invocation.

    Subsequent ``ToolCallArgs`` / ``ToolCallEnd`` events share the same
    ``call_id``.
    """

    kind: Literal["tool_call_start"] = "tool_call_start"
    call_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)


class ToolCallArgs(BaseModel):
    """A partial chunk of the tool invocation's JSON arguments.

    Concatenating all ``ToolCallArgs.args_chunk`` values for one ``call_id``
    yields the full JSON args payload.
    """

    kind: Literal["tool_call_args"] = "tool_call_args"
    call_id: str = Field(..., min_length=1)
    args_chunk: str = Field(default="")


class ToolCallEnd(BaseModel):
    """Marks the end of a tool invocation. Optionally carries the tool result."""

    kind: Literal["tool_call_end"] = "tool_call_end"
    call_id: str = Field(..., min_length=1)
    result: Any = Field(default=None, description="Optional tool result; shape is tool-specific.")


# Discriminated union — callers use ``TypeAdapter(HarnessEvent).validate_python(payload)``
# to parse raw dicts dispatched on the ``kind`` field.
HarnessEvent = Annotated[
    RunStarted | RunFinished | TextDelta | ToolCallStart | ToolCallArgs | ToolCallEnd,
    Field(discriminator="kind"),
]

__all__ = [
    "HarnessEvent",
    "RunFinished",
    "RunStarted",
    "TextDelta",
    "ToolCallArgs",
    "ToolCallEnd",
    "ToolCallStart",
]
