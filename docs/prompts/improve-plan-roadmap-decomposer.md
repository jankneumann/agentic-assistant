# Improve the `plan-roadmap` decomposer — semantic, not syntactic

## Mission

The `plan-roadmap` skill's decomposer (at `.claude/skills/plan-roadmap/scripts/decomposer.py`) currently does **pure structural markdown parsing** — it walks H2/H3 headings, looks for capability/phase/requirement marker words via regex, and infers dependencies from keyword overlap. For well-structured inputs where every capability is an H2/H3 section, that works. For real-world proposals that mix narrative prose, priority tables, sub-sections, and example YAML blocks, it produces noisy and incomplete output.

Your job is to **replace the structural-only approach with a two-pass architecture that combines fast structural parsing with LLM-driven semantic understanding**, and to validate the improvement with a regression test.

## Why this matters — concrete failure mode

The existing decomposer was run on `docs/perplexity-feedback.md` and produced 11 items. A hand-authored reference roadmap at `openspec/roadmap.yaml` contains 22 items for the same input (19 forward-looking + 3 archived). Specifically, the decomposer:

**Missed items entirely** (present in roadmap.yaml, absent from decomposer output):
- `http-tools-layer` — `§5 P0` table row, not a top-level section. The decomposer's `_classify_sections` didn't recognize the priority-labeled table row as a capability.
- `ms-graph-extension` — same: `§5 P0` table row.
- `delegation-context` — perplexity `§3.3` sub-section; the decomposer's capability markers didn't trigger on the sub-section heading.
- `extension-lifecycle` — perplexity `§3.1` sub-section, same issue.
- `harness-routing` — perplexity `§3.2` sub-section.
- **`delegation/router.py`** — `§5 P1` priority item living *inside a table cell*. This is the item that parallel-review-plan's technical dispatch flagged as silently dropped from the pre-iteration-2 roadmap. A semantic pass should pull it out.
- `bootstrap-fixes` — §7 has five sub-items (§7.1 through §7.5); the decomposer picked up only `§7.4` as a standalone item and missed the others, producing `ri-10-7-4-no-pyproject-toml-entry-po` without a sibling bundle.

**Produced noise** (decomposer items that are not real capabilities):
- `ri-06-or-as-an-extension` — a literal misparse of the "Option B" header inside §2.2's YAML example block.
- `ri-07-personas-work-extensions-manif` — parsed from an indented `manifest.yaml` YAML example inside §4.2.
- `ri-08-5-implementation-completeness` — §5 is a priority table; treating the section title as a capability collapses five distinct items into one.
- `ri-11-8-recommended-implementation-o` — §8 is a meta "recommended ordering" section with no new capabilities; decomposer turned it into an item.

**Poor IDs and descriptions**:
- Ugly IDs like `ri-01-1-1-no-observability-layer` (redundant numeric prefixes + raw slug) vs the stable change-id `observability` used in `openspec/roadmap.yaml`.
- Descriptions truncated at arbitrary character boundaries (not sentence-ended), with stray markdown backticks and broken acceptance-outcome bullets.
- Acceptance outcomes often contain just one entry, and it's a colon-ending bullet header (e.g., "Every `harness.invoke()` and `spawner.delegate()` call should emit spans with:") rather than discrete testable outcomes.

**Shallow dependency DAG**:
- Most items depend on `memory-architecture` because the inference is keyword-match (any item mentioning "memory" is a dependent). This is not functional dependency — `observability` doesn't depend on `memory-architecture` in reality; `scheduler` and `obsidian-vault` do.
- No cycle detection for the specific case of "A mentions B mentions A" keyword loops.
- Can't detect the case where an item is archived / completed (all archived phases in `openspec/changes/archive/` are missed entirely because the decomposer only reads the proposal file, not repo state).

**Other bugs**:
- `source_proposal` field writes an absolute path (`/Users/.../docs/...`) instead of a repo-relative one.
- No `change_id` field emitted per item (the model supports it; the decomposer never sets it).
- `status` always defaults to `candidate` even when the same change-id already exists in `openspec/changes/archive/`.

## Reference truth

The correct output for `docs/perplexity-feedback.md` lives at `openspec/roadmap.yaml`. It is hand-authored from the iteration-2 version of `openspec/roadmap.md`, which was reviewed by three independent vendors (Claude, Codex, Gemini) across two review rounds and two iteration passes. Treat this file as the **regression test oracle** for the improved decomposer.

