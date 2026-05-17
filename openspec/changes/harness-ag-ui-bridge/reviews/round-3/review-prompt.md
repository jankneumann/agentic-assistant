# Plan Review: harness-ag-ui-bridge — Round 3 (final convergence verification)

You are an independent plan reviewer for the OpenSpec change `harness-ag-ui-bridge`.
This is the THIRD and FINAL round of a multi-vendor convergence loop
(max_rounds=3). Your job is to verify that round-2 fixes correctly addressed
the round-2 findings and to surface any genuinely-blocking issue that would
prevent implementation from starting.

## Output contract

Emit **only** a single JSON object conforming to
`openspec/schemas/review-findings.schema.json`. No commentary, no markdown
wrapping. Required fields per finding: `id`, `type`, `criticality`,
`description`, `disposition`, `axis`, `severity`. Set `reviewer_vendor` to
your model identifier. Include `resolution` whenever you recommend
`disposition: fix`.

## What changed since round 2 (commit 76cf10c)

The round-2 review surfaced 13 findings, of which 2 were critical, 4 high,
1 medium, 6 low. The 6 critical/high issues were all addressed inline:

1. **Class-name regex** now allows dotted lowercase module prefixes
   (`asyncio.CancelledError` validates). Pattern is
   `^(?:[a-z_][a-zA-Z0-9_]*\.)*[A-Z][A-Za-z0-9_]*$` in both JSON schemas.
2. **work-packages.yaml stale paths** for `HarnessEvent` corrected from
   `src/assistant/transports/ag_ui/events.py` to
   `src/assistant/harnesses/sdk/events.py` (3 occurrences).
3. **`@traced_harness` location** fixed from `src/assistant/observability/**`
   to `src/assistant/telemetry/decorators.py` (the actual repo location).
   `wp-foundation` write_allow / locks / outputs / verification all aligned.
4. **RUN_ERROR migration** (the largest fix): upstream
   `ag_ui.core.RunFinishedEvent` has NO `error` field. Round-1 had encoded
   a non-existent field. Failures now map to AG-UI `RUN_ERROR` (matching
   upstream `RunErrorEvent` shape with `message` + `code` fields). Updated:
   - `ag-ui-events.schema.json`: added `RunError` variant, removed `error`
     from `RunFinished`
   - ag-ui-emitter spec: event type coverage now 9 types (added RUN_ERROR);
     Error Mapping requirement rewritten; 3 scenarios cover success path,
     failure path, and missing-Phase-1 raise
   - design.md D8 mapper-behavior paragraph rewritten
   - web-server spec harness-failure scenario rewritten
5. **SdkHarnessAdapter `thread_id` contract**: new requirement added to
   the harness-adapter spec (scenario: "SdkHarnessAdapter exposes a
   thread_id for transport binding"). Deep Agents reuses `self._thread_id`;
   MSAF synthesizes a UUID at construction. Web route uses the public
   `harness.thread_id` (not `_thread_id`).
6. **Task 5.10 dependencies** now include 3b.7; task 2.2 updated to also
   require the `thread_id` property on the base.
7. **Polish**: SSE citation corrected to WHATWG HTML / EventSource;
   stale "optional ag-ui-protocol" language removed from wp-foundation
   description; `plan_revision` bumped to 3.

## Already-deferred (do not re-raise)

These were single-vendor low/medium findings deferred to follow-up issues:
- `wp-web-cli` split into `wp-web` + `wp-cli` (cosmetic)
- `serve --harness` default vs persona config (single vendor)
- `tool_name` vs `toolCallName` naming asymmetry (intentional: internal vs
  protocol field naming; accepted)
- maxLength chars vs bytes interpretation (Python defaults to chars; accepted)

## Review focus for round 3

Be **highly selective**. This is the final round before IMPLEMENT.
Only raise a finding if it is genuinely blocking implementation. Specifically:

1. **Verify round-2 fixes are internally consistent.** Do the
   ag-ui-emitter spec, ag-ui-events schema, harness-adapter spec,
   web-server spec, and design.md D8 all describe the same RUN_ERROR
   semantics without contradiction?
2. **Verify upstream-type alignment.** Does the spec's mention of
   `RunErrorEvent.message` and `RunErrorEvent.code` match what the
   installed `ag_ui.core.RunErrorEvent` actually exposes? If not, that
   is blocking.
3. **Verify thread_id contract.** Is the harness-adapter base spec
   requirement actually implementable by both Deep Agents (existing
   `_thread_id`) and MSAF (synthesized UUID)?
4. **Catch any remaining stale path or stale field reference** that
   would cause `openspec validate --strict` to pass but implementation
   to fail.

Polish-level wording findings should be `low` criticality at most.
Cosmetic improvements should not be raised in round 3.

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
- `openspec/changes/harness-ag-ui-bridge/reviews/round-2/consensus.json` (the
  prior round's findings)

## Calibration

- **critical**: blocks implementation (validate fails, two artifacts encode
  incompatible contracts, upstream type reference is wrong, stale path)
- **high**: would force a follow-up to land v1
- **medium**: degrades quality but is fixable post-merge
- **low**: polish, wording

## Disposition guidance

- `fix`: blocking; provide `resolution`
- `accept`: noted but no change needed
- `escalate`: needs human decision

Begin.
