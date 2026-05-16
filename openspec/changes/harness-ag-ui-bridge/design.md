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
- Provide an AG-UI emitter that maps `HarnessEvent` to AG-UI protocol events.
- Mount a FastAPI app with a single SSE endpoint that consumes the emitter and serves AG-UI events.
- Add a `serve` CLI subcommand that mounts the app with startup-time persona/role binding.
- All quality gates pass: `pytest tests/`, `ruff check src tests`, `mypy src tests`, `openspec validate --strict`.

**Non-Goals:**
- Any browser frontend, OpenUI Lang rendering, or web UI code.
- Multi-persona-per-server, multi-tenancy, or auth beyond loopback binding.
- AG-UI event types beyond the minimal set (no STATE_DELTA, no CUSTOM, no step events).
- MSAF harness `astream_invoke()` implementation (out of scope until MSAF is real).
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

### D5: AG-UI Python types — use `ag-ui-protocol` PyPI package if available; else minimal in-repo types

The implementation should first check whether `ag-ui-protocol` (or equivalent) is available on PyPI with a stable v0.x release. If yes, depend on it. If not, define the minimal AG-UI event types in `src/assistant/transports/ag_ui/types.py` as Pydantic models matching the v0.x spec.

**Rationale.** Using the upstream package gives us spec-conformance for free. But if there's no Python implementation yet (or it's pre-alpha), an in-repo types module is small (~6 Pydantic classes for the v1 minimal set) and unambiguous. We tolerate the spec-drift risk because v0.x is pre-1.0 and AG-UI is small enough to track manually.

**Verification step (implementation time).** Before adding `pyproject.toml` deps, run `uv pip install --dry-run ag-ui-protocol` (and any plausible variant names: `ag-ui`, `ag-ui-core`, `agui`) to confirm what's installable. If nothing is, ship the in-repo types module.

### D6: Module boundary discipline

```
src/assistant/transports/ag_ui/        # transport-agnostic AG-UI mapper
├── __init__.py
├── types.py                            # AG-UI event Pydantic models (or shim if PyPI package)
├── events.py                           # HarnessEvent discriminated union
└── mapper.py                           # map_harness_to_ag_ui(stream) -> AsyncIterator[AGUIEvent]

src/assistant/web/                      # HTTP-specific
├── __init__.py
├── app.py                              # FastAPI factory: make_app(persona, role, harness) -> FastAPI
└── routes.py                           # /chat SSE endpoint handler

src/assistant/harnesses/
├── base.py                             # add abstract astream_invoke()
└── sdk/deep_agents.py                  # implement astream_invoke()
```

**Rule.** Nothing in `harnesses/` may import from `transports/` or `web/`. Nothing in `transports/ag_ui/` may import from `web/` or know about HTTP. Nothing in `web/` may import LangChain types directly — it only sees `AGUIEvent` from the transport layer. Enforced by code review for v1; could be enforced by `ruff` `isort` rules or `import-linter` later if useful.

### D7: Testing strategy — three layers

1. **Unit tests for `mapper.py`** (`tests/transports/ag_ui/test_mapper.py`): feed canned `HarnessEvent` async iterators, assert the emitted AG-UI events match expectations. No network, no harness. Fastest layer.
2. **HTTP endpoint tests** (`tests/web/test_chat_endpoint.py`): use FastAPI's `TestClient` (which is `httpx.Client` under the hood) plus a fake harness that yields canned `HarnessEvent` streams. Assert the SSE response framing, event ordering, error paths. No real LLM.
3. **Streaming harness tests** (`tests/harnesses/test_deep_agents_astream.py`): exercise `DeepAgentsHarness.astream_invoke()` against a fake LangGraph agent whose `astream` yields canned chunks. Assert correct mapping of LangChain `astream` events to `HarnessEvent` variants.

No end-to-end test against a real LLM in CI — that's reserved for manual `curl -N` smoke testing during validation (the success criterion in the proposal).

### D8: Error mapping in v1 — emit RUN_FINISHED with error, then close stream

