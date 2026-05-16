## Context

This change implements the first slice from `openspec/explore/generative-ui-layer.md` — a transport-only feature that exposes the Deep Agents harness over HTTP/SSE using the AG-UI protocol. No frontend yet; success is verified with `curl -N` against the new endpoint observing well-formed AG-UI events.

The exploration concluded that two open standards should be adopted: **AG-UI** (`ag-ui-protocol/ag-ui`) as the event-based SSE transport, and **OpenUI Lang** as the rendering format inside assistant messages. This change implements only the transport half. OpenUI Lang adoption is deferred to the `openui-lang-rendering` follow-up.

Discovery (Gate-pre) answered three constraining questions:
- **Q1**: Add a new abstract `astream_invoke()` method to `SdkHarnessAdapter` (additive; does not change `invoke()`).
- **Q2**: Startup-time persona/role binding via a new `serve` CLI subcommand (one persona per server process).
- **Q3**: Minimal AG-UI event coverage — lifecycle (RUN_STARTED/FINISHED), text-message streaming (TEXT_MESSAGE_START/_CONTENT/_END), and tool calls (TOOL_CALL_START/_ARGS/_END). No STATE_DELTA, no CUSTOM events in v1.

Gate 1 selected **Approach 2** (separated transport + emitter): a new `src/assistant/transports/ag_ui/` package owns the `HarnessEvent` abstraction and the AG-UI mapper; a new `src/assistant/web/` package serves it over SSE via FastAPI.

The streaming substrate is already wired: the Deep Agents harness uses LangGraph's `InMemorySaver` checkpointer (commit `67795c2`), which exposes `agent.astream()`. This change uses what's already there; no LangGraph upgrade is required.

## Goals / Non-Goals

**Goals:**
- Define a harness-agnostic `HarnessEvent` discriminated union (6 variants for v1).
- Add `SdkHarnessAdapter.astream_invoke()` as an abstract method yielding `HarnessEvent`.
- Implement `astream_invoke()` for the Deep Agents harness by consuming `agent.astream(...)`.
- Implement `astream_invoke()` for the MS Agent Framework harness by consuming `agent.run(messages, stream=True)`.
- Provide an AG-UI emitter that maps `HarnessEvent` to AG-UI protocol events using the upstream `ag_ui` Python package.
- Mount a FastAPI app with a single SSE endpoint that consumes the emitter and serves AG-UI events.
- Add a `serve` CLI subcommand that mounts the app with startup-time persona/role binding.
- All quality gates pass: `pytest tests/`, `ruff check src tests`, `mypy src tests`, `openspec validate --strict`.

**Non-Goals:**
- Any browser frontend, OpenUI Lang rendering, or web UI code.
- Multi-persona-per-server, multi-tenancy, or auth beyond loopback binding.
- AG-UI event types beyond the minimal set (no STATE_DELTA, no CUSTOM, no step events).
- Adopting Microsoft's `agent_framework_ag_ui` integration (broken in current venv and would fragment the harness boundary — see D10).
- Thread-id surfacing in HTTP requests (one thread per server process; clients cannot resume conversations across server restarts in v1).
- WebSocket transport (SSE only for v1).
- Production-grade error semantics (rate limiting, retry, backpressure beyond what `sse-starlette` provides natively).

## Decisions

### D1: HarnessEvent variant set — 6 variants, locked for v1

The `HarnessEvent` discriminated union has exactly six variants in v1, named to be harness-agnostic and protocol-agnostic:

```python
HarnessEvent = (
    RunStarted        # opaque run-id, start timestamp
    | RunFinished     # run-id, end timestamp, optional error
    | TextDelta       # message-id, partial text chunk
    | ToolCallStart   # call-id, tool name
    | ToolCallArgs    # call-id, partial JSON args chunk
    | ToolCallEnd     # call-id, optional result
)
```

