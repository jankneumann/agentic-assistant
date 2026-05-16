## 1. Foundation — Dependencies and HarnessEvent

- [ ] 1.1 Audit AG-UI Python package availability
  **Goal**: Resolve design Open Question 1 / D5. Run `uv pip install --dry-run` against `ag-ui-protocol`, `ag-ui`, `ag-ui-core`, `agui` to determine which is installable. Document the choice (use upstream OR ship in-repo types).
  **Spec scenarios**: (none — pre-implementation research)
  **Contracts**: (none)
  **Design decisions**: D5
  **Dependencies**: None

- [ ] 1.2 Write tests for HarnessEvent discriminated union
  **Spec scenarios**: harness-adapter "HarnessEvent variants are exhaustive for v1", "RunStarted carries an opaque run identifier", "TextDelta carries partial text chunks", "Tool call lifecycle events share a call_id"
  **Contracts**: contracts/events/harness-event.schema.json
  **Design decisions**: D1
  **Dependencies**: 1.1

- [ ] 1.3 Implement `src/assistant/transports/ag_ui/events.py`
  **Goal**: Define `HarnessEvent` discriminated union (Pydantic) with the 6 variants: RunStarted, RunFinished, TextDelta, ToolCallStart, ToolCallArgs, ToolCallEnd. Field names must be harness-agnostic and protocol-agnostic per D1.
  **Dependencies**: 1.2

- [ ] 1.4 Add runtime + dev dependencies to `pyproject.toml`
  **Goal**: Add `fastapi`, `uvicorn[standard]`, `sse-starlette`. Conditionally add `ag-ui-protocol` (or chosen variant) if 1.1 found one usable. Run `uv sync` and verify the lockfile diff is sane.
  **Dependencies**: 1.1

## 2. Harness Interface Evolution

- [ ] 2.1 Write tests for `SdkHarnessAdapter.astream_invoke` abstract signature
  **Spec scenarios**: harness-adapter "SdkHarnessAdapter.astream_invoke returns async iterator of HarnessEvent"
  **Design decisions**: D1
  **Dependencies**: 1.3

- [ ] 2.2 Add abstract `astream_invoke` to `src/assistant/harnesses/base.py`
  **Goal**: Add abstract method to `SdkHarnessAdapter` returning `AsyncIterator[HarnessEvent]`. Existing `invoke()` MUST remain unchanged. MSAgentFrameworkHarness must keep working — stub `astream_invoke` with `NotImplementedError` matching existing pattern (until MSAF is fully implemented in a later change).
  **Dependencies**: 2.1

- [ ] 2.3 Write tests for `@traced_harness` async-generator support
  **Spec scenarios**: harness-adapter "Deep Agents astream_invoke is traced on success", "Deep Agents astream_invoke is traced on exception"
  **Design decisions**: D9
  **Dependencies**: 2.2

- [ ] 2.4 Extend `@traced_harness` decorator to dispatch on coroutine vs async-generator
  **Goal**: Detect whether the wrapped function returns a coroutine or an async generator. For generators, measure duration across full consumption (success) or until the exception escapes (failure). Emit `trace_llm_call` exactly once in either case. Add `streaming=True` to metadata for the generator path per D9.
  **Dependencies**: 2.3

## 3. Deep Agents Streaming Implementation

- [ ] 3.1 Write tests for `DeepAgentsHarness.astream_invoke` lifecycle bracketing
  **Spec scenarios**: harness-adapter "astream_invoke emits RunStarted then RunFinished"
  **Design decisions**: D1, D7
  **Dependencies**: 2.2

- [ ] 3.2 Write tests for thread_id propagation in streaming path
  **Spec scenarios**: harness-adapter "astream_invoke passes thread_id to LangGraph"
  **Design decisions**: D3, D4
  **Dependencies**: 2.2

- [ ] 3.3 Write tests for LangChain text-chunk → TextDelta mapping
  **Spec scenarios**: harness-adapter "astream_invoke translates LangChain text chunks to TextDelta"
  **Design decisions**: D1
  **Dependencies**: 2.2

- [ ] 3.4 Write tests for tool-call lifecycle translation
  **Spec scenarios**: harness-adapter "astream_invoke translates tool calls to lifecycle events"
  **Design decisions**: D1
  **Dependencies**: 2.2

- [ ] 3.5 Write tests for error propagation (harness exception → terminal RunFinished with error)
  **Spec scenarios**: harness-adapter "astream_invoke emits RunFinished with error on exception"
  **Design decisions**: D8
  **Dependencies**: 2.2

