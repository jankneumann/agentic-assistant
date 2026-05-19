# Architecture Impact: harness-ag-ui-bridge

**Branch:** `openspec/harness-ag-ui-bridge` @ `d75847d`
**Comparison base:** `main`
**Generated:** 2026-05-19 VALIDATE phase

## Layer additions

```
src/assistant/
├── transports/                                  [NEW LAYER]
│   └── ag_ui/                                   [NEW PACKAGE]
│       ├── __init__.py        (42 LOC)
│       ├── mapper.py          (160 LOC) — HarnessEvent → AGUIEvent
│       └── types.py           (60 LOC)  — re-exports + AGUIEvent union
└── web/                                         [NEW PACKAGE]
    ├── __init__.py            (1 LOC)
    ├── app.py                 (180 LOC) — FastAPI factory + lifespan
    └── routes.py              (76 LOC)  — /chat (SSE) + /health
```

## Layer extensions

```
src/assistant/
├── harnesses/
│   ├── base.py                (+60 LOC)
│   │   ├── added: SdkHarnessAdapter.thread_id property
│   │   └── added: SdkHarnessAdapter.astream_invoke base stub (NotImplementedError)
│   └── sdk/
│       ├── events.py          (NEW, 127 LOC) — HarnessEvent discriminated union
│       ├── deep_agents.py     (+130 LOC)
│       │   ├── added: astream_invoke implementation (LangGraph translation)
│       │   ├── added: thread_id property
│       │   ├── added: per-stream open_tool_calls dict (call_id correlation)
│       │   └── added: aclosing wrap on inner LangGraph stream
│       └── ms_agent_fw.py     (+132 LOC)
│           ├── added: astream_invoke implementation (MSAF translation)
│           ├── added: thread_id property
│           ├── added: deque[str] FIFO for parallel-orphan call_id correlation
│           └── added: defensive aclose pattern on inner ResponseStream
├── telemetry/
│   └── decorators.py          (+78 LOC)
│       ├── extended: traced_harness now dispatches on coroutine vs async-generator
│       ├── added: async_gen_wrapper with one trace_llm_call per stream
│       ├── added: aclosing on inner harness gen (codex #3)
│       └── added: GeneratorExit branch records cancelled=True (gemini #6)
└── cli.py                     (+72 LOC)
    └── added: serve subcommand (host/port/persona/role/harness flags)
```

## Module dependency direction (D6)

```
                  ┌──────────────────────┐
                  │     assistant.web    │  (depends on transports + harnesses)
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  assistant.transports.ag_ui  │  (depends on harnesses + ag_ui.core)
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   assistant.harnesses.sdk    │  (depends on core, langchain, agent_framework)
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │      assistant.core          │  (persona, role, capabilities)
                  └──────────────────────┘
```

**Invariant:** `transports/ag_ui` MUST NOT import from `web/` or
`harnesses/host`. `web/` MUST NOT import from itself in a cycle.
`harnesses/sdk` MUST NOT import from `transports/` or `web/`.

**Status:** Verified via `import` grep. No upward-direction violations.

## New external dependencies

```diff
+ ag-ui-protocol >= 0.1, < 1.0    # AG-UI protocol types
+ fastapi          >= 0.115        # FastAPI app + routes
+ sse-starlette    >= 2.0          # SSE response with disconnect/backpressure handling
+ uvicorn          >= 0.30         # ASGI server (CLI `serve` entry point)
+ httpx            >= 0.27         # AsyncClient for tool discovery (transitive: already present)
```

Total new dependency surface: 4 packages (one already transitive). All
pinned to compatible-range versions in `pyproject.toml`.

## Test scaffolding additions

```
tests/
├── harnesses/                                   [NEW]
│   ├── __init__.py
│   ├── sdk/
│   │   ├── __init__.py
│   │   └── test_events.py           (278 LOC, 28 tests)
│   ├── test_base_streaming.py       (234 LOC)
│   ├── test_deep_agents_astream.py  (716 LOC, 26 tests — 4 round-1 regressions, 1 round-2 structural)
│   └── test_ms_agent_fw_astream.py  (795 LOC, 22 tests — 1 round-2 parallel-orphan regression)
├── transports/                                  [NEW]
│   ├── __init__.py
│   └── ag_ui/
│       ├── __init__.py
│       ├── test_mapper.py           (538 LOC, 24 tests)
│       └── test_types.py            (149 LOC, 20 tests)
├── web/                                         [NEW]
│   ├── __init__.py
│   └── test_app.py                  (586 LOC, 20 tests)
├── cli/                                         [NEW]
│   └── test_serve.py                (302 LOC, 10 tests)
├── integration/                                 [EXTENDED]
│   └── test_ag_ui_smoke.py          (250 LOC, 4 tests — 1 round-1 camelCase regression)
└── telemetry/                                   [EXTENDED]
    ├── test_traced_harness_streaming.py  (370 LOC, 8 tests — 2 round-1 regressions)
    └── test_privacy_compliance.py        (+66 LOC — privacy boundary asserts)
```

