# web-server Specification

## Purpose
TBD - created by archiving change harness-ag-ui-bridge. Update Purpose after archive.
## Requirements
### Requirement: SSE Chat Endpoint

The system SHALL expose a single FastAPI endpoint at `POST /chat`
that accepts a JSON request body of shape `{"message": <str>}` and
returns a `text/event-stream` response containing AG-UI events
produced by the active harness for that user message. The endpoint
SHALL stream events as they are produced (no full-response
buffering) and SHALL set `Content-Type: text/event-stream` on the
response. The endpoint SHALL emit events using the standard SSE
framing (WHATWG HTML Living Standard, EventSource specification), with
each AG-UI event serialized as JSON on a single `data:` line.

#### Scenario: POST /chat returns text/event-stream content type

- **WHEN** a client POSTs `{"message": "hello"}` to `/chat` against a
  running server bound to the personal/assistant persona-role
- **THEN** the HTTP response status MUST be `200`
- **AND** the `Content-Type` response header MUST start with
  `text/event-stream`

#### Scenario: Response body contains a well-formed AG-UI event stream

- **WHEN** a client POSTs `{"message": "hello"}` to `/chat` against a
  fake harness that yields `RunStarted`, one `TextDelta("hi")`, then
  `RunFinished`
- **THEN** the response body MUST contain (in order) a `data:` line
  with `type == "RUN_STARTED"`
- **AND** a `data:` line with `type == "TEXT_MESSAGE_START"` and a
  `messageId` matching the harness's emitted `message_id`
- **AND** a `data:` line with `type == "TEXT_MESSAGE_CONTENT"`,
  `delta == "hi"`, and the same `messageId`
- **AND** a `data:` line with `type == "TEXT_MESSAGE_END"` and the
  same `messageId` (the mapper's bracketing requirement is preserved
  end-to-end through the SSE response)
- **AND** the last `data:` line MUST have `type == "RUN_FINISHED"`

#### Scenario: Endpoint rejects non-JSON or malformed request bodies

- **WHEN** a client POSTs a body that is not valid JSON, or JSON
  without a `message` field, to `/chat`
- **THEN** the response status MUST be `422`
- **AND** the response body MUST NOT begin streaming SSE events
- **AND** the `Content-Type` response header MUST be
  `application/problem+json` (RFC 7807), produced by the app's custom
  `RequestValidationError` exception handler

#### Scenario: Endpoint rejects messages exceeding the maxLength bound

- **WHEN** a client POSTs `{"message": "<32769 characters>"}` to
  `/chat` (one byte over the OpenAPI `maxLength: 32768` cap)
- **THEN** the response status MUST be `422`
- **AND** the harness's `astream_invoke` MUST NOT be invoked (the
  validation MUST happen before any harness work begins)
- **AND** the `Content-Type` response header MUST be
  `application/problem+json`

#### Scenario: Endpoint emits RUN_ERROR when harness fails

- **WHEN** the harness's `astream_invoke` follows the two-phase D8
  contract (yields terminal internal `RunFinished(error="RuntimeError")`
  and then re-raises the original `RuntimeError`)
- **THEN** the response stream MUST emit a terminal AG-UI `RUN_ERROR`
  event with `message == "RuntimeError"` and `code == "RuntimeError"`
  (NOT a `RUN_FINISHED` event with an error field — the upstream
  `ag_ui.core.RunFinishedEvent` shape has no error field; failures
  map to `RunErrorEvent`)
- **AND** the stream MUST close cleanly without leaving the SSE
  response half-open (the mapper absorbs the Phase 2 re-raised
  exception per design.md D8)
- **AND** the `message` and `code` field values MUST be the exception
  class name only — not the exception message body — to prevent
  leakage of file paths, stack frames, or secret-bearing exception
  text to the client (full traceback is logged server-side via
  `@traced_harness` at ERROR level)

#### Scenario: Client disconnect during streaming cancels the harness

- **WHEN** a client closes the HTTP connection mid-stream (before
  `RUN_FINISHED` is emitted)
