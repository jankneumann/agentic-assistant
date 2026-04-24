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

---

## Phase: Plan Iteration 1 (2026-04-24)

Agent: claude_code Opus 4.7 with 1M context.
Session: autopilot PLAN_ITERATE phase.

### Findings summary

Four parallel Explore audits returned 32 distinct findings across six quality
dimensions. After dedup by root cause, roughly 25 unique issues. Breakdown:

- Critical: 1 (secrets in docker compose could be mistaken for production keys)
- High: 7 (contextvars assumption not in spec, wrong http tool function name,
  extension wrapping site was a Protocol not a base class, tracemalloc
  flakiness, missing secret regex patterns for AWS and GitHub and Slack and
  Google and DB URLs, Authorization Basic and Cookie patterns missing from
  sanitization, tests/telemetry directory scope overlap between two packages)
- Medium: 12 (op enum enumeration in tasks, 256 character threshold only in
  scenario not Requirement body, singleton cache cleanup needed a fixture,
  SpyProvider pattern undocumented, CI smoke test resource cost, MS Agent
  stub behavior undefined in spec, optional extra rationale missing, hooks
  decorator bottleneck note, empty string credential disambiguation,
  persona name validation, scope leak check, crash time delivery loss
  missing from spec)
- Low: ~5 (Python version note, Langfuse v3 confirmation, task dependency
  over constraint, capability resolver spec delta was missing entirely,
  no inbound interface constraint not stated)

### What Round 1 addressed

- Fixed the wrong function name in task 3 point 9: was _build_structured_tool,
  changed to _build_tool at line 186 in the http_tools builder. Verified by
  grep against the actual source.
- Fixed the extension wrapping site: Extension in extensions/base.py is a
  Protocol not a base class, so behavior cannot be inherited. Moved the
  wrapping to the aggregation sites in core/capabilities/tools.py and
  harnesses/sdk/deep_agents.py, with a shared helper wrap_extension_tools
  in telemetry/tool_wrap.py. Added a new capability-resolver spec delta
  covering this.
- Fixed the tests/telemetry scope overlap in work-packages.yaml by listing
  specific test files in wp-contracts and explicitly denying the hook test
  files. Added the telemetry/decorators and telemetry/tool_wrap files to
  wp-hooks write_allow with matching denies in wp-contracts.
- Added a new Requirement "Persona and Role Context Propagation" to the
  observability spec binding the contextvars choice with two scenarios for
  cross await persistence and delegation sub role propagation.
- Added a new Requirement "No Inbound Interfaces" with a scenario asserting
  the module docstring declares outbound only.
- Added a new Requirement "Documented Crash Time Delivery Semantics" with a
  scenario checking that the docs name the shutdown mode tradeoff.
- Added new scenarios under existing Requirements: rejects mis typed op
  value; common vendor token formats redacted; database URL with embedded
  credentials redacted; empty string credentials treated as missing;
  MSAgentFrameworkHarness stub traced with raised exception path.
- Expanded the sanitize regex list from 7 patterns to 15, adding AWS,
  GitHub PAT, Slack, Google OAuth, DB URL, Authorization Basic and Digest,
  and Cookie patterns. Updated the known safe fields list to include op
  and tool_kind (which are enums, not free text).
- Softened the zero allocation scenario from strict tracemalloc assertion
  to a 3 run median with 4 KB tolerance, marked as advisory.
- Renamed the sanitizer ordering scenario to correctly describe what it
  tests (Langfuse specific before generic secret key, not public key).
- Moved the 256 character hashing threshold into the delegation Requirement
  body with explicit hashlib sha256 formula.

### What Round 2 addressed

- Expanded task 1 point 7 to enumerate all regex patterns it covers.
- Expanded task 1 point 9 to explicitly include cross await propagation
  and delegation scope tests.
- Expanded task 2 point 3 to include MS Agent stub decorator application.
- Expanded task 4 point 3 to enumerate the required sections in
  docs/observability.md.
- Expanded task 5 point 2 to include the outbound only docstring check
  and the absence of inbound framework imports.
- Marked task 5 point 5 (live Langfuse smoke test) as optional with a
  repository variable guard.

### Design decisions added

- D11: Test fixtures for singleton reset (autouse) and SpyProvider (opt in).
- D12: pyproject optional extra rationale over dependency group.
- D13: Empty string credentials treated as missing, with warning log
  distinguishing from fully unset case.
- Updated D9 to require DUMMY dash prefix on all committed Langfuse init
  dev values plus a startup check script preventing accidental prod launch.

### Not addressed (deferred to PLAN_REVIEW or later)

- Persona name regex validation at config time. Flagged in audit as
  medium. Deferred because persona names are currently short and known
  safe, and adding validation could break existing fixture personas.
  Tracked in open questions.
- Phase 4 infrastructure scope confirmation. Docker compose, docs, and
  README updates are mixed in with the capability itself. User should
  confirm at Gate 2 whether this composition is desired.

### Validation

- openspec validate observability strict passes after both rounds.
- Total spec growth: 10 Requirements to 13, 18 scenarios to 31 in the
  main observability spec. One new spec delta added: capability-resolver.
- Total task growth: about 40 tasks to 43 tasks.
- Work packages DAG unchanged. Scope overlap eliminated. Max parallel
  width calculation stands: wp-contracts serial, wp-hooks plus wp-devops
  concurrent after contracts, wp-integration after both.
