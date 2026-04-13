# Roadmap v2 — Perplexity Feedback Integration

## Why

`openspec/roadmap.md` was derived from `docs/agentic-assistant-bootstrap-v4.1.md`
before the v4.1 spec was reviewed by perplexity. That review
(`docs/perplexity-feedback.md` — the v4.1 review document pasted into the
planning conversation) identified eight structural gaps (§1–§6) and twelve
prioritized implementation items (§8) that materially reshape the plan:

- **Missing from original roadmap entirely**: observability (§1.1, §8.3),
  A2A server (§6, §8.5), scheduler (§2.1, §8.6), Obsidian vault
  integration (§2.2, §8.7), error resilience (§1.3, §8.8), extension
  lifecycle hooks (§3.1, §8.9), dynamic harness routing (§3.2, §8.10),
  security hardening (§4, §8.12).
- **Under-specified in original roadmap**: memory architecture
  (`memory.md` vs Postgres vs Graphiti hierarchy — §1.2, §8.1),
  sub-agent delegation context (§3.3, §8.11).
- **Bootstrap hygiene debt**: five minor fixes (§7) — CLI `-h` conflict,
  missing `sqlalchemy.text()` wrapper, `deepagents` package reference,
  missing `[project.scripts]` entry point, `name` variable shadowing in
  `PersonaRegistry.load`.

Additionally, the current `openspec/roadmap.md` is **stale**: it lists
P1 as "in progress" but P1 `bootstrap-vertical-slice` was archived on
2026-04-12. Working from a stale roadmap invites duplicated effort and
confusion about which capabilities exist.

A single authoritative roadmap that integrates perplexity §8 ordering,
folds the un-overlapping pieces of P2–P10 into the new sequence, and
stages bootstrap hygiene fixes as a prerequisite proposal is the cleanest
way to unblock parallel phase implementation via `/autopilot`.

## What Changes

This proposal is **planning-only** — it produces documentation, not code
changes. It will:

1. **Replace `openspec/roadmap.md`** with a v2 that sequences 18 phases
   (P1.5 bootstrap-fixes + P2–P18) per perplexity §8 order, with each old
   P2–P10 item folded into its perplexity-aligned position.
2. **Add a `tooling-roadmap` capability spec** that formalizes what the
   roadmap document is for and the invariants it must satisfy (sequencing,
   status lifecycle, dependency graph representation).
3. **Add `docs/perplexity-feedback.md`** capturing the review document
   verbatim so the roadmap rationale has a stable reference.
4. **Define the phase-dependency DAG** in the new roadmap so that
   `/plan-feature` and `/autopilot` invocations for each phase can look up
   prerequisites deterministically.

Out of scope (handled by downstream phase proposals):
- The actual implementation of any phase (P1.5 and each of P2–P18 will be
  their own `/plan-feature` → `/autopilot` cycles).
- Spec deltas for `persona-registry`, `extension-registry`, etc. —
  those belong to the phase that implements the change.

## Approaches Considered

### Approach A: Single roadmap document + capability spec (Recommended)

**Description**: Rewrite `openspec/roadmap.md` as the single source of
truth for phase sequencing. Add a `tooling-roadmap` capability spec with
one requirement ("The project SHALL maintain a roadmap document…") and
scenarios covering sequencing, status lifecycle, and dependency-graph
invariants. No stub proposal directories created — each downstream phase
starts fresh when its turn comes.

**Pros**:
- Minimal artifact surface: roadmap.md + one spec file + feedback doc
- No premature commitment to phase-internal task shape
- Fast to land and review
- Each downstream phase gets a full `/plan-feature` pass, preserving
  discovery-question quality and letting implementation feedback inform
  later designs

**Cons**:
- No machine-enforcement of the dependency DAG — relies on humans
  consulting the roadmap before starting each phase
- Phase IDs (P1.5, P2, …, P18) only exist in the roadmap document; the
  actual OpenSpec change-ids will be chosen when each phase is planned

**Effort**: S

### Approach B: Roadmap + pre-scaffolded phase stubs

**Description**: Everything in Approach A, plus create skeleton
directories `openspec/changes/<phase-id>/` for each of the 18 phases
with `proposal.md` containing only the title, a one-paragraph why, and
"See roadmap.md P<n>". `/plan-feature` later fills in approaches, specs,
tasks. Pre-wires each phase so `/autopilot phase P5` can find a
pre-existing directory.

**Pros**:
- Autopilot invocations have a stable directory to target from day one
- Phase IDs become authoritative (directory-backed), not just doc-mentioned
- Easier to grep `openspec/changes/` for upcoming work

**Cons**:
- 18 skeleton directories clutter the active-changes listing; `openspec
  list` will show them all as "pending" even though most are months away
- Titles/scopes written now may drift from reality by the time that phase
  runs — pre-written stubs get stale
- More to review in this PR (proposal.md × 18 vs 1)

**Effort**: M

### Approach C: Roadmap + dependency-graph enforcement script

**Description**: Approach A, plus a `scripts/validate-roadmap.py` that
parses roadmap.md, verifies each phase's prerequisites are archived
before that phase can begin, and fails CI if someone tries to archive a
phase out of order. Optionally adds a pre-commit hook that blocks the
creation of a `proposal.md` for a phase whose deps aren't met.

**Pros**:
- Machine-enforced sequencing — no accidental out-of-order starts
- Makes the DAG a first-class artifact, not a markdown afterthought
- Catches drift if someone edits roadmap.md inconsistently with
  `openspec/changes/` state

**Cons**:
- More engineering effort (script + tests + CI wire-up)
- Adds friction when the DAG legitimately needs to change (e.g.,
  discovering during P4 that P8 can actually start earlier)
- Overkill for a solo-developer project — the soft discipline of
  consulting roadmap.md is probably sufficient
- CI gating on documentation state is a maintenance burden

**Effort**: M–L

### Recommended: Approach A

Approach A matches the project's current scale (one developer, phases run
sequentially via `/autopilot` rather than in parallel) and preserves the
value of full `/plan-feature` discovery for each phase. The dependency
DAG still exists — it's written into roadmap.md — it just isn't
machine-enforced. If the project scales to multiple developers and
phases start running concurrently, Approach C's enforcement script
becomes a follow-up proposal.

Approach B's stub-proliferation cost is not recovered by its
discoverability benefit when there's effectively one active phase at a
time.

### Selected Approach

**Approach A — roadmap doc + capability spec.** Confirmed by user at
Gate 1 with no modifications. Proceeding to generate:

- `openspec/roadmap.md` (rewritten in full)
- `openspec/changes/roadmap-v2-perplexity-integration/specs/tooling-roadmap/spec.md` (ADDED)
- `docs/perplexity-feedback.md` (canonical copy of the review)
- `openspec/changes/roadmap-v2-perplexity-integration/tasks.md`
- `openspec/changes/roadmap-v2-perplexity-integration/design.md` (phase-by-phase decomposition with §-citations)

Approaches B and C are recorded here as rejected:

- **B rejected**: 18 skeleton proposal directories would clutter `openspec
  list` output for months while most stubs sit unchanged; pre-written
  stubs drift from reality before their phase runs.
- **C rejected**: machine-enforcement of a documentation-driven DAG adds
  CI maintenance burden disproportionate to the project's current scale.
  If phases start running concurrently later, enforcement becomes a
  follow-up proposal.
