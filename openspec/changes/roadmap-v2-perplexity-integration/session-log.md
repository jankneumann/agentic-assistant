# Session log — roadmap-v2-perplexity-integration

---

## Phase: Plan (2026-04-13)

**Agent**: claude-code (Opus 4.6) | **Session**: N/A

### Decisions

1. **Replace P2–P10 with unified §8-ordered sequence** — The original
   roadmap predated perplexity review and was stale (P1 still listed as
   "in progress" despite being archived 2026-04-12). Replacing wholesale
   is cleaner than layering new phases on top of outdated content.
2. **Perplexity §8 ordering is authoritative** — Adopted §8's
   memory → HTTP → observability → MS Graph → A2A → scheduler → Obsidian
   → resilience → lifecycle → routing → delegation-context → security
   order even where it conflicts with original P-numbering.
3. **P1.5 bootstrap-fixes as distinct phase** — The five §7 hygiene
   fixes (CLI `-h`, `sqlalchemy.text()`, `deepagents` package,
   `[project.scripts]`, variable shadowing) run as a single prerequisite
   PR rather than being absorbed into each downstream phase.
4. **Old P4/P6/P7/P9/P10 carried forward as P14–P18** — No-perplexity-
   coverage items (google-extensions, work-persona-config,
   cli-harness-integrations, mcp-server-exposure, railway-deployment)
   preserved as tail of the sequence.
5. **Approach A: single roadmap document + capability spec** — Selected
   at Gate 1 over Approach B (pre-scaffolded 18 stubs) and Approach C
   (CI-enforced DAG).
6. **Change-ids without date prefix** — Each downstream phase's
   OpenSpec change-id is the kebab-case slug from the roadmap
   (`memory-architecture`, `a2a-server`, etc.) with no date prefix.

### Alternatives Considered

- **Fork into roadmap-v2.md, keep v1**: rejected — two competing
  roadmaps invite reader confusion about which is authoritative.
- **Promote A2A to Phase 1** (perplexity §6): rejected at discovery
  gate — lower integration risk comes from having working agents to
  expose first.
- **Group items into 6–8 medium phases**: rejected in favor of fine
  granularity (one proposal per §8 item) to maximize `/autopilot`
  parallelizability and review cohesion.
- **CI-enforced DAG (Approach C)**: rejected — doc-driven enforcement
  rots faster than the docs it guards; not justified at solo-developer
  scale.

### Trade-offs

- Accepted **18 phases** over **6–8 grouped phases** because fine
  granularity unlocks `/autopilot` per-phase + keeps review burden per
  PR small.
- Accepted **no CI enforcement** over **machine-enforced DAG** because
  the maintenance cost of CI gates on documentation state outweighs
  the benefit for a solo project.
- Accepted **carry-forward of old P4/P6/P7/P9/P10** over **dropping
  them** because "replace roadmap" means "rewrite the doc," not
  "drop half the scope."

### Open Questions

- [ ] Should `docs/perplexity-feedback.md` store the review verbatim or
      as a summary with § anchors? (Tentatively: verbatim, per design
      D6's "Open questions" resolution. Confirmed during implementation.)
- [ ] Whether to automate roadmap-status flips on archive. (Deferred
      to a follow-up proposal if warranted.)

### Context

Planning goal: integrate perplexity v4.1 review feedback into the
project roadmap so downstream phases can be implemented via
`/autopilot`. Outcome: proposal + design + tasks + specs + contracts
(stub) + work-packages for `roadmap-v2-perplexity-integration`, a
planning-only change that rewrites `openspec/roadmap.md` to sequence
18 phases (P1 archived, P1.5 bootstrap-fixes, P2–P13 perplexity §8
items, P14–P18 carried-forward legacy items). Validated with
`openspec validate roadmap-v2-perplexity-integration --strict` (exit 0,
PostHog network errors are unrelated telemetry).
