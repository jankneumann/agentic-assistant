## Why

The personal-assistant CLI is acceptable for shell-style interactions but misfits content-rich roles — the teacher role surfaced this most clearly during recent testing. The full design context is documented in `openspec/explore/generative-ui-layer.md` (committed 044f5ae). That exploration concluded with a phased plan whose first slice is *transport only* — get AG-UI events flowing from the Deep Agents harness over HTTP/SSE — before any frontend work.

This change implements that first slice. It is off-roadmap (P1–P5+P9 are archived; P6–P18 are pending without a UX layer) and emerged from user feedback. Shipping it now unblocks both the generative-UI follow-ups (`web-frontend-shell`, `openui-lang-rendering`, `teacher-ui-vocabulary`) and gives any future MSAF harness a ready-made event protocol that aligns with Microsoft's own AG-UI integration.

## What Changes

- **NEW** `serve` CLI subcommand: `uv run assistant serve -p <persona> -r <role> -H <harness> --host 127.0.0.1 --port 8765` mounts a FastAPI ASGI app with persona/role bound at startup time.
- **NEW** FastAPI app at `src/assistant/web/` exposing a single SSE endpoint (`POST /chat` → `text/event-stream`) that accepts a user message and streams AG-UI events back.
- **NEW** AG-UI emitter at `src/assistant/transports/ag_ui/` that maps harness-internal events to AG-UI protocol events (`RUN_STARTED`, `TEXT_MESSAGE_START`/`_CONTENT`/`_END`, `TOOL_CALL_START`/`_ARGS`/`_END`, `RUN_FINISHED`).
- **MODIFIED** `SdkHarnessAdapter`: adds an additive abstract method `astream_invoke(agent, message) -> AsyncIterator[HarnessEvent]`. Existing `invoke() -> str` is unchanged. **Not a breaking change** for the CLI (still uses `invoke()`). New for any harness implementer.
- **MODIFIED** Deep Agents harness: implements `astream_invoke()` by consuming `agent.astream(...)` from LangGraph (the substrate is already wired via `InMemorySaver` per commit `67795c2`).
- New runtime deps: `fastapi`, `uvicorn[standard]`, `sse-starlette`, and one of `ag-ui-protocol` (if a Python package exists) or a small in-repo `ag_ui` types module.
- New dev deps: none — `httpx` and `pytest-asyncio` are already present and used for SSE client testing.

**Out of scope (deferred to follow-up changes):**
- Any browser frontend or rendering code.
- Multi-persona-per-server, auth, multi-tenancy.
- AG-UI events beyond the minimal set (no `STATE_DELTA`, no custom events) — answer to discovery Q3.
- Thread-id surfacing to clients (single conversation per server process is implied by startup-time persona binding).
- MSAF harness streaming implementation (lands when MSAF is real; this change defines the abstract contract MSAF will implement).

## Capabilities

### New Capabilities

- `ag-ui-emitter`: Translates a harness `HarnessEvent` stream into AG-UI protocol events. Transport-agnostic — operates on async iterators, has no HTTP awareness. Defines the AG-UI event payload types in scope for v1 and the mapping from `HarnessEvent` variants.
- `web-server`: FastAPI ASGI application with a single SSE endpoint. Owns persona/role startup binding, request validation, error response formatting, and the SSE response framing (Content-Type, retry, event-id). Consumes the `ag-ui-emitter` to produce the event stream.

### Modified Capabilities

- `harness-adapter`: Adds an abstract `astream_invoke()` method to `SdkHarnessAdapter` returning `AsyncIterator[HarnessEvent]`. Defines the `HarnessEvent` discriminated union (run-lifecycle, text-delta, tool-call lifecycle). Existing `invoke()` is preserved unchanged.
- `cli-interface`: Adds a `serve` subcommand parallel to `run`. Shares the existing `-p/--persona`, `-r/--role`, `-H/--harness` option parsing; adds `--host` and `--port`. Wires startup-time persona/role binding into the FastAPI app.

## Impact

- **New code surface:** `src/assistant/transports/ag_ui/` (new package), `src/assistant/web/` (new package), one new CLI subcommand in `src/assistant/cli.py`.
- **Modified files:** `src/assistant/harnesses/base.py` (new abstract method), `src/assistant/harnesses/sdk/deep_agents.py` (implement astream_invoke), `src/assistant/cli.py` (new subcommand), `pyproject.toml` (new deps).
- **Tests:** `tests/transports/ag_ui/` (mapper unit tests), `tests/web/` (httpx-driven SSE client tests against a TestClient-mounted app), `tests/harnesses/test_deep_agents_streaming.py` (streaming variant of existing harness tests).
- **External deps:** adds FastAPI + uvicorn + sse-starlette to runtime; verify availability of `ag-ui-protocol` PyPI package (open question, addressed during implementation).
- **MSAF future impact:** When the MSAF harness becomes real (post-P5), it must implement `astream_invoke()`. Until then, MSAF stays stubbed; the abstract method on the base class enforces this for any new harness.
- **Privacy boundary:** No changes. Server binds to `127.0.0.1` by default; persona scoping is the same as the CLI (startup-time selection). No persona-specific code in the new modules; the privacy guard remains intact.
- **Off-roadmap acknowledgment:** This is the first concrete deliverable from the generative-UI exploration. Future follow-ups (`web-frontend-shell` and onward) extend this transport rather than replace it.