- **THEN** the server MUST detect the disconnect via
  `sse-starlette`'s built-in detector
- **AND** the underlying `astream_invoke` async generator MUST be
  closed via `aclose()` so that any open resources are released
- **AND** no further events MUST be emitted on the closed stream
- **AND** the server MUST NOT raise to the response handler (the
  cancellation is normal, not an error)

#### Scenario: Empty harness response emits lifecycle-only events

- **WHEN** the harness yields only `RunStarted` and `RunFinished`
  with no text or tool-call events between them
- **THEN** the response body MUST contain exactly one
  `data: RUN_STARTED` line and one `data: RUN_FINISHED` line
- **AND** no `TEXT_MESSAGE_*` or `TOOL_CALL_*` events MUST be
  emitted

### Requirement: Startup-Time Persona Binding

The FastAPI application SHALL bind exactly one persona, role, and
harness instance at startup via a `lifespan` async context manager.
The constructed harness adapter SHALL be stored on `app.state.harness`
and SHALL be shared across all `/chat` requests for the lifetime of
the server process. The lifespan SHALL NOT construct a harness
per-request, and the harness instance SHALL persist its conversation
thread (`thread_id`) across requests within a single server lifetime.

#### Scenario: Lifespan constructs a single harness at startup

- **WHEN** the FastAPI app's lifespan context is entered for persona
  `personal`, role `assistant`, harness `deep_agents`
- **THEN** exactly one call to `create_harness(persona, role,
  "deep_agents")` MUST occur during startup
- **AND** the returned adapter MUST be set on `app.state.harness`

#### Scenario: All requests share the same harness instance

- **WHEN** two sequential POST requests to `/chat` are processed
- **THEN** both requests MUST observe `request.app.state.harness` as
  the same object instance (identity equality)
- **AND** the harness's internal `_thread_id` MUST be unchanged
  between the two requests

#### Scenario: Lifespan rejects host harnesses

- **WHEN** the app factory is invoked with a host-harness name (e.g.
  `claude_code`)
- **THEN** lifespan startup MUST raise an exception preventing the
  server from accepting requests

#### Scenario: Lifespan rejects persona with the chosen harness disabled

- **WHEN** the app factory is invoked for a persona whose
  `harnesses.<harness_name>.enabled` is `false` (or whose harness
  configuration is missing entirely)
- **THEN** lifespan startup MUST raise a clear error identifying the
  persona name, the harness name, and the disabled/missing state
- **AND** the server MUST NOT begin accepting requests

### Requirement: Server Loopback Binding by Default

The `serve` subcommand SHALL bind the underlying uvicorn server to
`127.0.0.1` by default. Binding to a non-loopback address SHALL
require an explicit `--host` flag. The default port SHALL be `8765`.

#### Scenario: Default bind is loopback

- **WHEN** `assistant serve -p personal` is executed without `--host`
- **THEN** uvicorn MUST be invoked with `host="127.0.0.1"`

#### Scenario: Explicit --host overrides default

- **WHEN** `assistant serve -p personal --host 0.0.0.0` is executed
- **THEN** uvicorn MUST be invoked with `host="0.0.0.0"`

### Requirement: Health Check Endpoint

The FastAPI application SHALL expose `GET /health` returning HTTP
`200` with a JSON body containing at minimum the active persona
name, role name, and harness name. The endpoint SHALL NOT invoke
the harness or stream any events.

#### Scenario: Health check returns persona, role, harness identity

- **WHEN** a client GETs `/health` against a server bound to persona
  `personal`, role `assistant`, harness `deep_agents`
- **THEN** the response status MUST be `200`
- **AND** the JSON body MUST contain a `persona` field equal to
  `"personal"`, a `role` field equal to `"assistant"`, and a
  `harness` field equal to `"deep_agents"`

#### Scenario: Health check does not invoke the harness

- **WHEN** a client GETs `/health` repeatedly
- **THEN** the harness's `invoke` and `astream_invoke` methods MUST
  NOT be called as a side effect