**Rationale.** This is the smallest set that satisfies the discovery answer Q3 (lifecycle + text + tools) and the AG-UI v0.x event categories in scope. Field names avoid LangChain-isms (e.g., `text` not `content` because AG-UI uses `content` for something else; `tool_name` not LangChain's `tool_call_id` because the latter is more like our `call_id`).

**Alternatives considered.** (a) Reuse LangChain's `StreamEvent` directly — rejected because it leaks LangChain into the harness contract (Approach 3's flaw). (b) Reuse AG-UI's event types directly — rejected because it couples the harness to a specific transport protocol (we want WebSocket or stdio to be addable without harness changes).

**Forward-compatibility.** Adding new variants later is non-breaking for consumers that use exhaustive `match` with a wildcard arm. Removing or renaming variants would be breaking; we won't do that without a versioned migration.

### D2: SSE framing via `sse-starlette`

Use `sse-starlette` as the SSE response helper rather than a DIY response generator.

**Rationale.** `sse-starlette` is well-tested, handles `Content-Type`, `Cache-Control: no-cache`, comment heartbeats, and disconnect detection correctly. Approximately 30 lines of code we don't have to write or test. Adds one dependency — acceptable.

**Alternatives considered.** (a) DIY `StreamingResponse` with manual `data:`/`event:` framing — rejected because the disconnect-detection logic is error-prone and would require its own tests. (b) FastAPI's built-in `StreamingResponse` with no framing helper — same problem as (a).

### D3: Startup-time persona binding via FastAPI lifespan

Use FastAPI's `lifespan` async context manager to construct the persona, role, and harness exactly once at server startup. Stash the harness adapter on `app.state.harness`. All `/chat` requests use the same harness instance.

**Rationale.** Matches the CLI mental model (one persona per process). The harness already manages thread_id internally (per-instance), so one server process = one conversation thread. Lifespan is the idiomatic FastAPI pattern for this.

**Alternatives considered.** (a) Construct harness per-request — rejected because it loses conversation memory (each request would get a fresh thread_id, defeating the point of `InMemorySaver`). (b) Module-level singleton — rejected because it bypasses FastAPI's lifecycle and is harder to test.

### D4: One thread_id per server process; not surfaced to clients in v1

In v1, the server has exactly one conversation thread. Clients cannot pass a `thread_id`; the server uses the harness's internal `_thread_id` for every request.

**Rationale.** Matches the "single user" constraint (C4 in exploration doc). Multi-conversation support — including resuming threads across server restarts — is a natural follow-up but not a v1 requirement. Designing for it now would require persistence (the `InMemorySaver` is in-memory only).

**Forward path.** When multi-conversation arrives, the endpoint gains an optional `thread_id` query parameter or header; the harness gains a `with_thread_id()` factory or per-call override; the `InMemorySaver` is replaced with a `SqlSaver`. None of these break the AG-UI event format or the `serve` CLI.

### D5: AG-UI Python types — use the upstream `ag_ui` package directly

Resolved during plan revision (2026-05-16): the upstream `ag_ui` Python package is confirmed installed in the current venv. Its `ag_ui.core` submodule provides every event class the v1 minimal scope needs as Pydantic models:

- `RunStartedEvent`, `RunFinishedEvent`, `RunErrorEvent`
- `TextMessageStartEvent`, `TextMessageContentEvent`, `TextMessageEndEvent`, `TextMessageChunkEvent`
- `ToolCallStartEvent`, `ToolCallArgsEvent`, `ToolCallEndEvent`, `ToolCallChunkEvent`
- `EventType` enum with string values matching the v0.x protocol spec

`src/assistant/transports/ag_ui/types.py` becomes a thin re-export shim from `ag_ui.core` (no in-repo Pydantic definitions). Add `ag-ui` to `pyproject.toml` dependencies with a permissive version range and pin in `uv.lock`.

**Rationale.** Spec conformance for free; ~80 lines of Pydantic we don't have to write or test; transparent upgrade path when AG-UI v1.0 lands. The original "ship in-repo fallback" option is no longer needed.

