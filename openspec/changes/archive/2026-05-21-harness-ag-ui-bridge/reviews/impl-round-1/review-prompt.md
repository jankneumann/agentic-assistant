# Implementation Review: harness-ag-ui-bridge — Round 1

You are an independent implementation reviewer for the OpenSpec change
`harness-ag-ui-bridge`. The implementation is complete (6/6 work packages,
57/57 tasks, all quality gates green). This review is the first round of a
multi-vendor convergence loop (max_rounds=3). Read the code and supporting
artifacts as read-only input and produce structured findings conforming to
`openspec/schemas/review-findings.schema.json`.

## Output contract

Emit **only** a single JSON object conforming to
`openspec/schemas/review-findings.schema.json`. No commentary, no markdown
wrapping. Required fields per finding: `id`, `type`, `criticality`,
`description`, `disposition`, `axis`, `severity`. Set `reviewer_vendor` to
your model identifier. Include `resolution` whenever you recommend
`disposition: fix` — that text becomes the fix instruction.

## What was built

A FastAPI SSE bridge translating harness-agnostic streaming events into
AG-UI protocol events. The bridge sits between the SDK harness layer
(Deep Agents / MSAF) and downstream AG-UI consumers, and is exposed via a
new `assistant serve` CLI subcommand bound to loopback by default.

Components landed:

- `src/assistant/harnesses/sdk/events.py` — `HarnessEvent` discriminated
  union (6 variants with `kind` discriminator)
- `src/assistant/harnesses/sdk/deep_agents.py` — `astream_invoke` for
  Deep Agents (emits HarnessEvent stream)
- `src/assistant/harnesses/sdk/ms_agent_fw.py` — `astream_invoke` for MSAF
- `src/assistant/transports/ag_ui/{mapper,types,__init__}.py` — translates
  HarnessEvent stream into AG-UI protocol events (RUN_STARTED,
  TEXT_MESSAGE_*, TOOL_CALL_*, RUN_FINISHED, RUN_ERROR)
- `src/assistant/web/{app,routes}.py` — FastAPI app + `/chat` SSE +
  `/health` endpoints, with lifespan-managed harness + agent
- `src/assistant/cli.py` — `assistant serve` subcommand (host/port/persona/role/harness)
- `src/assistant/telemetry/decorators.py` — `@traced_harness` extended to
  produce span-bracketed streams

Test suites (~3500 LOC) cover events, mapper, deep_agents/msaf astream,
web app, CLI, integration smoke, and privacy/telemetry compliance.

## Input artifacts (read-only)

Working directory: `.` (this is the worktree root, branch
`openspec/harness-ag-ui-bridge`).

### Spec and design (authoritative interface)

- `openspec/changes/harness-ag-ui-bridge/proposal.md`
- `openspec/changes/harness-ag-ui-bridge/design.md`
- `openspec/changes/harness-ag-ui-bridge/specs/harness-adapter/spec.md`
- `openspec/changes/harness-ag-ui-bridge/specs/web-server/spec.md`
- `openspec/changes/harness-ag-ui-bridge/specs/cli-interface/spec.md`
- `openspec/changes/harness-ag-ui-bridge/specs/ag-ui-emitter/spec.md`

### Contracts

- `openspec/changes/harness-ag-ui-bridge/contracts/openapi/v1.yaml`
- `openspec/changes/harness-ag-ui-bridge/contracts/events/harness-event.schema.json`
- `openspec/changes/harness-ag-ui-bridge/contracts/events/ag-ui-events.schema.json`

### Implementation source

- `src/assistant/harnesses/base.py` (added `astream_invoke` + `thread_id` contract)
- `src/assistant/harnesses/sdk/events.py`
- `src/assistant/harnesses/sdk/deep_agents.py`
- `src/assistant/harnesses/sdk/ms_agent_fw.py`
- `src/assistant/transports/ag_ui/{__init__,mapper,types}.py`
- `src/assistant/web/{__init__,app,routes}.py`
- `src/assistant/cli.py`
- `src/assistant/telemetry/decorators.py`

### Tests

- `tests/harnesses/sdk/test_events.py`
- `tests/harnesses/test_base_streaming.py`
- `tests/harnesses/test_deep_agents_astream.py`
- `tests/harnesses/test_ms_agent_fw_astream.py`
- `tests/transports/ag_ui/test_mapper.py`
- `tests/transports/ag_ui/test_types.py`
- `tests/web/test_app.py`
- `tests/cli/test_serve.py`
- `tests/integration/test_ag_ui_smoke.py`
- `tests/telemetry/test_traced_harness_streaming.py`
- `tests/telemetry/test_privacy_compliance.py`

### History (already-fixed; do NOT re-raise unless residual gap)

- `openspec/changes/harness-ag-ui-bridge/session-log.md` (full revision history)
- `openspec/changes/harness-ag-ui-bridge/loop-state.json` (resolved + deferred findings)
- `openspec/changes/harness-ag-ui-bridge/tasks.md` (57/57 tasks complete)

## Already-fixed in IMPL_ITERATE round 1 (do NOT re-raise)

