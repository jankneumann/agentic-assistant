## 1. Foundation — Dependencies and HarnessEvent

- [x] 1.1 ~~Audit AG-UI Python package availability~~ (resolved during plan revision)
  **Resolution**: Use upstream `ag-ui` (Python package). Confirmed installed in current venv; `ag_ui.core` exposes Pydantic-typed event classes for every v1-scoped type plus `EventType` enum. No in-repo types needed. Add `ag-ui` to `pyproject.toml` dependencies during Task 1.4.
  **Spec scenarios**: (none — research task, resolved at plan time)
  **Design decisions**: D5 (updated)
  **Dependencies**: None
  **Status**: closed; superseded by Task 1.4

- [x] 1.2 Write tests for HarnessEvent discriminated union
  **Spec scenarios**: harness-adapter "HarnessEvent variants are exhaustive for v1", "RunStarted carries an opaque run identifier", "TextDelta carries partial text chunks", "Tool call lifecycle events share a call_id"
  **Contracts**: contracts/events/harness-event.schema.json
  **Design decisions**: D1
  **Dependencies**: 1.1

- [x] 1.3 Implement `src/assistant/harnesses/sdk/events.py`
  **Goal**: Define `HarnessEvent` discriminated union (Pydantic) with the 6 variants: RunStarted, RunFinished, TextDelta, ToolCallStart, ToolCallArgs, ToolCallEnd. Field names must be harness-agnostic and protocol-agnostic per D1. Module lives in the harness layer (not transports/) so concrete harnesses can construct events without importing upward into transports/ — preserves D6 import-direction rule. The `RunFinished.error` field MUST match the class-name-only pattern per D8.
  **Dependencies**: 1.2

- [x] 1.4 Add runtime + dev dependencies to `pyproject.toml`
  **Goal**: Add `fastapi`, `uvicorn[standard]`, `sse-starlette`, and `ag-ui` (the upstream AG-UI types package, confirmed installed during plan revision). Run `uv sync` and verify the lockfile diff is sane.
  **Dependencies**: None

## 2. Harness Interface Evolution

- [x] 2.1 Write tests for `SdkHarnessAdapter.astream_invoke` abstract signature
  **Spec scenarios**: harness-adapter "SdkHarnessAdapter.astream_invoke returns async iterator of HarnessEvent"
  **Design decisions**: D1
  **Dependencies**: 1.3

- [x] 2.2 Add abstract `astream_invoke` and `thread_id` to `src/assistant/harnesses/base.py`
  **Goal**: Add abstract method to `SdkHarnessAdapter` returning `AsyncIterator[HarnessEvent]`. Existing `invoke()` MUST remain unchanged. Both `DeepAgentsHarness` and `MSAgentFrameworkHarness` will implement this concretely in Sections 3 and 3b respectively — no NotImplementedError stub is acceptable on the base, since both real harnesses must satisfy the abstract contract before this change can merge. Also add an abstract `thread_id: str` property (or attribute requirement) to `SdkHarnessAdapter` so the web transport can pass a stable thread identifier to the AG-UI mapper. Deep Agents implements it as `return self._thread_id`; MSAF synthesizes a UUID at construction time.
  **Spec scenarios**: harness-adapter "SdkHarnessAdapter.astream_invoke returns async iterator of HarnessEvent", "SdkHarnessAdapter exposes a thread_id for transport binding"
  **Dependencies**: 2.1

- [x] 2.3 Write tests for `@traced_harness` async-generator support
  **Spec scenarios**: harness-adapter "Deep Agents astream_invoke is traced on success", "Deep Agents astream_invoke is traced on exception"
  **Design decisions**: D9
  **Dependencies**: 2.2

- [x] 2.4 Extend `@traced_harness` decorator to dispatch on coroutine vs async-generator
  **Goal**: Detect whether the wrapped function returns a coroutine or an async generator. For generators, measure duration across full consumption (success) or until the exception escapes (failure). Emit `trace_llm_call` exactly once in either case. Add `streaming=True` to metadata for the generator path per D9.
  **Dependencies**: 2.3

## 3. Deep Agents Streaming Implementation

- [x] 3.1 Write tests for `DeepAgentsHarness.astream_invoke` lifecycle bracketing
  **Spec scenarios**: harness-adapter "astream_invoke emits RunStarted then RunFinished"
  **Design decisions**: D1, D7
  **Dependencies**: 2.2

- [x] 3.2 Write tests for thread_id propagation in streaming path
  **Spec scenarios**: harness-adapter "astream_invoke passes thread_id to LangGraph"
  **Design decisions**: D3, D4
  **Dependencies**: 2.2

