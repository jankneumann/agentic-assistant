# a2a-server Specification (delta)

## ADDED Requirements

### Requirement: Agent Card Discovery

The system SHALL serve an A2A agent card describing the bound persona
at `GET /.well-known/agent-card.json` (canonical, A2A protocol version
0.3.0) and at `GET /.well-known/agent.json` (legacy pre-0.3.0 alias),
returning identical JSON at both paths. The card MUST declare
`protocolVersion`, `name` (persona display name), `description`,
`url` (the served base URL plus the JSON-RPC mount `/a2a/v1`),
`version`, `capabilities.streaming = true`, and one skill per role
enabled for the persona — skill `id` equal to the role name, skill
`name` equal to the role display name, and the role description. Wire
field names MUST be camelCase per the A2A schema.

#### Scenario: Card served at both well-known paths

- **WHEN** a client GETs `/.well-known/agent-card.json` and
  `/.well-known/agent.json` against a server started with `--a2a`
- **THEN** both responses MUST be HTTP 200 with identical JSON bodies

#### Scenario: Roles are exposed as skills

- **WHEN** the persona has roles `coder` and `researcher` enabled
- **THEN** the card's `skills` array MUST contain exactly one entry
  per role with `id` equal to the role name
- **AND** `capabilities.streaming` MUST be `true`

### Requirement: JSON-RPC Message Endpoint

The system SHALL expose a JSON-RPC 2.0 endpoint at `POST /a2a/v1`
accepting the methods `message/send` and `message/stream`. Envelope
failures MUST be returned as HTTP 200 responses carrying a
`JSONRPCErrorResponse` with the standard codes: `-32700` for
unparseable JSON, `-32600` for an invalid JSON-RPC envelope, `-32601`
for unknown methods, and `-32602` for params that do not validate as
`MessageSendParams`. Non-text message parts MUST be rejected with the
A2A `ContentTypeNotSupported` code (`-32005`); a message referencing a
known `taskId` MUST be rejected with `UnsupportedOperation` (`-32004`,
continuation requires the deferred approval interrupt/resume flow) and
an unknown `taskId` with `TaskNotFound` (`-32001`).

#### Scenario: Unparseable body returns parse error

- **WHEN** a client POSTs a non-JSON body to `/a2a/v1`
- **THEN** the response MUST be HTTP 200 with `error.code == -32700`

#### Scenario: Unknown method returns method-not-found

- **WHEN** a client POSTs a valid envelope with method `tasks/cancel`
- **THEN** the response MUST carry `error.code == -32601`
- **AND** the response `id` MUST echo the request `id`

#### Scenario: Malformed params return invalid-params

- **WHEN** the `params` object lacks a valid `message`
- **THEN** the response MUST carry `error.code == -32602`

### Requirement: Blocking Message Send

The system SHALL implement the `message/send` JSON-RPC method by
running the message through a session-bound SDK harness
(`astream_invoke`) to completion and returning the terminal `Task`
object as the JSON-RPC result: task lifecycle `submitted → working →
completed` on success with the streamed text accumulated into the
task's `artifacts`, or terminal state `failed` on harness error.
Harness failures MUST NOT be reported as JSON-RPC errors — the request
succeeded; the task failed — and failure text MUST be the exception
class name only (the harness-event redaction rule).

#### Scenario: message/send returns a completed task with artifacts

- **WHEN** `message/send` is invoked with a text message against a
  harness that streams `"Hello"` and `" world"`
- **THEN** the JSON-RPC result MUST be a `task` whose
  `status.state == "completed"`
- **AND** the concatenated text parts of its artifacts MUST equal
  `"Hello world"`

#### Scenario: Harness failure yields a failed task, not a protocol error

- **WHEN** the harness terminates with the two-phase error contract
  (`RunFinished(error="RuntimeError")` then re-raise)
- **THEN** the JSON-RPC response MUST be a success envelope whose
  result task has `status.state == "failed"`
- **AND** the failure message text MUST be `"RuntimeError"` with no
  exception message body

### Requirement: Streaming Message Endpoint