**Alternatives considered.** (a) Ship in-repo Pydantic types — rejected because the upstream package exists and works. (b) Reuse the type definitions from inside `agent_framework_ag_ui` — rejected because that package is broken in the current venv (see D10), so re-exporting from it would be fragile.

### D6: Module boundary discipline

```
src/assistant/harnesses/
├── base.py                             # add abstract astream_invoke()
├── sdk/
│   ├── base.py                         # SdkHarnessAdapter (extends HarnessAdapter)
│   ├── events.py                       # HarnessEvent discriminated union (6 variants)
│   ├── deep_agents.py                  # implement astream_invoke()
│   └── ms_agent_fw.py                  # implement astream_invoke()

src/assistant/transports/ag_ui/        # transport-agnostic AG-UI mapper
├── __init__.py
├── types.py                            # AG-UI event Pydantic models (re-exported from ag_ui.core)
└── mapper.py                           # map_harness_to_ag_ui(stream, *, thread_id) -> AsyncIterator[AGUIEvent]

src/assistant/web/                      # HTTP-specific
├── __init__.py
├── app.py                              # FastAPI factory: make_app(persona, role, harness) -> FastAPI
└── routes.py                           # /chat SSE endpoint handler
```

**Rule.** Imports flow strictly downward: `web/` → `transports/ag_ui/` → `harnesses/sdk/`. Nothing in `harnesses/` may import from `transports/` or `web/`. Nothing in `transports/ag_ui/` may import from `web/` or know about HTTP. Nothing in `web/` may import LangChain types directly — it only sees `AGUIEvent` from the transport layer.

**`HarnessEvent` placement.** The discriminated union lives in `harnesses/sdk/events.py` rather than `transports/ag_ui/events.py` because the harnesses themselves *construct* `HarnessEvent` instances inside `astream_invoke()`. Placing it in the transport layer would force harness implementations to import upward into `transports/`, violating the import-direction rule. The transport layer imports `HarnessEvent` from the harness layer (the natural direction: transports consume what harnesses produce). Enforced by code review for v1; could be enforced by `ruff` `isort` rules or `import-linter` later if useful.

### D7: Testing strategy — three layers

1. **Unit tests for `mapper.py`** (`tests/transports/ag_ui/test_mapper.py`): feed canned `HarnessEvent` async iterators, assert the emitted AG-UI events match expectations. No network, no harness. Fastest layer.
2. **HTTP endpoint tests** (`tests/web/test_chat_endpoint.py`): use FastAPI's `TestClient` (which is `httpx.Client` under the hood) plus a fake harness that yields canned `HarnessEvent` streams. Assert the SSE response framing, event ordering, error paths. No real LLM.
3. **Streaming harness tests** (`tests/harnesses/test_deep_agents_astream.py`): exercise `DeepAgentsHarness.astream_invoke()` against a fake LangGraph agent whose `astream` yields canned chunks. Assert correct mapping of LangChain `astream` events to `HarnessEvent` variants.

No end-to-end test against a real LLM in CI — that's reserved for manual `curl -N` smoke testing during validation (the success criterion in the proposal).

### D8: Error mapping in v1 — two-phase error contract, class-name-only redaction

When the harness encounters an exception during `astream_invoke()`, error semantics flow in **two distinct phases** that the harness, the mapper, the `@traced_harness` decorator, and the HTTP layer all observe:

**Phase 1 — event stream.** The harness MUST yield a terminal `RunFinished(error=<ClassName>)` event before the generator terminates abnormally. This is the user-facing protocol-level error signal. The `error` field is populated with the exception's **class name only** (e.g., `"RuntimeError"`, `"PermissionError"`) — never the message body, never a traceback, never any nested-exception detail.

**Phase 2 — exception propagation.** Immediately after yielding the Phase 1 terminal event, the harness MUST re-raise the **original** exception unchanged (no wrapping, no message rewriting). The `@traced_harness` decorator catches it for observability (sets `metadata["error"]=ClassName`) and re-raises so the caller can take operational action (close connection, log full traceback server-side).

