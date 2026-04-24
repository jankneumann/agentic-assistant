# Session Log — observability

Decision records per phase. Append-only.

---

## Phase: Plan (2026-04-24)

Agent: claude_code Opus 4.7 with 1M context.
Session: autopilot execution invoked via slash autopilot observability.

### Decisions

1. Approach A selected at Gate 1. Native Langfuse SDK with typed Protocol.
   User Q1 chose extend with first class methods over literal newsletter copy
   or generic span only. Protocol surface: four named trace methods
   plus a generic span escape hatch plus lifecycle hooks.

2. Shared methods for symmetric pairs. One trace tool call method covers
   both extension tools and HTTP tools via a tool kind parameter. One
   trace memory op method covers both the memory module and the graphiti
   module via an op parameter. Keeps the Protocol at five named methods
   instead of seven or more.

3. Shutdown only flush via atexit. Opt in per operation flush via an
   environment variable for debugging. Selected at Q2. User accepted that
   process crashes may lose buffered spans as the cost of zero latency
   tax on normal operation.

4. Scope upgrade from roadmap M to L. Accepted at Gate 1. Q3 answer
   expanded hook coverage from just harness and delegation to all six
   hook sites. Effort bumped from the roadmap declared M to L. Captured
   in the proposal header.

5. Four package coordinated DAG. Contracts depends on nothing.
   Hooks and devops both depend on contracts and run in parallel.
   Integration depends on both. Hooks package is intentionally large but
   kept as one unit because its changes share the same decorator import
   chain. Splitting would force serialized merges without parallel gain.

6. Langfuse init env vars from day one in the docker compose file.
   Memory flagged the newsletter gap. Fixing here rather than inheriting
   the deficiency. Dev default values committed alongside compose,
   documented as dev only.

7. Singleton provider via module level cache. Decision D1 in design doc.
   Returning a fresh provider per call would defeat SDK batching. Context
   propagation uses contextvars so sub agents emit with their own role
   after a delegation hop.

8. Claude Code Stop hook is documentation only. Decision D10. The
   existing script in agentic coding tools already handles transcript
   parsing and state file hashing. Reimplementing would duplicate code
   and drift.

### Alternatives Considered

- Approach B literal newsletter copy. Rejected. Would force a fork to
  change flush mode per Q2, and loses type safety on attrs across the
  six hook sites enabled by Q3.
- Approach C minimal Protocol with only generic span. Rejected. Loses
  specialized LLM call semantics and requires manual cost aggregation.
- Stayed at roadmap M scope, only harness and delegation. Offered at
  Gate 1 as Option 2. User chose the full scope expansion instead.
- Per request flush. Rejected at Q2 due to latency spike documented in
  the cross repo memory file.
- Six package decomposition. Rejected. Would force a serialized DAG
  because the three hook packages share the same decorator module.

### Trade offs

- Five method Protocol surface over three method copy. Accepted extra
  boilerplate in exchange for compile time attribute enforcement at six
  or more hook sites.
- Effort L over M. Accepted because deferring observability for each
  downstream phase would cost more total work.
- Crash time span loss. Accepted as the shutdown flush cost. The opt in
  per operation mode is available for workloads that cannot tolerate it.
- Four providers supported in Protocol even though only two ship.
  Accepts the slightly larger surface for future adapter slots.

### Open Questions

- Integration order within the hooks package. Should harness tracing
  land before or after delegation tracing. Tasks are currently listed
  harness first but no spec dependency forces one ordering.
- MS Agent Framework harness stub is registered but raises not
  implemented. Do we apply the traced harness decorator to it now or
  defer. Current plan: apply for consistency.
- Telemetry extra in pyproject. Dependency group or optional extra.
  Current plan: optional extra so a default sync does not install
  Langfuse.

### Context

Planning goal: produce a complete Gate 2 ready OpenSpec proposal for
phase 7 with enough detail that the implementation phase can dispatch
four parallel work packages. Planning ran under the coordinated tier
with the HTTP coordinator reachable and all three vendor CLIs
installed, enabling multi vendor review convergence during the
subsequent review phase.

Pre planning preparation pulled three memory entries into context
before dispatching exploration. The Langfuse lessons directly shaped
the Approach A sketch presented at Gate 1.

Two memory vs reality discrepancies surfaced during exploration and
are flagged in the design doc.
- Memory stated no per request flush as a universal rule. Reality: it
  was describing agent coordinator behavior, not newsletter aggregator,
  which does flush per call.
- Memory flagged the Langfuse init env vars as a newsletter gap.
  Confirmed. Newsletter compose omits them. We include them on day one.

No OpenSpec changes in progress that could conflict. Add teacher role
is the only open change and is orthogonal. Clean merge runway to main.

### Validation

- openspec validate observability strict passes.
- Work packages schema validator from agentic coding tools is a cross
  repo mismatch. Skipped. YAML format matches the archived http tools
  layer precedent from the same day.
- Parallel zones validation skipped. The architecture analysis
  directory is not populated in this repo. The make architecture
  target does not exist. Non blocking for planning.
