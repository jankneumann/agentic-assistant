# Review: roadmap-v2-reconciliation plan

You are reviewing an OpenSpec plan (proposal + design + tasks + spec delta). This is a **docs + spec** change that (1) narrows the `tooling-roadmap` capability's "Roadmap Document Authoritative" requirement so non-phase changes (meta / tooling / spec-sync) don't self-violate the spec, (2) updates the spec's `Purpose` placeholder, and (3) adds P1.5 / P1.6 roadmap rows for the archived `test-privacy-boundary` and `sync-test-privacy-boundary-spec` changes, bumping `bootstrap-fixes` from P1.5 to P1.7.

## Context

- The parent change `roadmap-v2-perplexity-integration` was merged and archived immediately prior; its Codex P2 review finding is what this reconciliation addresses.
- This is **planning-only** — no production code, no new tests.
- Validation is via `openspec validate --strict` (already passes) and manual roadmap-row accuracy check.

## Inputs (read-only)

Read these files before producing findings:

- `openspec/changes/roadmap-v2-reconciliation/proposal.md`
- `openspec/changes/roadmap-v2-reconciliation/design.md`
- `openspec/changes/roadmap-v2-reconciliation/tasks.md`
- `openspec/changes/roadmap-v2-reconciliation/specs/tooling-roadmap/spec.md` (the MODIFY delta)
- `openspec/changes/roadmap-v2-reconciliation/work-packages.yaml`
- `openspec/changes/roadmap-v2-reconciliation/contracts/README.md`
- `openspec/changes/roadmap-v2-reconciliation/session-log.md`
- `openspec/roadmap.md` (the actual edited roadmap — implementation is already staged on this branch)
- `openspec/specs/tooling-roadmap/spec.md` (the spec as it exists post-archive of the parent change; the Purpose placeholder is here)

Contextual files (optional):
- `openspec/changes/archive/2026-04-13-roadmap-v2-perplexity-integration/` — the prior change for reference
- `docs/perplexity-feedback.md` — the canonical review doc the roadmap cites

## Review dimensions

Apply the standard parallel-review-plan checklist with emphasis on:

- **Specification completeness**: Are SHALL/MUST obligations testable? Do scenarios describe positive obligations vs. negative permissions?
- **Correctness**: Does the plan actually achieve what it claims? (Specifically: the spec's `Purpose` field — can it be updated via an OpenSpec delta file?)
- **Architecture alignment**: Is "phase change" defined operationally enough for consistent authoring decisions?
- **Compatibility**: Does renumbering P1.5→P1.7 create referential issues? Are any other places in the repo (CLAUDE.md, session logs, archived proposals) affected?

## Output

Output **only** a JSON document conforming to the shape below (no markdown prose, no code fences outside the JSON):

```json
{
  "review_type": "plan",
  "target": "roadmap-v2-reconciliation",
  "reviewer_vendor": "<your vendor name, e.g. codex or gemini>",
  "findings": [
    {
      "id": 1,
      "type": "spec_gap | contract_mismatch | architecture | security | performance | style | correctness | observability | compatibility | resilience",
      "criticality": "critical | high | medium | low",
      "description": "Concrete, evidence-cited description of the issue",
      "resolution": "Specific actionable fix",
      "disposition": "fix | regenerate | accept | escalate"
    }
  ]
}
```

Be specific. Cite file paths and line-level evidence where possible. If you find no issues, return `"findings": []`. Do not invent problems; if a dimension is N/A (e.g. security on a docs-only change), omit it.
