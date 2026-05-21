# Implementation Review: harness-ag-ui-bridge — Round 2 (round-1 fix verification)

You are an independent implementation reviewer for the OpenSpec change
`harness-ag-ui-bridge`. This is the **second round** of a multi-vendor
convergence loop (max_rounds=3). Round 1 surfaced 13 findings; 9 were
fixed inline (commit `885177c`). Your job is to **verify the round-1
fixes are correct and complete** and to flag any **regression introduced
by the fix delta**.

## Output contract

Emit **only** a single JSON object conforming to
`openspec/schemas/review-findings.schema.json`. No commentary, no markdown
wrapping. Required fields per finding: `id`, `type`, `criticality`,
`description`, `disposition`, `axis`, `severity`. Set `reviewer_vendor` to
your model identifier. Include `resolution` whenever you recommend
`disposition: fix`.

## Round 1 findings recap

13 unique findings across 3 vendors. Distribution: 4 critical, 3 high,
4 medium, 2 low. None were cross-vendor confirmed (each vendor surfaced
non-overlapping concerns).

### Already fixed in commit `885177c` (verify, don't re-raise)

1. **codex #1 (critical)** — `routes.py:_generate()` now serializes events
   with `model_dump_json(by_alias=True, exclude_none=True)`. AG-UI camelCase
   field names (`threadId`, `runId`, `messageId`, `toolCallId`) are now
   emitted; null upstream fields are stripped.
   - Verify: `src/assistant/web/routes.py` lines around the
     `evt.model_dump_json(...)` call and the `err.model_dump_json(...)` call.
   - Regression test: `tests/integration/test_ag_ui_smoke.py::
     test_sse_payloads_use_ag_ui_camelcase_aliases`.

2. **codex #2 (critical)** — `httpx.AsyncClient` lifecycle moved into the
   FastAPI lifespan. `_default_agent_factory` now takes `http_client` as
   a required positional parameter. Client is created at lifespan startup
   if the persona declares `tool_sources`, closed in the lifespan
   `finally` block.
   - Verify: `src/assistant/web/app.py` — the `_lifespan` async-with on
     `http_client` and the `AgentFactory` type alias signature.

3. **gemini #1 (critical)** — `mapper.py` now emits
   `TextMessageStartEvent(message_id=..., role="assistant")` for every
   first-of-message TextDelta. Required by the AG-UI protocol.
   - Verify: `src/assistant/transports/ag_ui/mapper.py` —
     `TextMessageStartEvent` yield site.

4. **claude #1 (high)** — Both `deep_agents.py:astream_invoke` and
   `ms_agent_fw.py:astream_invoke` narrow their catch from
   `except BaseException` to `except Exception`, with an explicit
   `except GeneratorExit: raise` ahead of the Exception catch. Yielding
   a synthesized `RunFinished(error=...)` while handling `GeneratorExit`
   no longer occurs.
   - Verify: both harness modules.
   - Regression test: `tests/harnesses/test_deep_agents_astream.py::
     test_astream_invoke_disconnect_via_aclose_does_not_raise_runtime_error`.

5. **codex #3 (high)** — `traced_harness` async-generator wrapper now wraps
   the inner generator in `contextlib.aclosing(gen)` so closing the outer
   wrapper finalizes the inner harness generator.
   - Verify: `src/assistant/telemetry/decorators.py:async_gen_wrapper`.
   - Regression test: `tests/telemetry/test_traced_harness_streaming.py::
     test_traced_harness_aclose_finalizes_inner_generator`.

6. **gemini #2 (high)** — Stable tool_call_id correlation across the
   tool-call lifecycle.
   - `deep_agents.py`: per-stream `open_tool_calls: dict[str, str]` maps
     upstream LangGraph `run_id` → emitted `call_id`. The on_tool_end
     branch looks up the start's call_id by run_id; falls back to a fresh
     UUID only if run_id was missing on both sides.
   - `ms_agent_fw.py`: per-stream `pending_orphan_call_id: str | None`
     remembers the most-recent missing-id start so a missing-id
     `function_result` can correlate. SDK-provided call_id remains
     authoritative.
   - Verify: both harness modules.
   - Regression test: `tests/harnesses/test_deep_agents_astream.py::
     test_tool_call_id_stable_across_start_args_end_when_run_id_consistent`.

