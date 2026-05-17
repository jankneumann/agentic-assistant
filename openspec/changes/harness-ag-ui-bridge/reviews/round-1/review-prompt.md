# Plan Review: harness-ag-ui-bridge — Round 1

You are an independent plan reviewer for the OpenSpec change `harness-ag-ui-bridge`.
Follow the `parallel-review-plan` skill behavior: read the plan artifacts as
read-only input and produce structured findings conforming to
`review-findings.schema.json`.

## Output contract

Emit **only** a single JSON object conforming to
`openspec/schemas/review-findings.schema.json`. No commentary, no markdown wrapping
around the JSON. Include all required fields per finding: `id`, `type`,
`criticality`, `description`, `disposition`, `axis`, `severity`. Set
`reviewer_vendor` to your model identifier. Include `resolution` whenever you
recommend `disposition: fix` — that text becomes the fix instruction.

## Input artifacts (read-only)

Working directory: `.` (this is the worktree root).

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
- `openspec/changes/harness-ag-ui-bridge/session-log.md` (history of revisions)
- `openspec/changes/harness-ag-ui-bridge/loop-state.json` (already-fixed vs deferred findings)

## Context (do not re-review what is already fixed)

This plan has been through one PLAN_ITERATE pass. The following findings were
**already addressed inline** — do not re-raise them unless you find a residual gap:

- client disconnect scenario (web-server)
- empty response scenario (web-server)
- no-enabled-harness scenario (web-server lifespan)
- no `default_role` scenario (cli-interface)
- unknown harness scenario (cli-interface)
- non-loopback warning scenario (cli-interface)
- MSAF task 2.2 wording cleanup
- D8 updated with class-name-only error redaction
- D12 added: auth posture warn-not-refuse for non-loopback
- D13 added: trust sse-starlette for backpressure + disconnect contract

The following were **explicitly deferred to this review** for vendor consensus.
Please weigh in on each:

1. **wp-web-cli split** — should `wp-web-cli` be split into `wp-web` (FastAPI app +
   SSE endpoint) and `wp-cli` (the `serve` subcommand)? Current shape keeps them
   together because the CLI is a thin wrapper around the ASGI app.
2. **Rate limiting** — should v1 require rate limiting on `/chat`? The current
   posture is "v1 = single-user local-trust; no rate limiting." Justify keep or
   add.
3. **Backpressure** — D13 trusts `sse-starlette` for backpressure and client
   disconnect handling. Is that sufficient, or should the spec call out an
   explicit backpressure requirement?
4. **Mandatory auth middleware** — should the FastAPI app refuse to start without
   an auth middleware configured, even for loopback? D12 chose warn-not-refuse.
5. **Input length validation** — `ChatRequest.message` has `minLength: 1` but
   no `maxLength`. Should v1 cap message size? At what bound?
6. **Scenario IDs vs names** — spec deltas currently use `#### Scenario: <name>`
   anchors. Should scenarios also carry stable IDs (e.g., `web-server.3`) for
   test traceability per the tasks.md convention?
7. **ag_ui version pin in spec** — should the spec deltas pin the upstream
   `ag-ui-protocol` Python package version, or leave that to `pyproject.toml`?

## Review dimensions

Apply the standard plan-review dimensions from the `parallel-review-plan` skill:
- Specification completeness (SHALL/MUST, testability, scenarios)
- Contract consistency (OpenAPI ↔ JSON Schema ↔ specs)
- Architecture alignment (existing harness boundary, persona privacy)
- Security review (auth, secrets, input validation)
- Performance review (streaming, bounded queries, rate limiting)
- Observability review (the `@traced_harness` decorator, span structure)
- Compatibility review (additive HarnessEvent, MSAF parity)
- Resilience review (retry, timeout, fallback for SSE)
- Work-package validity (DAG, scopes, lock keys, parallelism)

## Calibration

- **critical**: would cause CI failure or block implementation (validate fails,
  missing spec delta for a referenced capability, contract contradicts spec)
- **high**: would force a follow-up change to land v1 (ambiguous SHALL,
  untestable scenario, contract-spec mismatch on event shape, security gap on
  a documented surface)
- **medium**: would degrade quality but is fixable post-merge (missing edge
  scenario, missing observability requirement, suboptimal task split)
- **low**: polish, wording, optional sections

Be **selective**. This is a v1 plan for a single-user local SSE bridge.
Do not raise findings that demand multi-tenant, multi-user, or production-hardening
features beyond the documented v1 scope (loopback-only, single-process,
single-thread-id, no auth).

## Disposition guidance

- `fix`: blocking; provide a concrete `resolution` describing what to change
- `regenerate`: the artifact needs rewriting from scratch (rare)
- `accept`: noted but no change needed (e.g., deferred to a future change)
- `escalate`: needs human decision, not vendor consensus

Begin.