The system SHALL implement the `message/stream` JSON-RPC method as an
SSE response (`text/event-stream`) in which every SSE `data:` line is
a JSON-RPC success envelope (echoing the request `id`) whose `result`
is one A2A event, in order: first the initial `Task` snapshot in state
`submitted`, then a `status-update` with state `working`, then
`artifact-update` events for streamed text (`append` set on
continuation chunks of the same artifact), and finally a
`status-update` with `final == true` (state `completed` or `failed`).
The two-phase harness error contract MUST be honored: the Phase-1
terminal `RunFinished(error=…)` maps to the final `failed` update with
class-name-only text and the Phase-2 re-raise is absorbed; a harness
that raises WITHOUT the Phase-1 terminal event MUST still produce a
synthesized final `failed` update so every stream ends with
`final == true`. The same stream MUST also be served REST-style at
`POST /a2a/v1/message:stream` (HTTP+JSON transport alias) with a bare
`MessageSendParams` body and bare A2A event objects as SSE data.

#### Scenario: SSE stream carries the full lifecycle in order

- **WHEN** `message/stream` is invoked against a harness that streams
  one text chunk and completes
- **THEN** the SSE data lines MUST decode to JSON-RPC envelopes whose
  results are, in order: a `task` in state `submitted`, a
  `status-update` with state `working`, at least one
  `artifact-update`, and a terminal `status-update` with state
  `completed` and `final == true`

#### Scenario: Two-phase harness error ends the stream with final failed

- **WHEN** the harness yields `RunFinished(error="RuntimeError")` and
  then re-raises
- **THEN** the last SSE event MUST be a `status-update` with state
  `failed` and `final == true`
- **AND** no `completed` status MUST appear anywhere in the stream

#### Scenario: REST alias streams bare events

- **WHEN** a client POSTs `MessageSendParams` JSON to
  `/a2a/v1/message:stream`
- **THEN** the SSE data lines MUST be bare A2A objects (no `jsonrpc`
  member), beginning with the `task` snapshot and ending with a
  `final == true` status-update

### Requirement: Approval Input-Required Bridge

The system SHALL surface guardrail approval denials as the A2A
`input-required` task state: when a run terminates with an
approval-denial error class (the leaf class name of
`RunFinished.error` matching the configured set, which includes
`ModelCallDeniedError` — raised when a guardrail returns
`require_confirmation=True` under the security-hardening
deny-until-interrupt semantics), the stream MUST emit a non-final
`status-update` with state `input-required` carrying an agent message,
followed by the final `failed` status-update. Interrupt/resume is NOT
implemented — the task then fails per P13 semantics; this requirement
bridges the guardrail-provider `ApprovalRequest` contract to the A2A
surface observationally until the durable-session approval flow
exists.

#### Scenario: Approval denial produces input-required then failed

- **WHEN** the harness terminates with
  `RunFinished(error="ModelCallDeniedError")`
- **THEN** the stream MUST contain a `status-update` with state
  `input-required` and `final == false`
- **AND** the terminal event MUST be a `status-update` with state
  `failed` and `final == true`

#### Scenario: Ordinary failures skip input-required

- **WHEN** the harness terminates with
  `RunFinished(error="RuntimeError")`
- **THEN** no `input-required` status MUST appear in the stream

### Requirement: A2A Session Multiplexing

The system SHALL multiplex A2A tasks over an in-memory
`SessionRegistry` implementing the harness-adapter Session Registry
contract (create / lookup / expire by `thread_id`, idle-TTL expiry),
with the A2A `contextId` equal to the session `thread_id`. A message
without a `contextId` MUST create a fresh session (a new harness and
agent built through the same persona/role pipeline as the AG-UI
lifespan, with its own `thread_id`); a message with a known
`contextId` MUST reuse that session so consecutive tasks share
conversation state; a message with an unknown `contextId` MUST be
rejected with `InvalidParams` (`-32602`) rather than silently creating
a new session — in-memory sessions are not resumable until the durable
checkpointer lands. Concurrent tasks on distinct sessions MUST NOT
observe each other's conversations, and runs on one session MUST be
serialized.

#### Scenario: Tasks without contextId get distinct sessions

- **WHEN** two `message/send` calls are made without `contextId`
- **THEN** the returned tasks MUST carry distinct `contextId` values
- **AND** each MUST have executed on its own harness instance

#### Scenario: Known contextId reuses the session

- **WHEN** a second message is sent with the `contextId` returned by a
  prior task
- **THEN** it MUST execute on the same harness instance as the first
- **AND** the two tasks MUST have distinct task `id` values

#### Scenario: Unknown contextId is rejected

- **WHEN** a message references a `contextId` that was never created
  (or has been expired)
- **THEN** the response MUST carry `error.code == -32602`
