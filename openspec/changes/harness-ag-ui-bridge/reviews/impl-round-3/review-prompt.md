# Implementation Review: harness-ag-ui-bridge — Round 3 (final convergence verification)

You are an independent implementation reviewer for the OpenSpec change
`harness-ag-ui-bridge`. This is the **third and final** round of a multi-vendor
convergence loop (max_rounds=3). Round 1 surfaced 13 findings (9 fixed,
4 deferred); round 2 surfaced 7 findings (5 fixed, 2 deferred, including
1 cross-vendor confirmed). Your job is to verify the round-2 fixes
correctly addressed the round-2 findings and to surface any genuinely
blocking issue that would prevent the feature from landing.

**Be highly selective.** This is the final round. Only raise a finding
if it is genuinely blocking. Convergence is the desired outcome.

## Output contract

Emit **only** a single JSON object conforming to
`openspec/schemas/review-findings.schema.json`. No commentary, no markdown
wrapping. Required fields per finding: `id`, `type`, `criticality`,
`description`, `disposition`, `axis`, `severity`. Set `reviewer_vendor` to
your model identifier. Include `resolution` whenever you recommend
`disposition: fix`.

## What changed since round 2 (commit `d36850c`)

The round-2 review surfaced 7 findings (vs round-1's 13). 5 fixes landed:

1. **gemini-r2-3 (medium)** — `deep_agents.py` now wraps the upstream
   LangGraph `astream_events` stream in `contextlib.aclosing` so a
   client disconnect (`GeneratorExit`) finalizes the SDK iterator.
   `ms_agent_fw.py` uses an equivalent **defensive** pattern (try/
   finally + `inspect.iscoroutine` + `getattr` for `aclose`) because
   MSAF's `ResponseStream` doesn't guarantee an awaitable `aclose`
   per the agent-framework SDK contract.

2. **Cross-vendor confirmed: claude-r2-2 + codex-r2-1 (medium)** —
   `ms_agent_fw.py` replaced the single-slot
   `pending_orphan_call_id: str | None` with a FIFO `deque[str]` so
   parallel missing-id tool calls bracket correctly via
   oldest-start-first matching. Single-vendor missing-id behavior
   is unchanged.

3. **claude-r2-1 (medium)** — The round-1 `test_thread_id_unchanged_after_imports`
   regression test was illusory (`__new__` bypass, never called
   `create_agent`). Replaced with
   `test_create_agent_does_not_reassign_thread_id_source` which uses
   `inspect.getsource(DeepAgentsHarness.create_agent)` and asserts
   the source does not contain `self._thread_id =`. Structural
   assertion; 100% revert-detecting.

4. **gemini-r2-1 (low)** — `SdkHarnessAdapter.thread_id` docstring in
   `base.py` updated: "`DeepAgentsHarness` synthesizes a UUID at
   construction and returns it unchanged for the adapter instance's
   lifetime" (was: "set by `create_agent`").

5. **gemini-r2-2 (low)** — `DeepAgentsHarness.astream_invoke` docstring
   updated to acknowledge `open_tool_calls` bookkeeping (was: "without
   extra bookkeeping").

### Already-deferred from round 2 (do not re-raise unless blocking)

- **claude-r2-3 (low)** — test fixtures' MagicMock auto-truthy
  `pc.tool_sources` causes test paths to construct (and immediately
  aclose) a real `httpx.AsyncClient`. Harmless; documented.

### Carried over from round 1 (still deferred)

- **claude #3 (low)** — CLI constructs harness twice. Accepted: surfaces
  config errors with cleaner CLI exit path.
- **claude #4 (low)** — `::1` / `localhost` not recognized as loopback by
  the warning predicate. Cosmetic warning behavior.
- **gemini #3 (medium)** — Tool args size limit. Pydantic
  `max_length=1 MiB` raises ValidationError at the source; no chunking
  layer needed for v1.
- **gemini #4 (medium)** — Mapper doesn't close text message before
  ToolCallStart. AG-UI clients tolerate interleaved events; spec doesn't
  require pre-tool closure.

## Input artifacts (read-only)

Working directory: `.` (this is the worktree root, branch
`openspec/harness-ag-ui-bridge` at `d36850c`).

### Implementation source (current state)

- `src/assistant/harnesses/base.py` (round-2 docstring update)
- `src/assistant/harnesses/sdk/deep_agents.py` (round-2 aclose +
  docstring updates; round-1 fixes still in place)
- `src/assistant/harnesses/sdk/ms_agent_fw.py` (round-2 deque + defensive
  aclose; round-1 fixes)
- `src/assistant/transports/ag_ui/mapper.py` (round-1 role='assistant')
- `src/assistant/transports/ag_ui/types.py`
- `src/assistant/web/app.py` (round-1 httpx lifespan)
- `src/assistant/web/routes.py` (round-1 by_alias + RUN_ERROR + aclose)
- `src/assistant/cli.py`
- `src/assistant/telemetry/decorators.py` (round-1 inner-gen aclose +
  GeneratorExit-as-cancelled)
- `src/assistant/harnesses/sdk/events.py`

### Tests

- `tests/harnesses/test_deep_agents_astream.py` (3 round-1 regressions +
  1 round-2 structural test)
- `tests/harnesses/test_ms_agent_fw_astream.py` (1 round-2 deque regression)
- `tests/telemetry/test_traced_harness_streaming.py` (2 round-1 regressions)
- `tests/integration/test_ag_ui_smoke.py` (1 round-1 SSE camelCase regression)
- `tests/web/test_app.py`
- `tests/cli/test_serve.py` (1 round-1 sentinel test)

### Review history

- `openspec/changes/harness-ag-ui-bridge/reviews/impl-round-1/` (round-1
  findings + consensus)
- `openspec/changes/harness-ag-ui-bridge/reviews/impl-round-2/` (round-2
  findings + consensus)

## Review focus for round 3

Be **highly selective**. Only raise a finding if it is genuinely
blocking. Specifically:

1. **Verify round-2 fixes are internally consistent.** Does each fix
   actually resolve the round-2 finding? Walk the 5 fixes against the
   current source.
2. **Verify the round-2 deque change preserves round-1 semantics.** When
   the SDK provides call_id (the normal case), is behavior unchanged?
   Only the missing-id path should differ.
3. **Verify defensive aclose patterns.** `deep_agents.py` uses
   `contextlib.aclosing` (strict). `ms_agent_fw.py` uses a defensive
   try/finally with `getattr` + `inspect.iscoroutine`. Is the defensive
   pattern actually safe for the production MSAF SDK?
4. **Catch any new bug introduced by the round-2 fix delta.** The delta
   touched: deep_agents.py (aclose, docstring), ms_agent_fw.py (deque,
   aclose), base.py (docstring), test_deep_agents (structural test),
   test_ms_agent_fw (deque regression).
5. **Catch any stale reference** from the round-2 changes — function
   signatures, type aliases, docstrings.

## Calibration

- **critical**: would cause a real-world `/chat` request to fail, a
  contract violation that breaks an AG-UI client, a security/privacy
  boundary violation, or a CI gate that should pass but doesn't.
- **high**: would force a follow-up commit to land v1.
- **medium**: would degrade quality but is fixable post-merge.
- **low**: polish, wording, naming, formatting.

Do not re-raise round-1 or round-2 deferred findings unless you can
show a concrete, non-theoretical impact in the v1 single-user-loopback
scope.

## Disposition guidance

- `fix`: blocking; provide a concrete `resolution` describing what to change
- `regenerate`: rewrite from scratch (rare)
- `accept`: noted but no change needed (a deferred-from-prior-round issue)
- `escalate`: needs human decision

Begin.
