# ADR-0003: Adopt AG-UI as the agent↔user transport protocol

## Status

ACCEPTED — explored in `openspec/explore/generative-ui-layer.md`
(committed 044f5ae, 2026-05-15); implemented by OpenSpec change
`harness-ag-ui-bridge`
(`openspec/changes/archive/2026-05-21-harness-ag-ui-bridge/`),
archived 2026-05-21.

## Date

2026-05-21

## Context

The CLI REPL is acceptable for shell-style interactions but misfits
content-rich roles — the `teacher` role (change `add-teacher-role`)
surfaced this most clearly. The generative-UI exploration concluded
with a phased plan whose first slice is *transport only*: stream
events from the harness over HTTP before any frontend work. The
options were a bespoke JSON API, raw LangChain event passthrough, or
an existing agent↔user event protocol. AG-UI is an open session/event
protocol with upstream Python types (`ag_ui.core`) and an existing
Microsoft Agent Framework integration, which aligns with this repo's
MSAF harness. Raw LangChain passthrough was rejected because it bleeds
LangChain event classes into the harness contract that MSAF cannot
speak; a bespoke API was rejected as a standard already existed
(later codified as roadmap guiding principle 7, "standards-first
seams").

## Decision

Adopt AG-UI (SSE event stream) as the agent↔user channel, organized as
a separated transport + emitter (proposal approach 2):

- **`HarnessEvent`** discriminated union in
  `src/assistant/harnesses/sdk/events.py` (6 variants: `RunStarted`,
  `RunFinished`, `TextDelta`, `ToolCallStart`, `ToolCallArgs`,
  `ToolCallEnd`), produced by `SdkHarnessAdapter.astream_invoke()` on
  both Deep Agents and MSAF harnesses.
- **AG-UI emitter** in `src/assistant/transports/ag_ui/` (`mapper.py`,
  `types.py`) mapping `HarnessEvent` to 9 AG-UI v1 event types
  (`RUN_STARTED`, `TEXT_MESSAGE_START/CONTENT/END`,
  `TOOL_CALL_START/ARGS/END`, `RUN_FINISHED`), with the D8 two-phase
  error contract (failure `RunFinished` event, then re-raise).
- **Web layer** in `src/assistant/web/` (`app.py`, `routes.py`):
  FastAPI app exposing `POST /chat` (SSE) and `GET /health`, started
  via the `assistant serve` CLI subcommand, loopback-bound by default.
- Runtime deps added: `fastapi`, `uvicorn`, `sse-starlette`, and the
  upstream AG-UI types package.

## Consequences

- The emitter is transport-agnostic (operates on async iterators), so
  a future WebSocket transport or in-process consumer reuses it; MSAF
  arrived as a drop-in because it emits the same `HarnessEvent` shape.
- Every concrete SDK harness must implement `astream_invoke()` and
  expose `thread_id` (see `src/assistant/harnesses/base.py`).
- `web/app.py` builds one harness at startup — a single global
  conversation. The P24 durable-session contract adds a session
  registry so P6 (A2A) and P7 (scheduler daemon) can multiplex.
- Follow-ups (`web-frontend-shell`, `openui-lang-rendering`, P29
  multimodal parts, the P24 approval-request event) extend this
  transport rather than replacing it; AG-UI is the composition surface
  row "Agent ↔ user UI" in
  `docs/architecture-analysis/2026-07-16-protocol-standards.md`.
