# Plan Review: harness-ag-ui-bridge — Round 2 (convergence verification)

You are an independent plan reviewer for the OpenSpec change `harness-ag-ui-bridge`.
This is the SECOND round of a multi-vendor convergence loop. Your job is to
verify that round-1 fixes correctly addressed the cross-vendor findings and
to surface any NEW issues introduced by those fixes or missed in round 1.

## Output contract

Emit **only** a single JSON object conforming to
`openspec/schemas/review-findings.schema.json`. No commentary, no markdown
wrapping around the JSON. Include all required fields per finding: `id`,
`type`, `criticality`, `description`, `disposition`, `axis`, `severity`. Set
`reviewer_vendor` to your model identifier. Include `resolution` whenever you
recommend `disposition: fix`.

## What changed since round 1

Commit `5f4e8f8` applied these inline fixes for cross-vendor round-1 themes:

1. **mapper signature**: `map_harness_to_ag_ui(stream, *, thread_id: str)` —
   thread_id is now keyword-only required; raises `ValueError` on empty.
   The mapper emits `threadId` on every `RUN_STARTED` and `RUN_FINISHED`.
2. **Two-phase error contract (D8)**: Phase 1 = harness yields terminal
   `RunFinished(error=<ClassName>)` with class-name-only redaction. Phase 2
   = harness re-raises original exception; `@traced_harness` captures it;
   the mapper absorbs the re-raise (no synthetic events, no double terminal).
   This contract is now referenced consistently in harness-adapter spec
   (both Deep Agents and MSAF exception scenarios), ag-ui-emitter spec
   (Error Mapping requirement + 2 scenarios), web-server spec (harness-fails
   scenario), and both JSON schemas (`error` field constrained to
   `^[A-Z][A-Za-z0-9_.]*$`).
3. **Module boundary (D6)**: `HarnessEvent` lives at
   `src/assistant/harnesses/sdk/events.py`. D6 now states the explicit
   import-direction rule: web → transports → harnesses (never the reverse).
4. **maxLength on `ChatRequest.message`**: 32768 cap added in OpenAPI;
   web-server "Endpoint rejects messages exceeding the maxLength bound"
   scenario added; new task 5.3c implements custom
   `RequestValidationError` → RFC 7807 Problem handler.
5. **MSAF exception observability**: new scenario "MSAF astream_invoke is
   traced on exception" parallel to the Deep Agents one.
6. **Web-server response scenario**: now asserts the full
   TEXT_MESSAGE_START → TEXT_MESSAGE_CONTENT → TEXT_MESSAGE_END bracketing
   end-to-end through the SSE stream.
7. **OpenAPI 422**: documents `application/problem+json` with examples for
   missing field AND oversize message; ties to the new exception handler task.

## Already-deferred (do not re-raise)

The following were single-vendor findings in round 1 and were intentionally
deferred to follow-up GitHub issues rather than fixed inline:

- `wp-web-cli` package split into `wp-web` + `wp-cli` (cosmetic)
- `serve --harness` default value should derive from persona config rather
  than literal `deep_agents`

Do **not** re-raise these unless you find them genuinely blocking.

## Review focus for round 2

Prioritize, in order:
1. **Verify the round-1 fixes are internally consistent.** Do the
   harness-adapter, ag-ui-emitter, web-server, and contract artifacts
   describe the same two-phase contract without contradiction?
2. **New regressions.** Did any of the fixes introduce a scenario that
   contradicts an existing requirement or task?
3. **Missed corners.** Anything genuinely blocking that round 1 should
   have caught but didn't.

Be **selective**. The plan is for a v1 single-user local SSE bridge.
Do not raise findings that demand multi-user, multi-tenant, or
production-hardening features beyond v1 scope. Polish-level wording
findings should be `low` criticality at most.

## Input artifacts (read-only)

Working directory: `.`

- `openspec/changes/harness-ag-ui-bridge/proposal.md`
- `openspec/changes/harness-ag-ui-bridge/design.md`
- `openspec/changes/harness-ag-ui-bridge/tasks.md`
- `openspec/changes/harness-ag-ui-bridge/work-packages.yaml`
- `openspec/changes/harness-ag-ui-bridge/specs/harness-adapter/spec.md`
- `openspec/changes/harness-ag-ui-bridge/specs/web-server/spec.md`
- `openspec/changes/harness-ag-ui-bridge/specs/cli-interface/spec.md`
- `openspec/changes/harness-ag-ui-bridge/specs/ag-ui-emitter/spec.md`
- `openspec/changes/harness-ag-ui-bridge/contracts/openapi/v1.yaml`
- `openspec/changes/harness-ag-ui-bridge/contracts/events/harness-event.schema.json`
- `openspec/changes/harness-ag-ui-bridge/contracts/events/ag-ui-events.schema.json`
- `openspec/changes/harness-ag-ui-bridge/reviews/round-1/consensus.json` (the
  round-1 findings you and the other vendors raised)

## Calibration

- **critical**: blocks implementation (validate fails, missing spec delta,
  contract contradicts spec, two artifacts encode incompatible contracts)
- **high**: would force a follow-up to land v1 (untestable scenario,
  contract-spec mismatch, regression introduced by a round-1 fix)
- **medium**: degrades quality but is fixable post-merge
- **low**: polish, wording

## Disposition guidance

- `fix`: blocking; provide `resolution`
- `accept`: noted but no change needed
- `escalate`: needs human decision

Begin.