Details that matter:
- 22 items (3 archived → `status: completed`; 19 forward-looking → `status: candidate`).
- Stable `item_id` values matching OpenSpec change-id conventions (kebab-case, no `ri-` prefix, no numeric section prefixes).
- Functional DAG: edges represent real prerequisites (phase B depends on phase A's output), not chronological ordering or keyword overlap. Example: `harness-routing` depends on both `ms-graph-extension` (needs MS Agent Framework real, not stub) and `bootstrap-fixes` (needs perplexity §7.3 `deepagents` package reference reconciled).
- Non-phase items (e.g., `sync-test-privacy-boundary-spec`, `spec-purpose-cleanup`) are flagged via their `description` / `rationale` and have no downstream dependents.
- `source_proposal` is `docs/perplexity-feedback.md` (repo-relative).

## Architecture: two-pass decomposition

Replace the single-pass structural walk with:

### Pass 1: Structural scan (existing, mostly kept)

Retain the fast deterministic parsing — section headings, phase markers, capability keywords — but use it only to build a *candidate pool* of text blocks worth inspecting. Do not yet commit any block to a roadmap item.

Extend Pass 1 to:
- Detect priority tables (markdown tables with columns named `Priority`, `P0`, `P1`, `Impact`, `Module`, etc.) and extract each row as a candidate block.
- Detect sub-sections (H4, H5 headings, and indented lists under an H2/H3) and treat them as candidate blocks distinct from the parent.
- Detect example/illustrative code blocks (fenced code blocks, indented YAML/JSON examples) and **exclude** their contents from the candidate pool.
- Read `openspec/changes/archive/` and `openspec/specs/` to build a map of change-ids that are already archived or have a synced spec — this informs status.

### Pass 2: Semantic consolidation (new, LLM-driven)

For each candidate block from Pass 1, call an LLM with a structured prompt that:

1. Asks *"Is this block describing a roadmap-worthy capability?"* — with one of three answers: **yes** (promote to item), **no** (discard as prose/example/narrative), **merge** (this block refines or is part of an earlier item; concatenate).
2. If yes: extracts a canonical `item_id` (kebab-case, no date prefixes, matching OpenSpec change-id conventions), a concise `title` (one line), a cleaned `description` (sentence-ended, no dangling fragments), and a list of discrete `acceptance_outcomes` (each one independently testable).
3. Asks *"Which earlier item(s) does this depend on functionally?"* — the LLM consults the running item list and names prerequisites by `item_id`, with a one-sentence justification per edge.
4. Flags *kind* — `phase` (new capability / bootstrap-v4.1 item / perplexity-item) vs `non-phase` (spec-sync / tooling / meta).

Use the existing `RoadmapItem` / `Roadmap` dataclasses from `roadmap-runtime/scripts/models.py` — don't introduce a parallel model. Populate `change_id` = `item_id` by default. Use `rationale` to capture the kind-decision justification.

### Pass 3: Validation (tightened existing)

After Pass 2 produces the roadmap:
- Cycle check (existing, works).
- **Cross-check against repo state**: for each item, if `openspec/changes/archive/<date>-<item_id>/` exists, set `status = completed`. If `openspec/changes/<item_id>/` (unarchived) exists, set `status = in_progress`.
- **Regression test**: if `openspec/roadmap.yaml` exists and its `source_proposal` matches the current input, compare the two roadmaps. Log any items missing from either side. Allow drift (authoring judgment can diverge from LLM inference) but surface it for review.
- **Repo-relative path**: ensure `source_proposal` is relative to `repo_root`, not absolute.

## Deliverables

1. **Code changes**: updated `.claude/skills/plan-roadmap/scripts/decomposer.py` (or a new `semantic_decomposer.py` that the skill dispatches to when an LLM client is available; falls back to the existing structural-only decomposer when not). Keep backward compatibility — existing callers should still work.

2. **LLM client integration**: use whatever LLM client is appropriate for the runtime. The `.claude/skills/parallel-infrastructure/scripts/` directory already has vendor-routing helpers; borrow patterns from there. Do NOT hardcode a specific vendor; respect the `agents.yaml` configuration.

3. **Regression test**: `.claude/skills/plan-roadmap/scripts/tests/test_decomposer_semantic.py` that:
   - Takes `docs/perplexity-feedback.md` as input.
   - Runs the improved decomposer.
   - Asserts the output contains all item_ids present in `openspec/roadmap.yaml` (same `source_proposal`) — the 19 non-archived items are the lower bound.
   - Asserts no noise items (i.e., no item whose `item_id` is a slugified fragment of a YAML example — test with a blocklist of known-bad tokens like `or-as-an-extension`, `personas-work-extensions-manif`, `recommended-implementation-o`).
   - Asserts `source_proposal` is repo-relative (does not start with `/`).
   - Asserts items whose `item_id` matches an archived change-id have `status = completed`.

4. **Documentation**: update `.claude/skills/plan-roadmap/SKILL.md` to describe the two-pass architecture, when semantic Pass 2 runs vs falls back, and how to invoke the regression test. Add a brief "Known inputs that stress the decomposer" section listing perplexity-feedback.md as a canonical test case.

5. **Commit structure**: separate commits for (a) Pass 1 extensions (structural improvements — table rows, sub-sections, example-block exclusion, repo-state read), (b) Pass 2 LLM integration, (c) regression test, (d) SKILL.md doc update. Each commit should be independently reviewable.

## Out of scope (don't do these)

- Do not modify `openspec/roadmap.yaml` — it is the test oracle. If the improved decomposer produces different but arguably-correct output, surface the diff; the human decides whether the oracle or the decomposer is right.
- Do not modify the `Roadmap` / `RoadmapItem` dataclasses in `roadmap-runtime/scripts/models.py` unless absolutely required. If you need new fields (e.g., explicit `kind: phase | non-phase`), propose them in a separate OpenSpec change first.
- Do not change the `plan-roadmap` skill's CLI contract or SKILL.md arg surface. The improvement should be internal.
- Do not run `/plan-roadmap` on production inputs as part of testing — use `docs/perplexity-feedback.md` only.
- Do not introduce hard dependencies on a specific LLM vendor (OpenAI, Anthropic, Google). The improvement should work with whichever vendor is configured via the existing coordination MCP / agents.yaml mechanism.

## Acceptance test

After your changes, running `/plan-roadmap docs/perplexity-feedback.md` should:

1. Produce a roadmap with **≥ 19 items** (the 19 non-archived items in `openspec/roadmap.yaml`).
2. Every item's `item_id` must be a valid kebab-case change-id (no `ri-` prefix, no numeric section prefix, no slugified fragments from YAML examples).
3. The DAG must contain these specific functional edges (cross-checked against `openspec/roadmap.yaml`):
   - `memory-architecture` → `bootstrap-fixes`
   - `harness-routing` → `ms-graph-extension` AND `bootstrap-fixes`
   - `delegation-context` → `memory-architecture`
   - `a2a-server` → `ms-graph-extension`
4. The DAG must NOT contain edges that are pure keyword overlap — specifically, `observability` must NOT depend on `memory-architecture` (the old decomposer asserted this; it's wrong).
5. The `source_proposal` field must be `docs/perplexity-feedback.md`, not an absolute path.
6. Items whose `item_id` matches an archived change-id (e.g., `bootstrap-vertical-slice`) must have `status = completed`, not `candidate`.
7. No item whose `item_id` contains any of: `or-as-an-extension`, `personas-work-extensions-manif`, `recommended-implementation-o`, `implementation-completeness`, `5-implementation`, `8-recommended`.

## Context pointers

- Existing decomposer: `.claude/skills/plan-roadmap/scripts/decomposer.py`
- Existing scaffolder: `.claude/skills/plan-roadmap/scripts/scaffolder.py`
- Shared runtime models: `.claude/skills/roadmap-runtime/scripts/models.py`
- Vendor dispatch patterns: `.claude/skills/parallel-infrastructure/scripts/review_dispatcher.py` (for how to dispatch to codex/gemini/claude)
- Agent config: `agents.yaml` (location varies by runtime; see `.claude/skills/parallel-infrastructure/scripts/__main__.py` `--list-agents`)
- Test oracle: `openspec/roadmap.yaml` (hand-authored from iteration-2 review convergence)
- Source input: `docs/perplexity-feedback.md` (the canonical review doc)
- Reference iteration notes: `openspec/changes/roadmap-v2-reconciliation/session-log.md` (explains why the hand-authored version is what it is)

## One stylistic ask

Write the semantic-pass prompt so another agent reading this repo later can understand *why* each LLM call is asking what it's asking. Comment the prompt template inline explaining what you expect the LLM to do differently from a structural regex. The failure mode to guard against: an engineer a year from now looking at a 500-line prompt and having no idea which parts are load-bearing vs legacy.