**Mapper behavior.** The AG-UI mapper, on receiving the Phase 1 terminal `RunFinished`, emits exactly one `RUN_FINISHED` AG-UI event with `error` field set to the same class name. When the upstream iterator subsequently raises (Phase 2), the mapper **catches and absorbs** the exception, MUST NOT emit any additional events, and terminates its own iterator cleanly. The SSE handler that consumes the mapper sees a clean end-of-stream after `RUN_FINISHED`. The exception is recorded server-side via `@traced_harness` and via the FastAPI exception logger; it does not escape the response generator.

**Redaction rule (explicit).** The class-name pattern is `^[A-Z][A-Za-z0-9_.]*$` (Python class identifier with optional dotted qualifier). This redaction prevents leakage of file paths, environment-variable values, secret-bearing exception messages (e.g., a wrapped LangChain exception that included an API key fragment), and stack-frame implementation details. The full exception with traceback is logged server-side at ERROR level for debugging.

**Rationale.** A single-phase model (only yield, never raise — or only raise, never yield) was rejected because each loses an essential property: yield-only leaves `@traced_harness` blind to the failure (it sees a normal generator return), while raise-only leaves the mapper synthesizing a terminal event it never directly produced, opening duplicate-event and event-ordering corner cases. The two-phase contract satisfies all four obligations simultaneously: well-formed AG-UI event stream, observable exception for tracing, no duplicate terminal events, no client leakage.

**Forward path.** If AG-UI v1.x adds a dedicated error event type with structured error-category fields, we adopt that. Until then, class name in `RUN_FINISHED.error` is the canonical detail level.

### D9: Use the existing `@traced_harness` decorator on `astream_invoke()` too

The `Requirement: Harness Invocation Emits Observability Span` in the existing `harness-adapter` spec requires `@traced_harness` on every concrete `invoke()`. We apply the same decorator to the new `astream_invoke()` method.

**Rationale.** Streaming invocations should also emit observability spans — otherwise the new code path is invisible to tracing. The decorator already handles success and exception paths; we extend it (or add a streaming variant) to handle async generators correctly.

**Risk.** The current `@traced_harness` decorator wraps a coroutine returning `str`. An async generator has a different shape — the decorator implementation MUST be updated to dispatch on the wrapped function's coroutine-vs-async-generator kind. This is a small but non-trivial change to `observability` (or wherever the decorator lives); tasks.md tracks it explicitly.

### D10: `agent_framework_ag_ui` acknowledged but unused in v1

Microsoft's `agent-framework-ag-ui` package (installed as `agent_framework_ag_ui`) ships `add_agent_framework_fastapi_endpoint`, `AgentFrameworkAgent`, `AGUIChatClient`, and `AGUIEventConverter`. On paper, it could replace the entire MSAF-side of this change. We chose not to adopt it in v1 for two reasons:

