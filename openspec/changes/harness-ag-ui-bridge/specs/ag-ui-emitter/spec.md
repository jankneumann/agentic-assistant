## ADDED Requirements

### Requirement: AG-UI Event Type Coverage in v1

The system SHALL emit exactly the following AG-UI event types in v1:
`RUN_STARTED`, `RUN_FINISHED`, `TEXT_MESSAGE_START`,
`TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`, `TOOL_CALL_START`,
`TOOL_CALL_ARGS`, `TOOL_CALL_END`. The emitter MUST NOT emit
`STATE_DELTA`, `CUSTOM`, step events, or any other AG-UI event type
in v1. Each emitted event MUST conform to the AG-UI protocol v0.x
shape with the fields required by that protocol for the event type.

#### Scenario: Emitter produces only the v1-scoped event types

- **WHEN** any harness event stream is fed through the AG-UI emitter
- **THEN** every emitted AG-UI event's `type` field MUST be one of
  the eight strings listed above
- **AND** no `STATE_DELTA` or `CUSTOM` event MUST be emitted

#### Scenario: Each emitted event conforms to the AG-UI v0.x schema

- **WHEN** a `RUN_STARTED` event is emitted
- **THEN** it MUST contain at minimum a `threadId` field and a
  `runId` field per the AG-UI v0.x spec
- **AND** a JSON-Schema validator for AG-UI v0.x events MUST accept
  the emitted payload

### Requirement: HarnessEvent to AG-UI Event Mapping

The system SHALL provide a `map_harness_to_ag_ui(stream:
AsyncIterator[HarnessEvent]) -> AsyncIterator[AGUIEvent]` async
function in `src/assistant/transports/ag_ui/mapper.py` that consumes
a stream of `HarnessEvent` instances and yields AG-UI protocol
events. The mapping SHALL be deterministic and the emitter SHALL NOT
buffer the entire stream before emitting.

#### Scenario: RunStarted maps to RUN_STARTED

- **WHEN** a `RunStarted(run_id="r1", started_at=...)` harness event
  is fed into the mapper
- **THEN** the first AG-UI event yielded MUST have
  `type == "RUN_STARTED"`
- **AND** `runId == "r1"`

#### Scenario: TextDelta maps to TEXT_MESSAGE_CONTENT framed by START/END

- **WHEN** three `TextDelta` events with the same `message_id` and
  texts `"Hel"`, `"lo"`, `" world"` are fed sequentially
- **THEN** the mapper MUST emit exactly one `TEXT_MESSAGE_START`
  event with that `messageId` before any content
- **AND** three `TEXT_MESSAGE_CONTENT` events with `delta` fields
  `"Hel"`, `"lo"`, `" world"` in order
- **AND** exactly one `TEXT_MESSAGE_END` event with the same
  `messageId` when the next harness event has a different
  `message_id` or the stream ends

#### Scenario: Tool call lifecycle maps to TOOL_CALL_* events

- **WHEN** a sequence `ToolCallStart(call_id="c1", tool_name="search")`,
  `ToolCallArgs(call_id="c1", args_chunk='{"q":')`, `ToolCallArgs(
  call_id="c1", args_chunk='"hi"}')`, `ToolCallEnd(call_id="c1")` is
  fed
- **THEN** the mapper MUST emit exactly one `TOOL_CALL_START` with
  `toolCallId="c1"` and `toolCallName="search"`
- **AND** two `TOOL_CALL_ARGS` events with the respective `delta`
  payloads
- **AND** one `TOOL_CALL_END` with `toolCallId="c1"`

#### Scenario: RunFinished maps to RUN_FINISHED

- **WHEN** a `RunFinished(run_id="r1", error=None)` event is the last
  harness event in the stream
- **THEN** the last AG-UI event yielded MUST have
  `type == "RUN_FINISHED"` and `runId == "r1"`

### Requirement: Run Lifecycle Event Ordering

The mapper SHALL guarantee that `RUN_STARTED` is emitted before any
`TEXT_MESSAGE_*` or `TOOL_CALL_*` event, and `RUN_FINISHED` is the
last event in any well-formed stream (successful or errored). The
mapper SHALL guarantee that `TEXT_MESSAGE_START` precedes every
`TEXT_MESSAGE_CONTENT` for a given message-id, and is followed by
exactly one `TEXT_MESSAGE_END` per message-id. The mapper SHALL
guarantee analogous bracketing for tool calls: every `TOOL_CALL_START`
is followed by zero or more `TOOL_CALL_ARGS` and exactly one
`TOOL_CALL_END` with matching `toolCallId`.

#### Scenario: RUN_STARTED precedes all content events

- **WHEN** the harness event stream begins with `RunStarted` followed
  by a `TextDelta`
- **THEN** the AG-UI stream MUST emit `RUN_STARTED` before any
  `TEXT_MESSAGE_*` event

#### Scenario: TEXT_MESSAGE_END closes a message on message-id boundary

- **WHEN** two consecutive `TextDelta` events have different
  `message_id` values
- **THEN** the mapper MUST emit a `TEXT_MESSAGE_END` for the first
  `message_id` before emitting `TEXT_MESSAGE_START` for the second

#### Scenario: TOOL_CALL_END terminates a call lifecycle

- **WHEN** a `ToolCallEnd(call_id="c1")` event is yielded by the
  harness
- **THEN** the mapper MUST emit `TOOL_CALL_END` with `toolCallId="c1"`
- **AND** MUST NOT emit further `TOOL_CALL_ARGS` events for `c1`

### Requirement: Error Mapping in v1

The AG-UI emitter SHALL surface harness errors as a terminal
`RUN_FINISHED` event with the `error` field populated (matching AG-UI
v0.x error semantics), after which the iterator SHALL close cleanly
and MUST NOT emit any further events. This error-mapping behavior
SHALL apply both when the harness event stream raises an exception
mid-stream and when it yields a `RunFinished` event whose `error`
field is non-empty.

#### Scenario: Harness exception surfaces as RUN_FINISHED with error

- **WHEN** the harness stream raises `RuntimeError("quota exceeded")`
  mid-stream
- **THEN** the final AG-UI event MUST be `RUN_FINISHED` with an
  `error` field whose value identifies the exception (at minimum the
  exception class name)
- **AND** no further events MUST be emitted after the terminal
  `RUN_FINISHED`

#### Scenario: RunFinished with error field is forwarded faithfully

- **WHEN** a `RunFinished(error="RuntimeError: quota exceeded")` is
  the last harness event
- **THEN** the emitted `RUN_FINISHED` AG-UI event MUST contain that
  error string in its `error` field
