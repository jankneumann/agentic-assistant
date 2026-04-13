# Proposal: roadmap-v2-reconciliation

## Why

Two reconciliation items surfaced after `roadmap-v2-perplexity-integration`
was archived:

1. **Codex P2 review finding on PR 3 (self-violating spec)**: The
   `tooling-roadmap` capability spec's "Roadmap Document Authoritative"
   requirement reads "every non-archived change under
   `openspec/changes/<change-id>/` MUST appear in the roadmap table."
   This is too broad — it would require meta / tooling / spec-sync
   proposals (e.g., `roadmap-v2-perplexity-integration` itself, or the
   just-archived `sync-test-privacy-boundary-spec`) to register as
   roadmap phases, which they aren't. The requirement must be narrowed
   to *phase changes only*.

2. **Test-boundary phases missing from the v2 roadmap table**: The v2
   roadmap (merged via PR 3) omits the `test-privacy-boundary` and
   `sync-test-privacy-boundary-spec` changes even though both are
   archived on main. Under the "Archived changes remain listed"
   scenario, both need roadmap rows. The original v2 drafting pre-dated
   their archival.

Both items must land together: narrowing the spec requirement without
adding the test-boundary rows would leave unfinished reconciliation;
adding rows without narrowing the spec leaves the self-violation Codex
flagged.

## What Changes

### 1. MODIFY `Requirement: Roadmap Document Authoritative`

Rewrite the requirement body to include an **operational definition of
"phase change"** — three classification criteria (introduces a new
capability spec; implements a bootstrap-v4.1 P-item or perplexity §8
item; represents a committed milestone promoted by authoring judgment).
Every other OpenSpec change is a "non-phase change" and is non-normative
with respect to the row/status invariants; non-phase changes MAY be
listed in the roadmap table when chronological context helps reviewers.

This classification closes three review concerns at once: it addresses
the Codex PR 3 P2 finding (spec was self-violating because every
non-archived change required a row), it gives authors a reproducible
decision rule (closes iterate-on-plan finding F#2 and F#4), and it
reframes the former "Non-phase changes are not required to have a row"
scenario as positive obligations ("listed non-phase change still
follows row invariants" — closes iterate-on-plan finding F#3).

### 2. Add roadmap rows + adjust numbering

- **P1.5** `test-privacy-boundary` (archived 2026-04-13) — hygiene
  follow-up to P1 that separated public tests from private persona data.
  Source: "new — IR hygiene finding during P1 validation."
- **P1.6** `sync-test-privacy-boundary-spec` (archived 2026-04-13) —
  spec sync that closed five drift items found during P1.5 validation.
  Source: "spec-sync follow-up of P1.5."
- **P1.7** `bootstrap-fixes` (pending, previously P1.5) — bumped by
  two positions to preserve chronological ordering; content unchanged.
- **Dependency graph**: update the ASCII tree so P1.5 / P1.6 / P1.7
  chain correctly and the downstream edges point at P1.7.
- **Cross-cutting themes**: no changes.

## Approaches Considered

### Approach A: Single bundled reconciliation (Recommended)

Bundle all three items in one change. Spec MODIFY + Purpose fix + roadmap
row additions ship together as one reviewable unit.

**Pros**:
- One audit unit for "reconcile v2 roadmap with reality"
- Minimal ceremony overhead
- Review can confirm the spec narrowing is consistent with the roadmap
  edits (both reference the same phase-vs-non-phase distinction)

**Cons**:
- Mixes a spec edit with a docs edit — slightly larger blast radius
  than a spec-only change

**Effort**: S

### Approach B: Two sequential changes (spec first, roadmap second)

Ship the spec narrowing as a dedicated change, archive it, then add the
roadmap rows in a follow-up.

**Pros**:
- Cleanly isolates spec evolution from doc maintenance
- Each change is trivially reviewable

**Cons**:
- Interim state (after spec narrowing, before roadmap rows added)
  still violates "Archived changes remain listed with archived status"
  for test-privacy-boundary and sync-test-privacy-boundary-spec
- Twice the archive bookkeeping overhead for the same net delta

**Effort**: M (ceremony, not content)

### Approach C: Skip the spec narrowing; document test-boundary work as exceptions in roadmap

Leave the spec as-is but document in `roadmap.md` that meta /
spec-sync changes are "exempt" from the row requirement. Implement the
exemption as prose rather than spec text.

**Pros**:
- No spec evolution
- Fast

**Cons**:
- Keeps the self-violating spec as Codex flagged
- Documentation-in-prose is exactly what the `tooling-roadmap` capability
  was created to avoid; prose-exemptions rot
- Doesn't actually address the P2 review finding

**Effort**: XS but invalidates the capability's purpose

## Selected Approach

**Approach A** — one bundled reconciliation change. The spec narrowing
and roadmap edits are two sides of the same reconciliation; separating
them creates an interim inconsistent state.

## Out of scope

- **P1.7 `bootstrap-fixes` implementation**: this change only renumbers
  the pending phase; the actual fixes (CLI `-h`, `sqlalchemy.text()`,
  etc.) are a separate downstream proposal to be created later.
- **`Purpose` placeholder cleanup**: the `tooling-roadmap` spec still
  carries the `TBD - created by archiving change...` placeholder that
  `openspec archive` inserted. This is the repo-wide pattern (5+
  synced specs in `openspec/specs/` carry the same placeholder).
  Iterate-on-plan finding F#1 showed that OpenSpec's delta format has
  no mechanism to update `Purpose` from a change delta, so fixing one
  spec in isolation is spot cleaning when the systemic issue is a
  separate concern. Filed as a follow-up.
- **No code changes**: pure docs + spec reconciliation.
- **No new tests**: the existing `openspec validate --strict` check
  covers spec consistency; manual review covers roadmap row accuracy.
- **No changes to the Dependency Graph Representation, Phase Status
  Lifecycle, or Provenance Attribution requirements**: those three
  requirements are unaffected by the phase-vs-non-phase classification.
