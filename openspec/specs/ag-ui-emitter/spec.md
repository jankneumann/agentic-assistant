# ag-ui-emitter Specification

## Purpose
Governs the translation of the internal `HarnessEvent` stream into AG-UI
protocol events: the exact v1 event-type subset, the HarnessEvent-to-AG-UI
mapping rules, run lifecycle ordering, and error mapping. It exists so that
frontends speaking the AG-UI protocol can render assistant runs without any
knowledge of harness internals. Its sole consumer is the web-server SSE
`/chat` endpoint, which serializes the emitted events onto the wire.
## Requirements
### Requirement: AG-UI Event Type Coverage in v1

The system SHALL emit exactly the following AG-UI event types in v1:
`RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`, `TEXT_MESSAGE_START`,
`TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`, `TOOL_CALL_START`,
`TOOL_CALL_ARGS`, `TOOL_CALL_END`. The emitter MUST NOT emit
`STATE_DELTA`, `CUSTOM`, step events, or any other AG-UI event type
in v1. Each emitted event MUST conform to the AG-UI protocol v0.x
shape with the fields required by that protocol for the event type
(matching the upstream `ag_ui.core` Pydantic models — `RunStartedEvent`,
`RunFinishedEvent`, `RunErrorEvent`, etc.).

#### Scenario: Emitter produces only the v1-scoped event types

- **WHEN** any harness event stream is fed through the AG-UI emitter
- **THEN** every emitted AG-UI event's `type` field MUST be one of
  the nine strings listed above
- **AND** no `STATE_DELTA` or `CUSTOM` event MUST be emitted

#### Scenario: Each emitted event conforms to the AG-UI v0.x schema

- **WHEN** a `RUN_STARTED` event is emitted
- **THEN** it MUST contain at minimum a `threadId` field and a
  `runId` field per the AG-UI v0.x spec
- **AND** a JSON-Schema validator for AG-UI v0.x events MUST accept
  the emitted payload

### Requirement: HarnessEvent to AG-UI Event Mapping

The system SHALL provide a `map_harness_to_ag_ui(stream:
AsyncIterator[HarnessEvent], *, thread_id: str) -> AsyncIterator[AGUIEvent]`
async function in `src/assistant/transports/ag_ui/mapper.py` that
consumes a stream of `HarnessEvent` instances and yields AG-UI
protocol events. The `thread_id` keyword-only argument MUST be passed
on every call and MUST be a non-empty string; the mapper SHALL populate
the `threadId` field (required by AG-UI v0.x) on every emitted
`RUN_STARTED` and `RUN_FINISHED` event using this value. The mapping
SHALL be deterministic and the emitter SHALL NOT buffer the entire
stream before emitting.

#### Scenario: RunStarted maps to RUN_STARTED with thread_id

- **WHEN** a `RunStarted(run_id="r1", started_at=...)` harness event
  is fed into the mapper called with `thread_id="t-abc"`
- **THEN** the first AG-UI event yielded MUST have
  `type == "RUN_STARTED"`
- **AND** `runId == "r1"`
- **AND** `threadId == "t-abc"`

#### Scenario: Mapper rejects empty thread_id

- **WHEN** `map_harness_to_ag_ui` is called with `thread_id=""` (empty
  string) or `thread_id=None`
- **THEN** the mapper MUST raise `ValueError` before consuming the
  first harness event
- **AND** the error message MUST identify `thread_id` as the cause

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

#### Scenario: RunFinished maps to RUN_FINISHED with thread_id

- **WHEN** a `RunFinished(run_id="r1", error=None)` event is the last
  harness event in the stream and the mapper was called with
  `thread_id="t-abc"`
- **THEN** the last AG-UI event yielded MUST have
  `type == "RUN_FINISHED"`, `runId == "r1"`, and `threadId == "t-abc"`

### Requirement: Run Lifecycle Event Ordering

The mapper SHALL guarantee that `RUN_STARTED` is emitted before any
`TEXT_MESSAGE_*` or `TOOL_CALL_*` event, and that the LAST event in
any well-formed stream is either `RUN_FINISHED` (on success) or
`RUN_ERROR` (on failure) — never both, and exactly one. The mapper
SHALL guarantee that `TEXT_MESSAGE_START` precedes every
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

The AG-UI emitter SHALL surface harness errors using the two-phase
error contract defined in design.md D8: the harness yields a terminal
internal `RunFinished(error=<ClassName>)` event AND then re-raises
the original exception. On receiving a terminal internal `RunFinished`
whose `error` field is non-null, the mapper SHALL emit exactly one
terminal AG-UI `RUN_ERROR` event (matching the upstream
`ag_ui.core.RunErrorEvent` shape with `message` and `code` fields)
INSTEAD OF a `RUN_FINISHED` event. The mapper SHALL absorb the
subsequent re-raised exception (catching it and terminating the
generator cleanly), and MUST NOT synthesize an additional terminal
event of its own. Both `message` and `code` fields SHALL be set to
the exception class name only (matching the upstream
`RunErrorEvent.message` and `RunErrorEvent.code` semantics) — the
mapper MUST NOT forward any exception message body, stack-frame data,
or wrapped-exception detail. On success, the mapper SHALL emit
`RUN_FINISHED` (with no error fields, matching the upstream
`RunFinishedEvent` shape). After either terminal event the iterator
SHALL close cleanly and MUST NOT emit any further events.

#### Scenario: Harness exception surfaces as RUN_ERROR with class-name-only message

- **WHEN** the harness yields internal `RunFinished(run_id="r1",
  finished_at=..., error="RuntimeError")` as its final event AND then
  re-raises the underlying `RuntimeError("quota exceeded")`
- **THEN** the final AG-UI event yielded by the mapper MUST be
  `RUN_ERROR` with `message == "RuntimeError"` and
  `code == "RuntimeError"` (both class-name-only — no message body)
- **AND** no `RUN_FINISHED` event MUST be emitted in the same stream
  (the AG-UI terminal is `RUN_ERROR`, not both)
- **AND** the mapper MUST absorb the re-raised exception (it MUST NOT
  propagate to the caller of the mapper iterator)
- **AND** no further events MUST be emitted after the terminal
  `RUN_ERROR`

#### Scenario: Mapper does not synthesize on raw raise

- **WHEN** a misbehaving harness raises `RuntimeError` mid-stream
  WITHOUT first yielding a terminal internal `RunFinished` event
- **THEN** the mapper MUST NOT synthesize a terminal `RUN_ERROR` or
  `RUN_FINISHED` event of its own to cover the gap (the well-formed-
  stream contract is a harness obligation, enforced by the
  harness-adapter spec)
- **AND** the exception MUST propagate to the caller of the mapper
  iterator so the bug is observable upstream

#### Scenario: Successful run emits RUN_FINISHED (no error fields)

- **WHEN** the harness yields a terminal internal `RunFinished(...,
  error=None)`
- **THEN** the final AG-UI event yielded by the mapper MUST be
  `RUN_FINISHED` with no `message` or `code` fields (matching the
  upstream `RunFinishedEvent` shape, which has no error field)
- **AND** no `RUN_ERROR` event MUST be emitted in the same stream