- [ ] 3.6 Implement `DeepAgentsHarness.astream_invoke` in `src/assistant/harnesses/sdk/deep_agents.py`
  **Goal**: Consume `agent.astream(...)` with the existing `_thread_id`; translate LangChain stream events into `HarnessEvent` variants. Open question: exact LangChain event names to filter — resolve by writing the implementation against an explicit allowlist. Apply `@traced_harness` decorator.
  **Dependencies**: 3.1, 3.2, 3.3, 3.4, 3.5, 2.4

## 4. AG-UI Emitter

- [ ] 4.1 Write tests for v1-scoped event type coverage
  **Spec scenarios**: ag-ui-emitter "Emitter produces only the v1-scoped event types", "Each emitted event conforms to the AG-UI v0.x schema"
  **Contracts**: contracts/events/ag-ui-events.schema.json
  **Design decisions**: D5
  **Dependencies**: 1.3

- [ ] 4.2 Write tests for HarnessEvent → AG-UI event mapping
  **Spec scenarios**: ag-ui-emitter "RunStarted maps to RUN_STARTED", "TextDelta maps to TEXT_MESSAGE_CONTENT framed by START/END", "Tool call lifecycle maps to TOOL_CALL_* events", "RunFinished maps to RUN_FINISHED"
  **Contracts**: contracts/events/ag-ui-events.schema.json, contracts/events/harness-event.schema.json
  **Design decisions**: D1, D6
  **Dependencies**: 1.3

- [ ] 4.3 Write tests for run lifecycle event ordering invariants
  **Spec scenarios**: ag-ui-emitter "RUN_STARTED precedes all content events", "TEXT_MESSAGE_END closes a message on message-id boundary", "TOOL_CALL_END terminates a call lifecycle"
  **Design decisions**: D1
  **Dependencies**: 1.3

- [ ] 4.4 Write tests for error mapping to terminal RUN_FINISHED
  **Spec scenarios**: ag-ui-emitter "Harness exception surfaces as RUN_FINISHED with error", "RunFinished with error field is forwarded faithfully"
  **Design decisions**: D8
  **Dependencies**: 1.3

- [ ] 4.5 Implement `src/assistant/transports/ag_ui/types.py`
  **Goal**: AG-UI event Pydantic models for the 8 v1-scoped event types. If 1.1 found a usable upstream package, this file is a thin re-export shim; if not, define the types in-repo against the AG-UI v0.x spec.
  **Design decisions**: D5
  **Dependencies**: 1.1, 4.1

- [ ] 4.6 Implement `src/assistant/transports/ag_ui/mapper.py`
  **Goal**: `async def map_harness_to_ag_ui(stream: AsyncIterator[HarnessEvent]) -> AsyncIterator[AGUIEvent]`. Streaming, deterministic, no full-stream buffering. Owns the TEXT_MESSAGE_START/END and TOOL_CALL_START/END bracketing logic per the ordering invariants.
  **Dependencies**: 4.2, 4.3, 4.4, 4.5

## 5. FastAPI Application + SSE Endpoint

- [ ] 5.1 Write tests for `/chat` endpoint content-type
  **Spec scenarios**: web-server "POST /chat returns text/event-stream content type"
  **Contracts**: contracts/openapi/v1.yaml
  **Design decisions**: D2, D6
  **Dependencies**: 1.4

- [ ] 5.2 Write tests for `/chat` response body containing AG-UI events
  **Spec scenarios**: web-server "Response body contains AG-UI events"
  **Contracts**: contracts/openapi/v1.yaml, contracts/events/ag-ui-events.schema.json
  **Design decisions**: D2, D7
  **Dependencies**: 1.4

- [ ] 5.3 Write tests for request validation (422 on malformed bodies)
  **Spec scenarios**: web-server "Endpoint rejects non-JSON or malformed request bodies"
  **Contracts**: contracts/openapi/v1.yaml
  **Dependencies**: 1.4

- [ ] 5.4 Write tests for harness-error path emitting terminal RUN_FINISHED
  **Spec scenarios**: web-server "Endpoint emits RUN_FINISHED with error when harness fails"
  **Design decisions**: D8
  **Dependencies**: 4.6

- [ ] 5.5 Write tests for lifespan single-harness construction at startup
  **Spec scenarios**: web-server "Lifespan constructs a single harness at startup"
  **Design decisions**: D3
  **Dependencies**: 1.4

- [ ] 5.6 Write tests for shared harness instance across requests
  **Spec scenarios**: web-server "All requests share the same harness instance"
  **Design decisions**: D3, D4
  **Dependencies**: 1.4