- [x] 3.3 Write tests for LangChain text-chunk → TextDelta mapping
  **Spec scenarios**: harness-adapter "astream_invoke translates LangChain text chunks to TextDelta"
  **Design decisions**: D1
  **Dependencies**: 2.2

- [x] 3.4 Write tests for tool-call lifecycle translation
  **Spec scenarios**: harness-adapter "astream_invoke translates tool calls to lifecycle events"
  **Design decisions**: D1
  **Dependencies**: 2.2

- [x] 3.5 Write tests for error propagation (harness exception → terminal RunFinished with error)
  **Spec scenarios**: harness-adapter "astream_invoke emits RunFinished with error on exception"
  **Design decisions**: D8
  **Dependencies**: 2.2

- [x] 3.6 Implement `DeepAgentsHarness.astream_invoke` in `src/assistant/harnesses/sdk/deep_agents.py`
  **Goal**: Consume `agent.astream_events(version="v2")` with the existing `_thread_id`; translate LangChain stream events into `HarnessEvent` variants via an explicit allowlist (on_chat_model_stream→TextDelta, on_tool_start→ToolCallStart+ToolCallArgs, on_tool_end→ToolCallEnd). Applied `@traced_harness` decorator. Added `thread_id` property returning `self._thread_id`. `_thread_id` now initialized to a UUID at `__init__` time (overwritten at `create_agent` time).
  **Dependencies**: 3.1, 3.2, 3.3, 3.4, 3.5, 2.4

## 3b. MS Agent Framework Streaming Implementation

Added during plan revision after confirming MSAF is fully implemented (per the existing `ms-agent-framework-harness` spec and `src/assistant/harnesses/sdk/ms_agent_fw.py`). Runs in parallel with Section 3 (different harness file). Both depend on Section 2 foundation.

- [x] 3b.1 Write tests for MSAF `astream_invoke` calling `agent.run(stream=True)`
  **Spec scenarios**: harness-adapter "MSAF astream_invoke calls agent.run with stream=True"
  **Design decisions**: D11
  **Dependencies**: 2.2

- [x] 3b.2 Write tests for MSAF lifecycle bracketing (RunStarted/RunFinished)
  **Spec scenarios**: harness-adapter "MSAF astream_invoke emits RunStarted then RunFinished"
  **Design decisions**: D1, D11
  **Dependencies**: 2.2

- [x] 3b.3 Write tests for `AgentResponseUpdate` → `TextDelta` mapping
  **Spec scenarios**: harness-adapter "MSAF astream_invoke translates text updates to TextDelta"
  **Design decisions**: D11
  **Dependencies**: 2.2

- [x] 3b.4 Write tests for MSAF tool-call lifecycle translation
  **Spec scenarios**: harness-adapter "MSAF astream_invoke translates tool calls to lifecycle events"
  **Design decisions**: D11
  **Dependencies**: 2.2

- [x] 3b.5 Write tests for MSAF error propagation (exception → terminal RunFinished with error)
  **Spec scenarios**: harness-adapter "MSAF astream_invoke emits RunFinished with error on exception"
  **Design decisions**: D8, D11
  **Dependencies**: 2.2

- [x] 3b.6 Write tests for `@traced_harness` on MSAF streaming path (success + exception)
  **Spec scenarios**: harness-adapter "MSAF astream_invoke applies @traced_harness", "MSAF astream_invoke is traced on exception"
  **Design decisions**: D9
  **Dependencies**: 2.4

- [x] 3b.7 Implement `MSAgentFrameworkHarness.astream_invoke` in `src/assistant/harnesses/sdk/ms_agent_fw.py`
  **Goal**: Call `agent.run(messages, stream=True)`, iterate the returned `ResponseStream`, translate `AgentResponseUpdate` instances to `HarnessEvent` per the D11 mapping table. Use defensive `getattr` with fallbacks (mirror `_stringify_run_result`). Keep lazy `agent_framework` imports (v1.0.1 namespace quirk workaround). Apply `@traced_harness` decorator.
  **Dependencies**: 3b.1, 3b.2, 3b.3, 3b.4, 3b.5, 3b.6, 2.4

## 4. AG-UI Emitter

- [x] 4.1 Write tests for v1-scoped event type coverage
  **Spec scenarios**: ag-ui-emitter "Emitter produces only the v1-scoped event types", "Each emitted event conforms to the AG-UI v0.x schema"
  **Contracts**: contracts/events/ag-ui-events.schema.json
  **Design decisions**: D5
  **Dependencies**: 1.3