1. **Broken in current venv.** Importing it raises `ImportError: cannot import name 'SupportsAgentRun' from 'agent_framework'`. The root cause is the documented v1.0.1 namespace-package quirk (see `CLAUDE.md` "What's Not Yet Wired" — the meta package's `__init__.py` is empty because multiple connector packages race to claim the namespace; submodule imports succeed but top-level re-exports fail). The MSAF harness already works around this with lazy imports inside method bodies; `agent_framework_ag_ui._agent` does a top-level import and therefore breaks.
2. **Fragments the harness boundary.** Adopting it for MSAF and keeping our custom emitter for DeepAgents would produce two distinct AG-UI emission paths, one per harness. The transport surface for the two harnesses would diverge in subtle ways (Microsoft's encoder vs. ours), making frontend integration harder to reason about.

**Rationale for revisiting later.** When upstream `agent-framework` v1.x repairs the namespace-package shape (or we pin `agent-framework-core` directly), `agent_framework_ag_ui` becomes usable. At that point a follow-up may evaluate whether to switch MSAF over to Microsoft's path — at the cost of the asymmetry above. The benefit would be one less Pydantic translation layer.

**Decisive factor.** The current uniform path (HarnessEvent → AG-UI via our mapper) preserves the architectural principle from Approach 2 (the harness boundary as the seam) AND works today. Microsoft's path is not yet a viable shortcut.

### D11: MSAF `AgentResponseUpdate` → `HarnessEvent` translation

`agent_framework.Agent.run(messages, stream=True)` returns a `ResponseStream[AgentResponseUpdate, AgentResponse[Any]]`. Iterating yields `AgentResponseUpdate` instances. Our MSAF `astream_invoke` translates each update to one or more `HarnessEvent` variants per the following table:

| AgentResponseUpdate carries | Emit HarnessEvent |
|---|---|
| First update of a new run | `RunStarted(run_id, started_at)` (synthesized once, before the first update) |
| Text content delta on `.text` / `.content` / `.delta` (whichever the SDK exposes) | `TextDelta(message_id, text)` — `message_id` is stable across all text updates within one message |
| Tool invocation start (presence of new `tool_call_id` / `tool_calls` entry) | `ToolCallStart(call_id, tool_name)` |
| Tool args delta | `ToolCallArgs(call_id, args_chunk)` |
| Tool call complete | `ToolCallEnd(call_id, result=optional)` |
| Stream exhausted normally | `RunFinished(run_id, finished_at, error=None)` |
| Exception raised mid-stream | `RunFinished(run_id, finished_at, error=<class name>)` then close |

**Rationale.** Mirrors the Deep Agents translation table (which exists implicitly in the LangChain `astream` event types). Keeps the two harnesses' `HarnessEvent` output indistinguishable downstream — the AG-UI emitter cannot tell which harness produced a given event. Implementation will defensively use `getattr(update, ..., None)` with fallbacks since the SDK's `AgentResponseUpdate` shape has churned between minor versions (see `_stringify_run_result` in the existing MSAF harness, which already pattern-matches three different shapes).

**Risk.** SDK shape drift across `agent-framework` minor versions. Tests pin the expected shape to the SDK version in `pyproject.toml`. The same `_stringify_run_result`-style defensive coding pattern is reused for streaming.

### D12: Auth posture — loopback-only by default; non-loopback binding warns but does not require auth

The server binds to `127.0.0.1` by default (D6, web-server spec "Server Loopback Binding by Default"). When the operator explicitly passes `--host 0.0.0.0` (or any non-loopback address), the server prints a clearly-visible warning on stderr identifying that the server will be network-accessible *without* authentication, but the server still starts.

**Rationale.** v1 is explicitly single-user local-trust-mode (constraint C4 from the exploration doc). Adding mandatory authentication middleware for non-loopback binding would: (a) require introducing an auth scheme (bearer token, OAuth, mTLS) that has no use case in v1; (b) complicate the FastAPI app for a future case ("multi-user network deployment") that's explicitly deferred to a separate change; (c) provide a false sense of security if the operator binds to `0.0.0.0` thinking auth protects them — local-network listeners with bearer tokens are still trivially scannable. The warning gives operators a clear signal about the deployment posture without adding code that would need to be maintained or replaced when real auth lands.

**Alternatives considered.** (a) Refuse to start on non-loopback unless `--auth-token` is supplied — rejected because it surprises operators who legitimately want to expose the loopback over SSH-forwarded ports (`ssh -L 8765:127.0.0.1:8765`) and still bind to `0.0.0.0` inside a container. (b) Mandatory auth middleware — rejected per Non-Goals (auth is a separate v2 concern). (c) Silent allow — rejected because the deployment-posture signal is genuinely important and cheap to emit.

**Forward path.** When v2 introduces multi-user or remote-access scenarios, a dedicated auth design decision lands then; this D12 warning becomes a refuse-without-auth-token check at that point.

### D13: Trust `sse-starlette` for backpressure and disconnect detection

The mapper (`map_harness_to_ag_ui`) is an async generator. The web layer wraps it with `sse-starlette.EventSourceResponse`, which handles: (a) SSE framing (event-id, data:, retry hints), (b) disconnect detection (sets a `request.is_disconnected()` flag the response generator can check), (c) basic backpressure via its internal queue.

We do not add custom backpressure logic, custom rate limiting, or custom connection-count guards in v1. The loopback-only default + single-user constraint makes these explicit non-goals.

**Rationale.** `sse-starlette` is mature on this surface. Building parallel backpressure logic in v1 would be over-engineering for the documented scope. If the future Tauri + web frontend exposes the server to high-rate clients, those concerns get a dedicated design decision then.

**Client-disconnect contract.** When `sse-starlette` reports the client disconnected (via `request.is_disconnected()` or by the underlying ASGI connection closing), the response handler must call `aclose()` on the harness's async-iterator return value so any open resources are released. The harness `astream_invoke` implementations MUST handle `GeneratorExit` cleanly (release locks, close any open SDK streams, do not emit further events). Tests for this scenario are added in the web-server spec and tasks.md.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| LangChain `astream` event vocabulary may evolve | LangGraph v0.x is mature on this surface; pin LangGraph version in `pyproject.toml`; freeze the mapper logic against an explicit list of event types we handle |
| `agent_framework.AgentResponseUpdate` shape drifts across SDK versions | D11 mitigation: defensive `getattr` with fallbacks (mirrors existing `_stringify_run_result` pattern); pytest fixtures pin shape to installed SDK version |
| `HarnessEvent` shape may need adjustment as new harnesses arrive | Variants are minimal and protocol-agnostic; D1's exhaustive-match pattern makes new variants additive |
| `@traced_harness` decorator may not handle async generators correctly | D9-noted; tasks.md adds explicit step to extend the decorator with tests |
| Single-user assumption bakes in single-thread-per-process | D4-acknowledged; documented forward path; not a v1 problem |
| Discoverability of the new `serve` command | Update `--help` output for the CLI; mention in CLAUDE.md "Essential Commands" |
| SSE proxy/firewall buffering may break streaming | Loopback-only binding in v1 sidesteps this; document for future Tauri deployment |
| FastAPI / uvicorn add ~5 new transitive deps | Acceptable; both are mature, well-maintained |
| `agent_framework_ag_ui` upstream namespace fix lands and changes the right move | D10 acknowledges the option; follow-up evaluates re-adoption after the SDK's namespace quirk is resolved |

## Migration Plan

This is an additive change. No migration is required for existing CLI users — `assistant run -p personal` works exactly as before. The new `assistant serve ...` subcommand is opt-in. Rollback is `git revert`.

For implementers of new SDK harnesses (e.g., the future MSAF implementation), the abstract `astream_invoke()` method becomes a required override. The MSAF harness currently stubs `invoke()` with `NotImplementedError`; the stub for `astream_invoke()` should match that pattern until MSAF is fully implemented.

## Open Questions

These are deferred to implementation time, not blockers for plan approval:

1. **Exact LangChain `astream` event names to filter.** LangGraph emits many event types (on_chain_start, on_llm_stream, on_tool_start, etc.); the mapper needs to know which to translate and which to drop. Resolved during Task 3.x (DeepAgents mapper implementation) by writing tests against the canonical event set the Deep Agents harness produces.
2. **Exact shape of `agent_framework.AgentResponseUpdate` for the installed SDK version.** D11 lays out the conceptual mapping; the exact attribute names (`.text` vs `.content` vs `.delta`) are resolved during Task 3b.x (MSAF mapper implementation) by reading the SDK source and writing fixture-driven tests.
3. **Whether `--host` defaults to `127.0.0.1` or `localhost`.** Both work; `127.0.0.1` avoids IPv6 dual-stack confusion on some macOS configurations. Resolved during Task 5.x (CLI subcommand implementation).
4. **Whether `Content-Type: text/event-stream` should include `; charset=utf-8`.** RFC 6455 doesn't require it; some clients prefer it; `sse-starlette` likely handles this. Resolved during Task 4.x (HTTP layer).