- [ ] 5.7 Write tests for lifespan rejecting host harnesses
  **Spec scenarios**: web-server "Lifespan rejects host harnesses"
  **Dependencies**: 1.4

- [ ] 5.8 Write tests for `/health` endpoint
  **Spec scenarios**: web-server "Health check returns persona, role, harness identity", "Health check does not invoke the harness"
  **Contracts**: contracts/openapi/v1.yaml
  **Dependencies**: 1.4

- [ ] 5.9 Implement `src/assistant/web/app.py` — FastAPI factory `make_app(persona, role, harness_name) -> FastAPI`
  **Goal**: App factory with lifespan that constructs harness once and stores on `app.state.harness`. Reject host harnesses in lifespan.
  **Dependencies**: 5.5, 5.6, 5.7

- [ ] 5.10 Implement `src/assistant/web/routes.py` — `/chat` (SSE) and `/health` (JSON)
  **Goal**: `/chat` calls `app.state.harness.astream_invoke(...)`, pipes through `map_harness_to_ag_ui`, serves as SSE via `sse-starlette`. `/health` returns persona/role/harness identity without touching the harness.
  **Dependencies**: 5.1, 5.2, 5.3, 5.4, 5.8, 5.9, 4.6, 3.6

## 6. CLI serve Subcommand

- [ ] 6.1 Write tests for `serve` startup binding persona/role
  **Spec scenarios**: cli-interface "serve binds the supplied persona and role at startup"
  **Dependencies**: 5.9

- [ ] 6.2 Write tests for default host (127.0.0.1)
  **Spec scenarios**: cli-interface "serve defaults host to 127.0.0.1", web-server "Default bind is loopback", "Explicit --host overrides default"
  **Design decisions**: D6 (loopback per privacy default)
  **Dependencies**: 5.9

- [ ] 6.3 Write tests for `default_role` fallback when `-r` omitted
  **Spec scenarios**: cli-interface "serve uses persona default_role when -r is omitted"
  **Dependencies**: 5.9

- [ ] 6.4 Write tests for unknown persona handling
  **Spec scenarios**: cli-interface "serve rejects unknown personas with non-zero exit"
  **Dependencies**: 5.9

- [ ] 6.5 Write tests for host-harness rejection at CLI boundary
  **Spec scenarios**: cli-interface "serve rejects host harness names"
  **Dependencies**: 5.9

- [ ] 6.6 Write tests for clean Ctrl-C exit (status 0)
  **Spec scenarios**: cli-interface "Ctrl-C exits with status 0"
  **Dependencies**: 5.9

- [ ] 6.7 Write tests for `--help` mentioning `serve`
  **Spec scenarios**: cli-interface "Serve subcommand is registered in the CLI group"
  **Dependencies**: 5.9

- [ ] 6.8 Implement `serve` subcommand in `src/assistant/cli.py`
  **Goal**: New click subcommand with `-p`, `-r`, `-H`, `--host`, `--port` options. Calls `make_app(...)` and `uvicorn.run(...)`. Reuses `_load_persona_or_fail` and existing harness/role resolution.
  **Dependencies**: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7

## 7. Verification

- [ ] 7.1 Manual smoke test: text role over curl
  **Goal**: Start `assistant serve -p personal -r assistant`; `curl -N -X POST http://127.0.0.1:8765/chat -H 'Content-Type: application/json' -d '{"message":"hello"}'`; verify the SSE response contains well-formed RUN_STARTED → TEXT_MESSAGE_* → RUN_FINISHED.
  **Dependencies**: 6.8

- [ ] 7.2 Manual smoke test: tool-using role over curl
  **Goal**: Start `assistant serve` with a role that has tools enabled; send a message that triggers a tool call; verify the SSE response contains TOOL_CALL_START/_ARGS/_END events in the correct order.
  **Dependencies**: 7.1

- [ ] 7.3 Update CLAUDE.md "Essential Commands" with `serve` example
  **Goal**: Add `uv run assistant serve -p personal` to the Essential Commands table with a one-line description. Brief — no implementation detail in CLAUDE.md.
  **Dependencies**: 6.8

- [ ] 7.4 Run CI-scope quality gates locally
  **Goal**: `uv run pytest tests/`, `uv run ruff check src tests`, `uv run mypy src tests`, `openspec validate --strict`. All must pass (G8 gotcha: don't run mypy with `src/` alone).
  **Dependencies**: 7.1, 7.2, 7.3
