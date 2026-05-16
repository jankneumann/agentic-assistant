## ADDED Requirements

### Requirement: SSE Chat Endpoint

The system SHALL expose a single FastAPI endpoint at `POST /chat`
that accepts a JSON request body of shape `{"message": <str>}` and
returns a `text/event-stream` response containing AG-UI events
produced by the active harness for that user message. The endpoint
SHALL stream events as they are produced (no full-response
buffering) and SHALL set `Content-Type: text/event-stream` on the
response. The endpoint SHALL emit events using the SSE framing
specified by RFC 8895, with each AG-UI event serialized as JSON on a
single `data:` line.

#### Scenario: POST /chat returns text/event-stream content type

- **WHEN** a client POSTs `{"message": "hello"}` to `/chat` against a
  running server bound to the personal/assistant persona-role
- **THEN** the HTTP response status MUST be `200`
- **AND** the `Content-Type` response header MUST start with
  `text/event-stream`

#### Scenario: Response body contains AG-UI events

- **WHEN** a client POSTs `{"message": "hello"}` to `/chat` against a
  fake harness that yields one `TextDelta("hi")` then `RunFinished`
- **THEN** the response body MUST contain at least one `data:` line
  whose JSON payload has `type == "RUN_STARTED"`
- **AND** at least one `data:` line whose JSON payload has
  `type == "TEXT_MESSAGE_CONTENT"` and `delta == "hi"`
- **AND** the last `data:` line MUST have `type == "RUN_FINISHED"`

#### Scenario: Endpoint rejects non-JSON or malformed request bodies

- **WHEN** a client POSTs a body that is not valid JSON, or JSON
  without a `message` field, to `/chat`
- **THEN** the response status MUST be `422`
- **AND** the response body MUST NOT begin streaming SSE events

#### Scenario: Endpoint emits RUN_FINISHED with error when harness fails

- **WHEN** the harness's `astream_invoke` raises `RuntimeError`
- **THEN** the response stream MUST emit a terminal `RUN_FINISHED`
  event with the `error` field populated
- **AND** the stream MUST close cleanly without leaving the SSE
  response half-open

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
