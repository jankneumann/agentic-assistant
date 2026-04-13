# Design — roadmap-v2-perplexity-integration

## Scope recap

This change is **planning-only**. No production code changes. Artifacts:

1. `openspec/roadmap.md` — full rewrite
2. `openspec/changes/roadmap-v2-perplexity-integration/specs/tooling-roadmap/spec.md` — new capability
3. `docs/perplexity-feedback.md` — canonical review reference
4. This change's own proposal/tasks/design/work-packages

## Decisions

### D1: Single-document roadmap over per-phase stubs

**Decision**: Adopt Approach A from `proposal.md` — one rewritten
`roadmap.md` plus one capability spec.

**Rejected alternatives**:
- Approach B (pre-scaffold 18 stub directories): rejected because it
  would clutter `openspec list` output for the project's entire
  multi-month execution window and because stub content drifts faster
  than the roadmap it shadows.
- Approach C (CI-enforced DAG via `scripts/validate-roadmap.py`):
  rejected because the maintenance burden of CI gates over documentation
  state outweighs the benefit at current project scale. If multiple
  developers later run phases concurrently, enforcement becomes a
  separate follow-up proposal.

### D2: Perplexity §8 ordering is authoritative

**Decision**: The roadmap adopts perplexity §8 "Recommended
Implementation Order" as its sequencing even where it conflicts with the
original P2–P10 order.

**Rationale**: The §8 ordering bakes in a dependency chain (memory →
tools → observability → extensions → A2A → scheduler → Obsidian →
resilience → lifecycle → routing → delegation context → security). The
original P-numbering was scope-derived, not dependency-derived.

**Counterargument considered**: Perplexity §6 argues A2A should be
Phase 1. Rejected at discovery (Gate 0 question 2) — lower integration
risk comes from having working agents to expose first.

### D3: P1.5 bootstrap-fixes as a distinct phase

**Decision**: The five minor fixes from perplexity §7 (CLI `-h`
conflict, `sqlalchemy.text()` wrapper, `deepagents` package reference,
`[project.scripts]` entry point, `name` variable shadowing) get their
own proposal `P1.5 bootstrap-fixes` rather than being absorbed into
whichever downstream phase next touches each file.

**Rationale**: They're hygiene debt that blocks development ergonomics
(`uv run assistant` doesn't work without the entry point fix; CLI
`--help` is shadowed). A single small PR clears all five at once; the
alternative forces each downstream phase to detour through unrelated
bugfixes.

### D4: Old P4/P6/P7/P9/P10 carried forward as P14–P18

**Decision**: The five items from the original P2–P10 that have no
perplexity §8 counterpart (google-extensions, work-persona-config,
cli-harness-integrations, mcp-server-exposure, railway-deployment) are
appended to the sequence as P14–P18 rather than dropped.

**Rationale**: Replace semantics (per the Gate-0 answer) means "rewrite
the doc," not "drop half the items." These phases still have value —
they just happen to have no perplexity-raised concerns. Placing them
last honors dependency order: they all rely on infrastructure built in
P1.5–P13.

### D5: Per-phase change-ids without date prefix

**Decision**: Each downstream phase's OpenSpec change-id is the
kebab-case slug from the roadmap (e.g., `memory-architecture`,
`a2a-server`) — no date prefix.

**Rationale**: The archived P1 used a date prefix
(`2026-04-12-bootstrap-vertical-slice`). That convention makes sense
for archival (when the archive date is meaningful) but is noise during
development — the roadmap is the identity source. Archiving can add a
date prefix at archive time if desired.

### D6: `tooling-roadmap` as a capability spec

**Decision**: Formalize roadmap invariants as a capability spec with
one ADDED requirement ("The project SHALL maintain a single canonical
roadmap…") and four sub-requirements covering authority, status
lifecycle, DAG, and provenance.

**Rationale**: Without a spec, the roadmap is just a markdown file
that drifts. With a spec, `openspec validate` (and future reviewers)
can check its invariants. Keeps the soft-discipline model (Approach A)
but makes the discipline explicit.

## Non-goals

- **No phase-proposal scaffolds created**: Each phase's proposal.md,
  specs, and tasks are generated at `/plan-feature <phase-id>` time.
- **No CI enforcement**: No script validates that in-progress phases
  match their roadmap status. The spec requirements are reviewer-level
  obligations, not CI-gated ones.
- **No automated `roadmap.md` update on archive**: When a phase is
  archived, the archiving engineer manually flips its status column.
  Automating this is a follow-up proposal if warranted.

## Open questions

- **`docs/perplexity-feedback.md` content format**: The review document
  is long; do we store it verbatim, summarize it, or store verbatim in a
  sub-file with a summary at the top? Answer: store verbatim; the
  citations in `roadmap.md` point to specific § references and
  grepability matters.
- **Should P1.5 be part of this proposal?** No — this proposal only
  declares P1.5 exists in the roadmap. The actual fixes are implemented
  via a separate `/plan-feature bootstrap-fixes` run.
