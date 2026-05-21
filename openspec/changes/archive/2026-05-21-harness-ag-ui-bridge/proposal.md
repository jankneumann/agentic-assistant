## Why

The personal-assistant CLI is acceptable for shell-style interactions but misfits content-rich roles — the teacher role surfaced this most clearly during recent testing. The full design context is documented in `openspec/explore/generative-ui-layer.md` (committed 044f5ae). That exploration concluded with a phased plan whose first slice is *transport only* — get AG-UI events flowing from the Deep Agents harness over HTTP/SSE — before any frontend work.

This change implements that first slice. It is off-roadmap (P1–P5+P9 are archived; P6–P18 are pending without a UX layer) and emerged from user feedback. Shipping it now unblocks both the generative-UI follow-ups (`web-frontend-shell`, `openui-lang-rendering`, `teacher-ui-vocabulary`) and gives any future MSAF harness a ready-made event protocol that aligns with Microsoft's own AG-UI integration.

## What Changes

- **NEW** `serve` CLI subcommand: `uv run assistant serve -p <persona> -r <role> -H <harness> --host 127.0.0.1 --port 8765` mounts a FastAPI ASGI app with persona/role bound at startup time.
- **NEW** FastAPI app at `src/assistant/web/` exposing a single SSE endpoint (`POST /chat` → `text/event-stream`) that accepts a user message and streams AG-UI events back.
- **NEW** AG-UI emitter at `src/assistant/transports/ag_ui/` that maps harness-internal events to AG-UI protocol events (`RUN_STARTED`, `TEXT_MESSAGE_START`/`_CONTENT`/`_END`, `TOOL_CALL_START`/`_ARGS`/`_END`, `RUN_FINISHED`).
- **MODIFIED** `SdkHarnessAdapter`: adds an additive abstract method `astream_invoke(agent, message) -> AsyncIterator[HarnessEvent]`. Existing `invoke() -> str` is unchanged. **Not a breaking change** for the CLI (still uses `invoke()`). New for every concrete harness implementer.
- **MODIFIED** Deep Agents harness: implements `astream_invoke()` by consuming `agent.astream(...)` from LangGraph (the substrate is already wired via `InMemorySaver` per commit `67795c2`).
- **MODIFIED** MS Agent Framework harness: implements `astream_invoke()` by consuming `agent.run(messages, stream=True)` from `agent-framework` (which returns a `ResponseStream[AgentResponseUpdate, AgentResponse[Any]]` — the typed overload at `_agents.py:1631-1645`). Required for the abstract method to be honored on every concrete SdkHarnessAdapter, and verified during plan revision after the explore agent reported MSAF as stubbed (it is fully wired since P5).
- New runtime deps: `fastapi`, `uvicorn[standard]`, `sse-starlette`, and `ag-ui` (the upstream AG-UI Python types package — confirmed installed; `ag_ui.core` provides Pydantic-typed `RunStartedEvent`, `RunFinishedEvent`, `TextMessage{Start,Content,End}Event`, `ToolCall{Start,Args,End}Event`).
- New dev deps: none — `httpx` and `pytest-asyncio` are already present and used for SSE client testing.

**Out of scope (deferred to follow-up changes):**
- Any browser frontend or rendering code.
- Multi-persona-per-server, auth, multi-tenancy.
- AG-UI events beyond the minimal set (no `STATE_DELTA`, no custom events) — answer to discovery Q3.
- Thread-id surfacing to clients (single conversation per server process is implied by startup-time persona binding).
- Adopting Microsoft's `agent_framework_ag_ui` package directly (it is installed but currently broken in the venv due to the v1.0.1 namespace-package quirk; also would fragment the harness boundary). Acknowledged in design.md D10 as a future option if the upstream packaging issue is resolved.

## Capabilities

### New Capabilities

- `ag-ui-emitter`: Translates a harness `HarnessEvent` stream into AG-UI protocol events. Transport-agnostic — operates on async iterators, has no HTTP awareness. Defines the AG-UI event payload types in scope for v1 and the mapping from `HarnessEvent` variants.
- `web-server`: FastAPI ASGI application with a single SSE endpoint. Owns persona/role startup binding, request validation, error response formatting, and the SSE response framing (Content-Type, retry, event-id). Consumes the `ag-ui-emitter` to produce the event stream.