If the harness raises during `astream_invoke()`, the AG-UI emitter catches the exception, emits a `RUN_FINISHED` event with an `error` field populated, and closes the SSE stream cleanly (no further events). The HTTP layer also logs the exception with full traceback.

**Rationale.** AG-UI v0.x has no dedicated error event in our minimal scope (D3 answer to Q3 excluded CUSTOM events). Stuffing the error into `RUN_FINISHED.error` keeps the stream well-formed and lets clients detect failure without protocol drift. Logs preserve the full traceback for debugging.

**Forward path.** If AG-UI v1.x adds a dedicated error event type, we adopt it then. Until then, this is the right level of pragmatism for v1.

### D9: Use the existing `@traced_harness` decorator on `astream_invoke()` too

The `Requirement: Harness Invocation Emits Observability Span` in the existing `harness-adapter` spec requires `@traced_harness` on every concrete `invoke()`. We apply the same decorator to the new `astream_invoke()` method.

**Rationale.** Streaming invocations should also emit observability spans — otherwise the new code path is invisible to tracing. The decorator already handles success and exception paths; we extend it (or add a streaming variant) to handle async generators correctly.

**Risk.** The current `@traced_harness` decorator wraps a coroutine returning `str`. An async generator has a different shape — the decorator implementation MUST be updated to dispatch on the wrapped function's coroutine-vs-async-generator kind. This is a small but non-trivial change to `observability` (or wherever the decorator lives); tasks.md tracks it explicitly.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| `ag-ui-protocol` PyPI package may not exist or may be pre-alpha | D5 mitigation: ship in-repo Pydantic types as fallback; ~6 classes |
| LangChain `astream` event vocabulary may evolve | LangGraph v0.x is mature on this surface; pin LangGraph version in `pyproject.toml`; freeze the mapper logic against an explicit list of event types we handle |
| `HarnessEvent` shape may need adjustment when MSAF becomes real | Variants are minimal and protocol-agnostic; D1's exhaustive-match pattern makes new variants additive |
| `@traced_harness` decorator may not handle async generators correctly | D9-noted; tasks.md adds explicit step to extend the decorator with tests |
| Single-user assumption bakes in single-thread-per-process | D4-acknowledged; documented forward path; not a v1 problem |
| Discoverability of the new `serve` command | Update `--help` output for the CLI; mention in CLAUDE.md "Essential Commands" |
| SSE proxy/firewall buffering may break streaming | Loopback-only binding in v1 sidesteps this; document for future Tauri deployment |
| FastAPI / uvicorn add ~5 new transitive deps | Acceptable; both are mature, well-maintained |

## Migration Plan

This is an additive change. No migration is required for existing CLI users — `assistant run -p personal` works exactly as before. The new `assistant serve ...` subcommand is opt-in. Rollback is `git revert`.

For implementers of new SDK harnesses (e.g., the future MSAF implementation), the abstract `astream_invoke()` method becomes a required override. The MSAF harness currently stubs `invoke()` with `NotImplementedError`; the stub for `astream_invoke()` should match that pattern until MSAF is fully implemented.

## Open Questions

These are deferred to implementation time, not blockers for plan approval:

1. **`ag-ui-protocol` Python package availability and quality.** Resolved during Task 1.x (dependency audit). If it exists and is usable, depend on it; else ship in-repo types.
2. **Exact LangChain `astream` event names to filter.** LangGraph emits many event types (on_chain_start, on_llm_stream, on_tool_start, etc.); the mapper needs to know which to translate and which to drop. Resolved during Task 3.x (mapper implementation) by writing tests against the canonical event set the Deep Agents harness produces.
3. **Whether `--host` defaults to `127.0.0.1` or `localhost`.** Both work; `127.0.0.1` avoids IPv6 dual-stack confusion on some macOS configurations. Resolved during Task 5.x (CLI subcommand implementation).
4. **Whether `Content-Type: text/event-stream` should include `; charset=utf-8`.** RFC 6455 doesn't require it; some clients prefer it; `sse-starlette` likely handles this. Resolved during Task 4.x (HTTP layer).