The IMPL_ITERATE self-review pass surfaced 9 findings; these 5 were fixed:

1. **CRITICAL — `astream_invoke` signature mismatch.** `routes.py` was
   calling `harness.astream_invoke(message)` but the contract on
   `SdkHarnessAdapter` is `astream_invoke(agent, message)`. Fake harnesses
   in tests mirrored the broken call site, so all 967 tests passed but the
   feature was broken in production. Fix: introduced injectable
   `_agent_factory` kwarg in `make_app`; default factory runs the full
   discover→resolve→authorize→create_agent pipeline; tests inject a
   trivial factory. routes.py now correctly passes both args. Verify
   `src/assistant/web/app.py` + `src/assistant/web/routes.py`.

2. **HIGH — RUN_ERROR synthesis on raw raise.** If a misbehaving harness
   raises without first emitting `RunFinished(error=...)`, the mapper
   would close the SSE stream silently. Fix: routes.py wraps the harness
   stream in try/except and synthesizes a `RunErrorEvent` (per AG-UI
   contract — class name only, no message body) before exit. Verify
   `src/assistant/web/routes.py:_generate`.

3. **HIGH — Client disconnect cleanup.** Harness async generator was not
   `aclose`d if the client dropped mid-stream. Fix: `contextlib.aclosing`
   wraps the stream. Verify `src/assistant/web/routes.py`.

4. **MEDIUM — Streaming field bounds.** `TextDelta.text` and
   `ToolCallArgs.args_chunk` had no max_length. Fix: 1 MiB cap on both.
   Verify `src/assistant/harnesses/sdk/events.py:70-74,98-101`.

5. **MEDIUM — SSE proxy buffering.** Default SSE response missed
   `Cache-Control: no-cache` + `X-Accel-Buffering: no` headers, causing
   nginx-style proxies to buffer the stream. Fix: headers added in
   routes.py. Verify `src/assistant/web/routes.py`.

## Already-deferred (do NOT re-raise — file as new follow-up if you disagree)

- **Concurrency lock** (#2 IMPL_ITERATE): no lock on shared harness;
  concurrent `/chat` requests could race `_thread_id` state. Deferred
  because v1 is single-user loopback. Re-raise only if you see a path
  that hits this in normal operation.
- **`/health` info disclosure** (#6 IMPL_ITERATE): `/health` exposes
  persona/role/harness. Acceptable on loopback default; re-raise only if
  you see a path where the loopback contract is broken.
- **`on_tool_end` orphan UUID fallback** (#7 IMPL_ITERATE): rare edge
  case, logged. Re-raise only if you see a non-rare trigger.
- **`wp-web-cli` split** (PLAN_REVIEW deferred): cosmetic, declined.
- **`serve --harness` default vs persona config** (PLAN_REVIEW deferred):
  declined.

## Review dimensions

Apply standard implementation-review dimensions:

- **Correctness**: does the code actually do what the specs/design say?
  Look for off-by-one errors, missing else-branches, wrong field
  references, type confusion.
- **Contract adherence**: does the AG-UI mapper emit events that validate
  against `ag-ui-events.schema.json`? Do tool-call event IDs flow
  correctly through start→args→end? Does RUN_ERROR follow the upstream
  shape from `ag_ui.core.RunErrorEvent`?
- **Security**: anything user-controllable that flows into a privileged
  surface? Anything that leaks beyond the loopback contract?
- **Performance**: any unbounded loops, unbounded memory growth, or
  blocking calls in the async path? Are async generators properly closed?
- **Test quality**: do tests verify the contract or just the call site?
  (IMPL_ITERATE caught the signature bug because fakes mirrored the broken
  call.) Are there tests for failure paths, not just the happy path? Does
  the smoke test reach end-to-end through the real FastAPI app?
- **Observability**: does `@traced_harness` correctly bracket the stream?
  Is there a span around each tool call?
- **Privacy boundary**: per `tests/telemetry/test_privacy_compliance.py`,
  the telemetry subtree must not eagerly import FastAPI-adjacent modules.
  Are imports correctly lazy in `assistant.web.app._default_agent_factory`?

## Calibration

- **critical**: would cause a real-world `/chat` request to fail, a
  contract violation that breaks an AG-UI client, a security/privacy
  boundary violation, or a CI gate that should pass but doesn't.
- **high**: would force a follow-up commit to land v1 (ambiguous behavior
  versus spec, missing failure-path coverage on a documented surface,
  test that doesn't actually test the contract).
- **medium**: would degrade quality but is fixable post-merge (missing
  edge-case test, suboptimal abstraction, missing observability span).
- **low**: polish, wording, naming, formatting.

Be **selective**. This is a v1 single-user loopback SSE bridge. Do not
raise findings that demand multi-tenant, multi-user, or production-
hardening features beyond the documented v1 scope.

## Disposition guidance

- `fix`: blocking; provide a concrete `resolution` describing what to change
- `regenerate`: the artifact needs rewriting from scratch (rare for impl)
- `accept`: noted but no change needed (e.g., would be fixed in a follow-up)
- `escalate`: needs human decision, not vendor consensus

Begin.