### Modified Capabilities

- `harness-adapter`: Adds an abstract `astream_invoke()` method to `SdkHarnessAdapter` returning `AsyncIterator[HarnessEvent]`. Defines the `HarnessEvent` discriminated union (run-lifecycle, text-delta, tool-call lifecycle). Existing `invoke()` is preserved unchanged.
- `cli-interface`: Adds a `serve` subcommand parallel to `run`. Shares the existing `-p/--persona`, `-r/--role`, `-H/--harness` option parsing; adds `--host` and `--port`. Wires startup-time persona/role binding into the FastAPI app.

## Impact

- **New code surface:** `src/assistant/transports/ag_ui/` (new package), `src/assistant/web/` (new package), one new CLI subcommand in `src/assistant/cli.py`.
- **Modified files:** `src/assistant/harnesses/base.py` (new abstract method), `src/assistant/harnesses/sdk/deep_agents.py` (implement astream_invoke), `src/assistant/harnesses/sdk/ms_agent_fw.py` (implement astream_invoke), `src/assistant/cli.py` (new subcommand), `pyproject.toml` (new deps).
- **Tests:** `tests/transports/ag_ui/` (mapper unit tests), `tests/web/` (httpx-driven SSE client tests against a TestClient-mounted app), `tests/harnesses/test_deep_agents_astream.py` and `tests/harnesses/test_ms_agent_fw_astream.py` (streaming variants of the existing harness tests).
- **External deps:** adds FastAPI + uvicorn + sse-starlette + `ag-ui` to runtime. The `ag-ui` package is confirmed installed in the current venv; `pyproject.toml` will declare it explicitly so future installs pin it.
- **MSAF impact (corrected during plan revision):** MSAF is already fully implemented (per the existing `ms-agent-framework-harness` spec and `src/assistant/harnesses/sdk/ms_agent_fw.py`); this change adds `astream_invoke()` to MSAF as well, wrapping `agent.run(messages, stream=True)`. The abstract method on the base class is honored uniformly across both harnesses today, not just future-MSAF.
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

**Description.** Two new packages plus a colocated event type. `HarnessEvent` (a small discriminated union: `RunStarted`, `RunFinished`, `TextDelta`, `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`) lives at `src/assistant/harnesses/sdk/events.py` next to the `SdkHarnessAdapter` base class — because the harnesses *construct* these events, the type must live in the harness layer per the D6 import-direction rule. `src/assistant/transports/ag_ui/` contains the AG-UI mapper that consumes `HarnessEvent` and emits AG-UI events. `src/assistant/web/` is the FastAPI app that consumes the mapper. The harness's new `astream_invoke()` yields `HarnessEvent`, not LangChain events — the harness owns the LangChain→HarnessEvent translation; the AG-UI emitter owns HarnessEvent→AG-UI translation.

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

**Approach 2 — Separated transport + emitter.** Selected at Gate 1 without modification on 2026-05-16. Plan was revised at Gate 2 (same day) to extend scope: MSAF streaming is included in this change after code inspection confirmed MSAF is already fully implemented (not stubbed as the explore agent had reported). All downstream artifacts (specs, tasks, design, contracts, work-packages) MUST implement this approach. Specifically:

- Two new packages: `src/assistant/transports/ag_ui/` (AG-UI mapper + upstream-type re-exports) and `src/assistant/web/` (FastAPI + SSE serving). A third addition lives in the existing harness package: `src/assistant/harnesses/sdk/events.py` defines the `HarnessEvent` discriminated union (kept in the harness layer per the D6 import-direction rule).
- New `HarnessEvent` discriminated union (6 variants for v1: `RunStarted`, `RunFinished`, `TextDelta`, `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`).
- `SdkHarnessAdapter.astream_invoke()` yields `HarnessEvent`, not raw LangChain or `agent_framework` stream events. Both DeepAgents and MSAF map their respective SDK stream events to the same `HarnessEvent` shape.
- AG-UI event types come from the upstream `ag_ui` Python package (`ag_ui.core`), not in-repo types — confirmed installed.
- Microsoft's `agent_framework_ag_ui` package (which provides `add_agent_framework_fastapi_endpoint`) is acknowledged but not used in v1; see design.md D10 for the rationale.
- Approaches 1 and 3 are documented above for the historical record and are not in scope.