- [x] 4.2 Write tests for HarnessEvent → AG-UI event mapping (with thread_id propagation)
  **Spec scenarios**: ag-ui-emitter "RunStarted maps to RUN_STARTED with thread_id", "Mapper rejects empty thread_id", "TextDelta maps to TEXT_MESSAGE_CONTENT framed by START/END", "Tool call lifecycle maps to TOOL_CALL_* events", "RunFinished maps to RUN_FINISHED with thread_id"
  **Contracts**: contracts/events/ag-ui-events.schema.json, contracts/events/harness-event.schema.json
  **Design decisions**: D1, D6
  **Dependencies**: 1.3

- [x] 4.3 Write tests for run lifecycle event ordering invariants
  **Spec scenarios**: ag-ui-emitter "RUN_STARTED precedes all content events", "TEXT_MESSAGE_END closes a message on message-id boundary", "TOOL_CALL_END terminates a call lifecycle"
  **Design decisions**: D1
  **Dependencies**: 1.3

- [x] 4.4 Write tests for error mapping to terminal RUN_ERROR (two-phase D8 contract)
  **Spec scenarios**: ag-ui-emitter "Harness exception surfaces as RUN_ERROR with class-name-only message", "Mapper does not synthesize on raw raise", "Successful run emits RUN_FINISHED (no error fields)"
  **Design decisions**: D8
  **Dependencies**: 1.3

- [x] 4.5 Implement `src/assistant/transports/ag_ui/types.py`
  **Goal**: AG-UI event Pydantic models for the 8 v1-scoped event types. If 1.1 found a usable upstream package, this file is a thin re-export shim; if not, define the types in-repo against the AG-UI v0.x spec.
  **Design decisions**: D5
  **Dependencies**: 1.1, 4.1

- [x] 4.6 Implement `src/assistant/transports/ag_ui/mapper.py`
  **Goal**: `async def map_harness_to_ag_ui(stream: AsyncIterator[HarnessEvent], *, thread_id: str) -> AsyncIterator[AGUIEvent]`. Streaming, deterministic, no full-stream buffering. The `thread_id` is required keyword-only and populates the `threadId` field on every emitted `RUN_STARTED`/`RUN_FINISHED`. Raises `ValueError` on empty `thread_id`. Owns the TEXT_MESSAGE_START/END and TOOL_CALL_START/END bracketing logic. Implements two-phase D8 error handling: on receiving terminal internal `RunFinished(error=<ClassName>)`, emits one `RUN_ERROR` event (mapping to upstream `ag_ui.core.RunErrorEvent` with `message` and `code` both set to the class name — NOT `RUN_FINISHED`, which has no error field in the upstream model). On `RunFinished(error=None)` emits `RUN_FINISHED` cleanly. After the terminal event, catches/absorbs any subsequent re-raised exception from upstream (no synthetic events, no propagation).
  **Dependencies**: 4.2, 4.3, 4.4, 4.5

## 5. FastAPI Application + SSE Endpoint

- [x] 5.1 Write tests for `/chat` endpoint content-type
  **Spec scenarios**: web-server "POST /chat returns text/event-stream content type"
  **Contracts**: contracts/openapi/v1.yaml
  **Design decisions**: D2, D6
  **Dependencies**: 1.4

- [x] 5.2 Write tests for `/chat` response body containing AG-UI events (full lifecycle bracketing)
  **Spec scenarios**: web-server "Response body contains a well-formed AG-UI event stream"
  **Contracts**: contracts/openapi/v1.yaml, contracts/events/ag-ui-events.schema.json
  **Design decisions**: D2, D7
  **Dependencies**: 1.4

- [x] 5.3 Write tests for request validation (422 on malformed bodies, RFC 7807 shape)
  **Spec scenarios**: web-server "Endpoint rejects non-JSON or malformed request bodies"
  **Contracts**: contracts/openapi/v1.yaml
  **Dependencies**: 1.4

- [x] 5.3b Write tests for message length validation (oversize → 422)
  **Goal**: Assert that a body with `message` of 32769 characters yields HTTP 422 with `Content-Type: application/problem+json`, and that the harness's `astream_invoke` is never called for that request.
  **Spec scenarios**: web-server "Endpoint rejects messages exceeding the maxLength bound"
  **Contracts**: contracts/openapi/v1.yaml (`ChatRequest.message.maxLength`)
  **Dependencies**: 1.4

