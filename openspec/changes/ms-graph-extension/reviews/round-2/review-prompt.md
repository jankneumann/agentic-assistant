# Review Prompt — ms-graph-extension PLAN_REVIEW round 2

## Context

This is **round 2** of multi-vendor PLAN_REVIEW for the OpenSpec change `ms-graph-extension` (Phase P5 — Microsoft 365 extensions and MSAF harness).

**History:**
- Round 1 of PLAN_REVIEW (claude+codex+gemini) ran previously and surfaced 12 findings — all remediated in commit `1cecb0f` adding D13–D27 to design.md and ~30 tasks.
- Subsequently, autopilot PLAN_ITERATE (claude_code, opus 4.7, single agent with 5 parallel Explore subagents) found and remediated 14 additional findings in commit `563688c`. PLAN_ITERATE additions:
  - New `specs/observability/spec.md` MODIFIED requirement adding `trace_graph_call` to `ObservabilityProvider` Protocol
  - graph-client/spec.md: HTTP client async lifecycle (`__aenter__`/`__aexit__`/`aclose`) requirement
  - graph-client/spec.md: cross-domain redirect rejection requirement (trusted_hosts validation, `follow_redirects=False`)
  - graph-client/spec.md: 429 Retry-After past-date and malformed-value scenarios
  - ms-extensions/spec.md: Pagination Discipline (no N+1 Graph fetches in list-tools)
  - ms-extensions/spec.md: Per-Tool Page Ceiling Configuration
  - msal-auth/spec.md: replaced "event loop MUST remain responsive" with measurable timing
  - extension-registry/spec.md: real factory called with `persona=None` raises actionable TypeError scenario
  - design.md D5: pinned `agent-framework>=1.0.0,<2.0.0`
  - work-packages.yaml: fixed stale path `core/observability.py` → `telemetry/providers/{base,noop,langfuse}.py`; bumped wp-foundation `loc_estimate` 1900 → 3000
  - tasks.md: new section 9 (~15 tasks)

## Your Task

Review the plan **as it now stands** (post-iteration-1) and produce findings JSON conforming to `openspec/schemas/review-findings.schema.json`.

**Focus areas (round 2 specific):**

1. **Did PLAN_ITERATE introduce new bugs?** Cross-document inconsistencies between the new content and existing requirements/scenarios. The PLAN_ITERATE pass added 18+ new scenarios; verify each is consistent with surrounding requirements.

2. **Did PLAN_ITERATE close round-1 findings without regressing?** Round-1 found e.g. paginate-yield contradiction (D4 vs spec); page-ceiling silent truncation; MSAL gitignore check. Verify these stay closed.

3. **New attack surface added by PLAN_ITERATE:** `trusted_hosts` constructor arg, `__aenter__`/`__aexit__`, `MSAL_FALLBACK_DEVICE_CODE` env var, observability `trace_graph_call` Protocol method. Each is a new contract surface — review for completeness, edge cases, and abuse paths.

4. **Plan readiness for `/implement-feature`:** Are all spec scenarios concrete enough that an agent could write the test from spec alone? Is every new requirement covered by at least one task in tasks.md? Does work-packages.yaml correctly own each new file?

5. **Anything still missing.** Things round-1 reviewers and PLAN_ITERATE agents both missed. Some examples to consider:
   - Concurrency on token cache file (multiple async tasks refreshing token simultaneously)
   - Behavior when `agent-framework` version pin needs to change post-merge
   - What happens if `personas/<name>/.cache/` directory does not exist when first token write attempts
   - Test-fixture privacy boundary (CLAUDE.md G6) for Graph response fixtures
   - Whether new `observability` spec delta needs an Impact-section migration plan note

**Output format:** JSON object (NOT array) at the top level matching `review-findings.schema.json`. Required keys: `review_type` ("plan"), `target` ("ms-graph-extension"), `reviewer_vendor` (your vendor name, e.g., "codex"), `findings` (array of finding objects with id, type, criticality, description, resolution, disposition).

**Limit yourself to ~10 findings ranked by criticality.** Critical/high findings get prioritized for fixing; medium for triage; low for documentation. Each `description` should cite specific files and line numbers where relevant.

**Available files (read-only):**
- `openspec/changes/ms-graph-extension/proposal.md`
- `openspec/changes/ms-graph-extension/design.md`
- `openspec/changes/ms-graph-extension/tasks.md`
- `openspec/changes/ms-graph-extension/work-packages.yaml`
- `openspec/changes/ms-graph-extension/session-log.md`
- `openspec/changes/ms-graph-extension/specs/extension-registry/spec.md`
- `openspec/changes/ms-graph-extension/specs/graph-client/spec.md`
- `openspec/changes/ms-graph-extension/specs/harness-adapter/spec.md`
- `openspec/changes/ms-graph-extension/specs/ms-agent-framework-harness/spec.md`
- `openspec/changes/ms-graph-extension/specs/ms-extensions/spec.md`
- `openspec/changes/ms-graph-extension/specs/msal-auth/spec.md`
- `openspec/changes/ms-graph-extension/specs/observability/spec.md`  ← NEW in iteration 1
- `openspec/changes/ms-graph-extension/contracts/README.md`

**Past artifacts** (informational only — do not re-litigate already-closed findings unless they regressed):
- `openspec/changes/ms-graph-extension/reviews/round-1/findings-{claude,codex,gemini}-plan.json`
- `openspec/changes/ms-graph-extension/reviews/round-1/consensus-plan.json`

Write your findings JSON to `openspec/changes/ms-graph-extension/reviews/round-2/findings-<your-vendor>-plan.json`.