7. **gemini #5 (medium)** — `DeepAgentsHarness.create_agent` no longer
   overwrites `self._thread_id`. The `__init__`-time UUID is the
   adapter-instance-lifetime thread_id, matching the harness-adapter spec.
   - Verify: `src/assistant/harnesses/sdk/deep_agents.py:create_agent`.
   - Regression test: `tests/harnesses/test_deep_agents_astream.py::
     test_thread_id_unchanged_after_imports`.

8. **gemini #6 (low)** — `traced_harness` async-gen wrapper distinguishes
   `GeneratorExit` (cancellation) from other exceptions in trace metadata.
   Cancellation records `metadata={"streaming": True, "cancelled": True}`;
   other exceptions record `error: ClassName` as before.
   - Verify: `src/assistant/telemetry/decorators.py:async_gen_wrapper`
     — separate `except GeneratorExit` branch.
   - Regression test: `tests/telemetry/test_traced_harness_streaming.py::
     test_traced_harness_generator_exit_recorded_as_cancelled`.

9. **claude #2 (medium)** — `tests/cli/test_serve.py::
   test_serve_uses_default_role_when_r_omitted` now mocks
   `_load_persona_or_fail` + `RoleRegistry` to inject a sentinel
   `default_role='sentinel-default-role'` and asserts exact equality.

### Already deferred (do NOT re-raise unless you find a real, non-theoretical impact)

- **claude #3 (low)** — `serve` constructs harness twice. Accepted: the
  CLI-side construction surfaces config errors with a cleaner CLI exit
  path. make_app's own `isinstance(harness, HostHarnessAdapter)` check
  remains the source-of-truth.
- **claude #4 (low)** — `::1` and `localhost` not recognized as loopback
  by the warning predicate. Accepted: cosmetic warning behavior.
- **gemini #3 (medium)** — Tool args size limit. Pydantic `max_length=1
  MiB` on `ToolCallArgs.args_chunk` raises a `ValidationError` at the
  source; no chunking layer is needed for v1.
- **gemini #4 (medium)** — Mapper does not close text message before
  ToolCallStart. Most AG-UI clients tolerate interleaved events; the
  spec does not require pre-tool message closure.

## Review focus for round 2

Be **highly selective**. This is the second of at most three rounds, and
the goal is convergence, not exhaustive iteration. Specifically:

1. **Verify round-1 fixes are internally consistent.** Does each fix
   actually resolve the original finding without introducing
   regressions? Walk each of the 9 fixes against the source.
2. **Verify the regression tests actually exercise the fix.** Each fix
   added a test. Does the test fail if the fix is reverted? (You can't
   run pytest; reason from the test body.)
3. **Catch new bugs introduced by the fix delta** — particularly:
   - `_default_agent_factory` now takes `http_client`. Are there any
     code paths or test fixtures still calling it with 4 args instead
     of 5?
   - `pending_orphan_call_id` in `ms_agent_fw.py` is a single slot — does
     it correctly handle the case where the SDK emits parallel/nested
     tool calls?
   - `aclosing(gen)` in `traced_harness` — could the double-aclose (outer
     wrapper closing the inner gen, then the inner gen's own cleanup
     running) cause anything unexpected?
   - `except GeneratorExit: raise` is now explicit in 2 harnesses. Does
     the order of `except GeneratorExit / except Exception` matter
     (it should — GeneratorExit must come first), and is the ordering
     correct in both files?
4. **Catch any stale reference** — function signatures, type aliases,
   docstrings.

## Calibration

- **critical**: would cause a real-world `/chat` request to fail, a
  contract violation that breaks an AG-UI client, a security/privacy
  boundary violation, or a CI gate that should pass but doesn't.
- **high**: would force a follow-up commit to land v1.
- **medium**: would degrade quality but is fixable post-merge.
- **low**: polish, wording, naming, formatting.

Do not re-raise round-1 deferred findings unless you can show a concrete,
non-theoretical impact in the v1 single-user-loopback scope.

## Disposition guidance

- `fix`: blocking; provide a concrete `resolution` describing what to change
- `regenerate`: rewrite from scratch (rare)
- `accept`: noted but no change needed (a deferred-from-round-1 issue)
- `escalate`: needs human decision

Begin.