**Coverage delta:** +8 test files, ~3500 LOC of new test code, 162 new test functions.

## OpenSpec artifact additions

```
openspec/changes/harness-ag-ui-bridge/
├── proposal.md
├── design.md
├── tasks.md                          (57 tasks, all checked)
├── work-packages.yaml                (6 packages, DAG-ordered)
├── session-log.md                    (extensive — full revision history)
├── loop-state.json                   (full convergence trace)
├── validation-report.md              [THIS PHASE]
├── architecture-impact.md            [THIS PHASE — this file]
├── specs/
│   ├── harness-adapter/spec.md       (294 LOC)
│   ├── web-server/spec.md            (177 LOC)
│   ├── cli-interface/spec.md         (113 LOC)
│   └── ag-ui-emitter/spec.md         (180 LOC)
├── contracts/
│   ├── openapi/v1.yaml
│   ├── events/harness-event.schema.json
│   └── events/ag-ui-events.schema.json
└── reviews/
    ├── round-1/ ... round-3/         (PLAN_REVIEW: 3 rounds)
    ├── impl-round-1/ ... impl-round-3/  (IMPL_REVIEW: 3 rounds)
    └── (each with per-vendor findings + consensus + manifest)
```

## Architecture decisions impacted (design.md trace)

| Decision | Impact |
|---|---|
| D1: HarnessEvent discriminated union | NEW (this change introduces it) |
| D2: SSE transport | NEW |
| D3: Single harness per process (lifespan) | NEW (FastAPI lifespan) |
| D4: Single thread_id per server process | NEW (harness.thread_id property) |
| D5: Loopback default + auth posture | NEW (`--host 127.0.0.1` default, warn-not-refuse) |
| D6: Import direction (downward only) | EXTENDED (transports → harnesses contract) |
| D7: Async-generator over callback | NEW (astream_invoke) |
| D8: Two-phase error contract | NEW (RunFinished(error=) + Phase-2 re-raise + RUN_ERROR mapper) |
| D9: traced_harness dispatch on shape | EXTENDED (added async-gen path) |
| D11: SDK event translation | NEW (D1 mapping table) |
| D12: Loopback-only auth posture | NEW (warn on non-loopback) |
| D13: Backpressure via sse-starlette | NEW (delegated to library) |

## Public API surface added

```python
# New imports available to operators:
from assistant.harnesses.sdk.events import (
    HarnessEvent, RunStarted, RunFinished, TextDelta,
    ToolCallStart, ToolCallArgs, ToolCallEnd,
)
from assistant.transports.ag_ui import map_harness_to_ag_ui
from assistant.transports.ag_ui.types import (
    AGUIEvent, RunStartedEvent, RunFinishedEvent, RunErrorEvent,
    TextMessageStartEvent, TextMessageContentEvent, TextMessageEndEvent,
    ToolCallStartEvent, ToolCallArgsEvent, ToolCallEndEvent,
)
from assistant.web.app import make_app

# New CLI subcommand:
$ uv run assistant serve -p <persona> [-r <role>] [-H <harness>] [--host <addr>] [--port <int>]
```

## Public API surface modified (backward-compatible additions only)

```python
# SdkHarnessAdapter base class (additive):
class SdkHarnessAdapter(HarnessAdapter):
    @property
    def thread_id(self) -> str: ...                          # NEW; concrete classes must override
    async def astream_invoke(self, agent: Any, message: str
                            ) -> AsyncIterator[HarnessEvent]: ...  # NEW; concrete classes must override
```

Subclasses outside this repo (none currently) MUST add these two methods.
Within this repo, both concrete SDK harnesses (DeepAgents, MSAF) override
both methods as part of this change.

## Removals

None. This change is purely additive.

## Performance impact

- `assistant serve` adds a long-lived FastAPI process (singleton harness +
  singleton agent built once at lifespan start) so per-request cost is
  dominated by the harness invocation itself rather than setup overhead.
- The mapper's text-message bracketing tracks one open `message_id` in a
  closure variable (O(1) state per request).
- The deep_agents tool_call_id correlation dict is per-request (`async def`
  scope), so memory cost is bounded by concurrent open tool calls × 36
  bytes per UUID. For v1 single-user loopback this is negligible.
- The MSAF deque is bounded similarly.

## Security impact

- `--host 0.0.0.0` is an explicit opt-out from the loopback default; CLI
  warns but does not refuse (D12). Acceptable v1 posture.
- `/health` exposes persona/role/harness names without authentication;
  acceptable on loopback default, deferred follow-up for non-loopback (see
  `loop-state.json:deferred_to_followup:health_endpoint_persona_disclosure_loopback_default`).
- `/chat` does not authenticate; same scope as above. v1 deliberately
  ships without auth per D12.

## Out-of-scope / Follow-ups filed

See `loop-state.json:deferred_to_followup` for the 12 single-vendor low/
medium findings deferred across PLAN_REVIEW + IMPL_REVIEW rounds. They
are documented limitations, not bugs.