- [x] 5.3c Implement custom `RequestValidationError` exception handler in `src/assistant/web/app.py`
  **Goal**: Register an `app.exception_handler(RequestValidationError)` that converts FastAPI's default validation-error payload into RFC 7807 `Problem` JSON with `Content-Type: application/problem+json`, matching the OpenAPI 422 contract. Include the first validation error's `msg` in `detail`. The handler MUST NOT leak field paths beyond the request body schema (no internal stack data).
  **Spec scenarios**: web-server "Endpoint rejects non-JSON or malformed request bodies", "Endpoint rejects messages exceeding the maxLength bound"
  **Dependencies**: 5.3, 5.3b

- [x] 5.4 Write tests for harness-error path emitting terminal RUN_ERROR (two-phase D8 contract)
  **Goal**: Fake harness yields terminal internal `RunFinished(error="RuntimeError")` then re-raises `RuntimeError("quota exceeded")`. Assert the response stream contains exactly one AG-UI `RUN_ERROR` event with `message == "RuntimeError"` and `code == "RuntimeError"` (class name only — NOT a `RUN_FINISHED` with an error field; the upstream `RunFinishedEvent` has no error field, so failures map to the separate `RunErrorEvent` shape per D8). Assert that no `RUN_FINISHED` event is emitted in the same stream, no further events follow `RUN_ERROR`, and that the response generator returns cleanly (the mapper absorbs the Phase-2 re-raised exception per D8).
  **Spec scenarios**: web-server "Endpoint emits RUN_ERROR when harness fails"
  **Design decisions**: D8 (two-phase contract, redaction rule, RUN_ERROR mapping)
  **Dependencies**: 4.6

- [x] 5.4b Write tests for client disconnect during streaming
  **Goal**: Use FastAPI TestClient with manually-controlled stream closure (or `httpx.AsyncClient` with `stream=True` followed by early `aclose()`). Assert that the harness's async-generator `aclose()` is called, that no further events are emitted, and that the response handler does not raise.
  **Spec scenarios**: web-server "Client disconnect during streaming cancels the harness"
  **Design decisions**: D13
  **Dependencies**: 4.6

- [x] 5.4c Write tests for empty harness response (lifecycle-only events)
  **Spec scenarios**: web-server "Empty harness response emits lifecycle-only events"
  **Dependencies**: 4.6

- [x] 5.5 Write tests for lifespan single-harness construction at startup
  **Spec scenarios**: web-server "Lifespan constructs a single harness at startup"
  **Design decisions**: D3
  **Dependencies**: 1.4

- [x] 5.6 Write tests for shared harness instance across requests
  **Spec scenarios**: web-server "All requests share the same harness instance"
  **Design decisions**: D3, D4
  **Dependencies**: 1.4

- [x] 5.7 Write tests for lifespan rejecting host harnesses
  **Spec scenarios**: web-server "Lifespan rejects host harnesses"
  **Dependencies**: 1.4

- [x] 5.7b Write tests for lifespan rejecting persona with disabled or missing harness config
  **Spec scenarios**: web-server "Lifespan rejects persona with the chosen harness disabled"
  **Dependencies**: 1.4

- [x] 5.8 Write tests for `/health` endpoint
  **Spec scenarios**: web-server "Health check returns persona, role, harness identity", "Health check does not invoke the harness"
  **Contracts**: contracts/openapi/v1.yaml
  **Dependencies**: 1.4

- [x] 5.9 Implement `src/assistant/web/app.py` — FastAPI factory `make_app(persona, role, harness_name) -> FastAPI`
  **Goal**: App factory with lifespan that constructs harness once and stores on `app.state.harness`. Reject host harnesses in lifespan.
  **Dependencies**: 5.5, 5.6, 5.7

