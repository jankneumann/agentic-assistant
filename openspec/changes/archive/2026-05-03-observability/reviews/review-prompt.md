# Plan Review — observability

You are reviewing an OpenSpec plan. Read all artifacts under `openspec/changes/observability/` and produce a structured critique.

## Files to read

- `openspec/changes/observability/proposal.md` — Why, What Changes, Impact, Approaches Considered, Selected Approach
- `openspec/changes/observability/design.md` — 13 decisions: module layout, degradation state machine, hook integration, contextvars propagation, sanitization ordering, flush lifecycle, noop zero-allocation, test strategy, docker init vars (DUMMY prefixed), Stop hook, test fixtures, optional extra rationale, empty-string credential handling
- `openspec/changes/observability/specs/observability/spec.md` — 13 ADDED Requirements, 31 scenarios
- `openspec/changes/observability/specs/harness-adapter/spec.md` — 1 ADDED Requirement (harness invocation tracing, MS Agent stub case)
- `openspec/changes/observability/specs/delegation-spawner/spec.md` — 1 ADDED Requirement (delegation tracing + 256-char hashing)
- `openspec/changes/observability/specs/extension-registry/spec.md` — 1 ADDED Requirement (extension tool tracing)
- `openspec/changes/observability/specs/capability-resolver/spec.md` — 1 ADDED Requirement (aggregation-site wrapping)
- `openspec/changes/observability/specs/http-tools/spec.md` — 1 ADDED Requirement (http-tool tracing + sanitization cross-ref)
- `openspec/changes/observability/tasks.md` — 43 tasks, 5 phases, TDD-ordered
- `openspec/changes/observability/work-packages.yaml` — 4 coordinated work packages
- `openspec/changes/observability/session-log.md` — decision records (Plan + Plan Iteration 1)

## What to evaluate

Score the plan on these axes and flag any issue as a structured finding:

1. **Specification completeness** — every Requirement has scenarios; every task maps to a Requirement; Impact section matches actual spec deltas
2. **Contract/interface consistency** — the Protocol signatures in `design.md` match the Protocol Requirement in `observability/spec.md`; the `tool_kind` and `op` enums are the same everywhere they appear
3. **Architecture soundness** — singleton provider lifecycle, contextvars propagation, aggregation-site wrapping pattern, 4-package DAG. Any decision that would produce churn, lock contention, or a design that doesn't scale?
4. **Security** — sanitization regex ordering, committed dev-default credentials, outbound-only posture, persona attribute passthrough, any missing secret patterns
5. **Performance** — noop allocation behavior, flush mode semantics, sanitization cost on every span attribute
6. **Testability** — can the specified scenarios actually be verified in CI? Any requirements that would be flaky on shared runners?
7. **Parallelizability** — scope overlap between packages, task ordering within packages, locks. Are there file-overlap conflicts?
8. **Correctness** — factual errors (function names, file paths), logical contradictions between documents, requirements that don't actually specify what the text says they specify

## Output format

Output ONLY a single JSON document conforming to the schema at `agentic-coding-tools/openspec/schemas/review-findings.schema.json`. No prose, no markdown wrapper, no commentary before or after.

Required shape:

```json
{
  "review_type": "plan",
  "target": "observability",
  "reviewer_vendor": "<your vendor name, e.g. codex or gemini>",
  "findings": [
    {
      "id": 1,
      "type": "spec_gap | contract_mismatch | architecture | security | performance | style | correctness | observability | compatibility | resilience",
      "criticality": "low | medium | high | critical",
      "description": "<1–3 sentence description>",
      "resolution": "<optional concrete fix>",
      "disposition": "fix | regenerate | accept | escalate",
      "file_path": "<optional path relative to repo root>",
      "line_range": {"start": <int>, "end": <int>}
    }
  ]
}
```

**Disposition values**:
- `fix` — straightforward edit will address
- `regenerate` — section needs rework
- `accept` — noted but not blocking
- `escalate` — human judgment needed

Prioritize **confirmed, high-confidence findings**. Do NOT invent issues to fill quota. An empty findings array is acceptable if the plan is solid. Focus on things a second pair of eyes would reasonably catch that the primary reviewer missed.