## Approaches Considered

Three genuinely distinct organizations of the new code. All three are constrained by the discovery answers (additive harness API, startup-time persona binding, minimal event set) — they differ in *how* the new code is organized across modules and capabilities.

### Approach 1 — Thin single-module bridge

**Description.** All new code lives in one package: `src/assistant/web/` containing `app.py` (FastAPI), `ag_ui.py` (mapper), and `events.py` (types). The harness's new `astream_invoke()` yields LangChain stream events directly; the mapper inside `web/` translates LangChain events → AG-UI events.

**Pros:**
- Smallest footprint: ~3 files in 1 new package.
- Fastest to ship; minimal boilerplate.
- No new abstraction (no `HarnessEvent`) to design.

**Cons:**
- AG-UI mapping logic is tied to the HTTP module — not reusable for a future WebSocket transport or an in-process consumer.
- Couples the AG-UI translator to LangChain's event vocabulary. The future MSAF harness's events would need a parallel mapper.
- Drifts from the exploration doc's "transports/ag_ui/" + "web/" split.

**Effort:** S

### Approach 2 — Separated transport + emitter (Recommended)

**Description.** Two new packages: `src/assistant/transports/ag_ui/` defines `HarnessEvent` (a small discriminated union: `RunStarted`, `RunFinished`, `TextDelta`, `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`) and the AG-UI mapper that consumes `HarnessEvent` and emits AG-UI events. `src/assistant/web/` is the FastAPI app that consumes the mapper. The harness's new `astream_invoke()` yields `HarnessEvent`, not LangChain events — the harness owns the LangChain→HarnessEvent translation; the AG-UI emitter owns HarnessEvent→AG-UI translation.

**Pros:**
- Clean separation of concerns: harness produces harness-agnostic events, transport produces protocol-specific events, web serves them.
- AG-UI emitter is reusable for a future WebSocket transport or for in-process streaming consumers (e.g., a future "stream to file" CLI mode for debugging).
- Future MSAF harness emits the same `HarnessEvent` shape → same AG-UI emitter works without modification.
- Aligns with the exploration doc's recommended architecture (the durable design record).
- Mirrors "harness boundary as the right seam" — the principle from the exploration.

**Cons:**
- More files (~5–6 vs ~3); ~200 extra lines of boilerplate.
- `HarnessEvent` is a new abstraction that needs careful design to avoid leaking LangChain-isms or AG-UI-isms.

**Effort:** M

### Approach 3 — Direct LangChain event passthrough

**Description.** The harness's `astream_invoke()` yields **raw LangChain stream events** unchanged; `src/assistant/web/` contains both the FastAPI app and the LangChain→AG-UI mapper. No new abstraction (`HarnessEvent`) is introduced; the mapper sits between the harness and the SSE response.

**Pros:**
- No intermediate abstraction — fastest path to a working bridge.
- Keeps the harness as thin as possible.
- AG-UI mapping is in one place, easy to navigate.

**Cons:**
- Couples AG-UI emitter directly to LangChain's event vocabulary.
- Bleeds harness-internal types (LangChain event classes) into the harness contract — every harness must speak LangChain, even if its underlying SDK doesn't (e.g., MSAF doesn't).
- The future MSAF harness has only two bad options: (a) emit fake LangChain events, or (b) the AG-UI mapper grows a second code path for MSAF events.
- Locks in LangChain-shaped thinking at the harness boundary.

**Effort:** S

### Recommendation

**Approach 2.** It costs about a day of extra implementation effort and ~200 extra lines vs. Approach 1, but it preserves the architectural principle from the exploration doc (the harness boundary as the right seam) and makes MSAF integration *additive* rather than *parallel*. Approach 3 looks attractive on size but pays its cost later — when MSAF becomes real, the LangChain coupling will be embarrassing.

The decisive factor: MSAF integration is on the roadmap (P5+P10 pending), not hypothetical. We're not designing for a "what if" future — we're designing for a planned future. Approach 2's HarnessEvent abstraction is the only one of the three that lets MSAF arrive as a drop-in.

### Selected Approach

**Approach 2 — Separated transport + emitter.** Selected at Gate 1 without modification on 2026-05-16. All downstream artifacts (specs, tasks, design, contracts, work-packages) MUST implement this approach. Specifically:

- Two new packages: `src/assistant/transports/ag_ui/` (emitter + HarnessEvent) and `src/assistant/web/` (FastAPI + SSE serving).
- New `HarnessEvent` discriminated union (6 variants for v1: `RunStarted`, `RunFinished`, `TextDelta`, `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`).
- `SdkHarnessAdapter.astream_invoke()` yields `HarnessEvent`, not raw LangChain stream events.
- Approaches 1 and 3 are documented above for the historical record and are not in scope.
