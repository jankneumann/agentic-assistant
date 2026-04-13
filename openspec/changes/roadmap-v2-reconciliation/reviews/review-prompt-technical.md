# Technical Review — roadmap-v2-reconciliation (post-iteration 1)

**Critical framing**: A prior review dispatch (stored as `findings-codex-plan.json` / `findings-gemini-plan.json`) focused on spec-mechanics and OpenSpec consistency. That review was valuable but shallow on **substantive technical correctness** of the plan's content. This re-review is specifically asked to focus on the *technical content* of the plan, not its form.

## What this change does (short version)

Modifies the `tooling-roadmap` capability spec's "Roadmap Document Authoritative" requirement to add a three-criterion classification rule for what constitutes a "phase change" vs a non-phase change. Updates `openspec/roadmap.md` to insert two new rows (P1.5 `test-privacy-boundary`, P1.6 `sync-test-privacy-boundary-spec`) and renumbers the existing P1.5 `bootstrap-fixes` to P1.7. Updates the Dependency graph accordingly.

Plan docs are at `openspec/changes/roadmap-v2-reconciliation/{proposal,design,tasks}.md` and the spec delta is at `openspec/changes/roadmap-v2-reconciliation/specs/tooling-roadmap/spec.md`. The actual roadmap edit is already staged at `openspec/roadmap.md`. The current `tooling-roadmap` spec (post-archive of the parent change) is at `openspec/specs/tooling-roadmap/spec.md`.

## What this review SHOULD focus on

**Walk through the 18-phase roadmap at `openspec/roadmap.md` and verify the plan's content against reality.** Specifically:

### 1. Classification coverage

The new requirement defines three criteria for "phase change":
1. Introduces a new capability spec
2. Implements a bootstrap-v4.1 P-item or perplexity §8 item
3. Represents a committed milestone promoted by authoring judgment

**Apply each criterion to every phase P1, P1.5, P1.6, P1.7, P2–P18** (18 phases total) and report which phases don't fit criteria 1 or 2 cleanly and must fall through to criterion 3. A phase that requires criterion 3 ("authoring judgment") is a weakness in the classification rule, not a feature — it means the rule doesn't really operationalize classification for that case.

For example: does P1.7 `bootstrap-fixes` (implements perplexity **§7** hygiene items, not §8) cleanly fit criterion 2's literal text "perplexity §8 item"? If not, propose a rewording.

### 2. DAG accuracy

The new dependency graph at `openspec/roadmap.md` lines 56–73 shows:
```
P1 (archived)
 └─→ P1.5 test-privacy-boundary (archived; hygiene)
      └─→ P1.6 sync-test-privacy-boundary-spec (archived; spec-sync for P1.5)
           └─→ P1.7 bootstrap-fixes (pending; hygiene; unblocks everything below)
                ├─→ P2 memory-architecture ...
```

**Evaluate each directed edge**: does phase B actually depend on phase A's outputs, or is the edge an artifact of the renumbering?

Specifically: does `bootstrap-fixes` (which touches `cli.py`, `db.py`, `pyproject.toml`, `persona.py`) actually depend on the outputs of `test-privacy-boundary` (which touches `tests/conftest.py`, `tests/_privacy_guard_*.py`, `scripts/push-with-submodule.sh`)? Use `openspec/changes/archive/2026-04-13-test-privacy-boundary/` and `docs/perplexity-feedback.md` §7 to verify.

If the DAG documents phantom edges, that violates the `Requirement: Dependency Graph Representation` scenario "Prerequisites reference real phases" which states phase A's status SHALL be archived before phase B's status may transition to in-progress. (Archived predecessors don't block anything temporally, but documented prerequisites that aren't real create misleading expectations for future readers.)

### 3. Classification vs. listing consistency

The new spec allows non-phase changes (like spec-sync) to be *listed* in the roadmap table as an authoring choice. P1.6 `sync-test-privacy-boundary-spec` is listed as a top-level phase row despite being a spec-sync (non-phase by criteria).

Is this visually misleading — does listing a non-phase at the same hierarchical level as real phases confuse the roadmap's signal? Propose alternatives (sub-row, annotation, separate "Addenda" section, footnote) or accept.

### 4. Acceptance coverage

The perplexity review document (`docs/perplexity-feedback.md`) contains §§1–§8. Sections §1 (structural gaps), §2 (chief-of-staff gaps), §3 (architecture refinements), §4 (security), §5 (implementation completeness), §6 (A2A), §7 (minor fixes), §8 (recommended implementation order). Does the 18-phase roadmap actually provide a phase for every actionable item in §§1–§7, or are items silently dropped? Specifically check: are all of perplexity's P0/P1/P2 items from §5's table covered by some phase?

### 5. Renumbering impact

The renumbering `P1.5 bootstrap-fixes → P1.7` may leave stale references. Grep the repo for P-number references and report any that still point at the old numbering. Check at minimum: `CLAUDE.md`, `openspec/changes/archive/**`, session logs under `openspec/changes/roadmap-v2-reconciliation/`, any docs under `docs/`.

### 6. Out-of-scope / follow-up adequacy

The proposal's "Out of scope" section punts `Purpose` cleanup to a follow-up (based on the iterate-on-plan finding F#1). Is that follow-up realistic, or does it require changes to OpenSpec tooling that aren't tracked anywhere? Should it be a P-numbered phase in the roadmap itself?

## Input files (read-only)

Required:
- `openspec/changes/roadmap-v2-reconciliation/proposal.md`
- `openspec/changes/roadmap-v2-reconciliation/design.md`
- `openspec/changes/roadmap-v2-reconciliation/tasks.md`
- `openspec/changes/roadmap-v2-reconciliation/specs/tooling-roadmap/spec.md`
- `openspec/changes/roadmap-v2-reconciliation/session-log.md`
- `openspec/roadmap.md` (the edited roadmap on this branch)
- `openspec/specs/tooling-roadmap/spec.md` (the spec as it stands on main, post-archive of the parent change)
- `docs/perplexity-feedback.md` (the canonical review the plan cites — §§1–§8)

Optional context:
- `openspec/changes/archive/2026-04-13-test-privacy-boundary/` and `archive/2026-04-13-sync-test-privacy-boundary-spec/` (to verify DAG edges)
- `openspec/changes/archive/2026-04-13-roadmap-v2-perplexity-integration/` (the parent change artifacts)

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
      "type": "spec_gap | architecture | correctness | compatibility | observability | resilience | performance | security | style | contract_mismatch",
      "criticality": "critical | high | medium | low",
      "description": "Concrete, evidence-cited description. When applicable, name specific phases (e.g., 'P1.7 does not fit criterion 2 because ...'). Cite file:line where possible.",
      "resolution": "Specific actionable fix with proposed wording or structural change.",
      "disposition": "fix | regenerate | accept | escalate"
    }
  ]
}
```

**Do not reproduce findings from the prior dispatch** (the ones at `reviews/findings-{codex,gemini}-plan.json`) unless you find they were resolved incorrectly. Focus on **new, technical, substantive** findings that emerge from the six focus areas above.

If a focus area yields no findings, say so explicitly via an `"id": 0` sentinel finding with `"criticality": "low"` and `"disposition": "accept"` describing what you checked and confirmed. This helps distinguish "no issues found" from "didn't look."