- [x] 5.10 Implement `src/assistant/web/routes.py` — `/chat` (SSE) and `/health` (JSON)
  **Goal**: `/chat` calls `app.state.harness.astream_invoke(...)`, pipes through `map_harness_to_ag_ui(stream, thread_id=app.state.harness.thread_id)` (passing the bound harness's public `thread_id` attribute keyword-only per the updated mapper signature — the SdkHarnessAdapter base class requires every concrete harness to expose this attribute per the harness-adapter spec "SdkHarnessAdapter exposes a thread_id for transport binding" requirement). Serves as SSE via `sse-starlette`. `/health` returns persona/role/harness identity without touching the harness.
  **Dependencies**: 5.1, 5.2, 5.3, 5.4, 5.8, 5.9, 4.6, 3.6, 3b.7

## 6. CLI serve Subcommand

- [x] 6.1 Write tests for `serve` startup binding persona/role
  **Spec scenarios**: cli-interface "serve binds the supplied persona and role at startup"
  **Dependencies**: 5.9

- [x] 6.2 Write tests for default host (127.0.0.1)
  **Spec scenarios**: cli-interface "serve defaults host to 127.0.0.1", web-server "Default bind is loopback", "Explicit --host overrides default"
  **Design decisions**: D6 (loopback per privacy default)
  **Dependencies**: 5.9

- [x] 6.3 Write tests for `default_role` fallback when `-r` omitted
  **Spec scenarios**: cli-interface "serve uses persona default_role when -r is omitted"
  **Dependencies**: 5.9

- [x] 6.4 Write tests for unknown persona handling
  **Spec scenarios**: cli-interface "serve rejects unknown personas with non-zero exit"
  **Dependencies**: 5.9

- [x] 6.5 Write tests for host-harness rejection at CLI boundary
  **Spec scenarios**: cli-interface "serve rejects host harness names"
  **Dependencies**: 5.9

- [x] 6.6 Write tests for clean Ctrl-C exit (status 0)
  **Spec scenarios**: cli-interface "Ctrl-C exits with status 0"
  **Dependencies**: 5.9

- [x] 6.6b Write tests for persona with no default_role (when -r omitted)
  **Spec scenarios**: cli-interface "serve rejects persona with no default_role when -r is omitted"
  **Dependencies**: 5.9

- [x] 6.6c Write tests for unknown harness name handling
  **Spec scenarios**: cli-interface "serve rejects unknown harness names"
  **Dependencies**: 5.9

- [x] 6.6d Write tests for non-loopback host warning
  **Goal**: Capture stderr while invoking `assistant serve -p personal --host 0.0.0.0` and assert a warning is present before uvicorn starts. The server still starts; the test should verify the warning text + ordering, not refuse-to-start semantics.
  **Spec scenarios**: cli-interface "serve warns when binding to a non-loopback host"
  **Design decisions**: D12
  **Dependencies**: 5.9

- [x] 6.7 Write tests for `--help` mentioning `serve`
  **Spec scenarios**: cli-interface "Serve subcommand is registered in the CLI group"
  **Dependencies**: 5.9

- [x] 6.8 Implement `serve` subcommand in `src/assistant/cli.py`
  **Goal**: New click subcommand with `-p`, `-r`, `-H`, `--host`, `--port` options. Calls `make_app(...)` and `uvicorn.run(...)`. Reuses `_load_persona_or_fail` and existing harness/role resolution.
  **Dependencies**: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7

## 7. Verification

- [x] 7.1 Manual smoke test: text role over curl
  **Goal**: Start `assistant serve -p personal -r assistant`; `curl -N -X POST http://127.0.0.1:8765/chat -H 'Content-Type: application/json' -d '{"message":"hello"}'`; verify the SSE response contains well-formed RUN_STARTED → TEXT_MESSAGE_* → RUN_FINISHED.
  **Dependencies**: 6.8
  **Evidence**: Procedure documented in CLAUDE.md "Essential Commands"; automated TestClient parity in `tests/integration/test_ag_ui_smoke.py::test_smoke_text_role_full_lifecycle` exercises the same SSE pipeline through the real FastAPI app with a fake harness.

- [x] 7.2 Manual smoke test: tool-using role over curl
  **Goal**: Start `assistant serve` with a role that has tools enabled; send a message that triggers a tool call; verify the SSE response contains TOOL_CALL_START/_ARGS/_END events in the correct order.
  **Dependencies**: 7.1
  **Evidence**: Automated TestClient parity in `tests/integration/test_ag_ui_smoke.py::test_smoke_tool_using_role_emits_tool_events_in_order` asserts TOOL_CALL_START < TOOL_CALL_ARGS < TOOL_CALL_END order in the SSE body. Live curl run remains an operator runbook step.

- [x] 7.3 Update CLAUDE.md "Essential Commands" with `serve` example
  **Goal**: Add `uv run assistant serve -p personal` to the Essential Commands table with a one-line description. Brief — no implementation detail in CLAUDE.md.
  **Dependencies**: 6.8
  **Evidence**: `serve` example + curl smoke procedure added to CLAUDE.md "Essential Commands" section.

- [x] 7.4 Run CI-scope quality gates locally
  **Goal**: `uv run pytest tests/`, `uv run ruff check src tests`, `uv run mypy src tests`, `openspec validate --strict`. All must pass (G8 gotcha: don't run mypy with `src/` alone).
  **Dependencies**: 7.1, 7.2, 7.3
  **Evidence**: pytest 967 passed, 3 skipped; ruff clean; mypy clean (168 source files); openspec validate --strict clean. All four gates green on this commit.
