# harness-routing — Dynamic Harness Selection (`--harness auto`) (P11)

## Why

Harness choice is manual today: every CLI entry point hard-defaults to
`deep_agents` and the operator must remember to pass
`-H ms_agent_framework` for M365-flavored work. The roadmap row P11
(perplexity §3.2/§8.10, reframed by arch-review G-C) calls for the
selection to be automatic: M365-tool tasks belong on the MS Agent
Framework harness, complex reasoning / general chat on Deep Agents,
and host-tier (subscription) harnesses are an explicit hand-off, never
an automatic one. Model routing already lives in P19
(`model-provider-routing`) and is NOT re-implemented here — P11 routes
**harnesses** and consumes the existing capability vocabulary.

This is deliberately NOT the P12 semantic router: no LLM calls, no
intent classification. Harness selection is deterministic and
config-driven so the decision is reproducible, testable, and free.

## What Changes

- **`core/harness_routing.py`** (new): the `harnesses.routing:` rule
  schema — ordered first-match rules matching on role-name glob and/or
  role `preferred_tools` globs (`ms_graph:*`, `outlook:*`, bare source
  names), each naming a target harness. Parsed at persona load with
  the same actionable-error posture as `models:` / `schedules:` onto
  `PersonaConfig.harness_routing`.
- **`select_harness(persona, role, *, requested=None)`** in
  `harnesses/factory.py`: deterministic resolution with precedence
  explicit `-H` → persona `harnesses.routing:` rules (first match) →
  built-in defaults (role prefers MS-source tools AND
  `ms_agent_framework` enabled → MSAF; else `deep_agents` when
  enabled; else the remaining enabled SDK harness). A host harness is
  NEVER auto-selected — host harnesses export config rather than
  execute, so auto-selecting one would silently no-op an interactive
  run; the host tier stays explicit-only (`-H claude_code` +
  `assistant export`).
- **Routing decision telemetry**: every `select_harness` call emits a
  `harness.routing` span through the observability `start_span`
  escape hatch (same pattern as the P25 `guardrail.decision` audit
  record) plus an INFO log line — decision, requested value, and
  reason are always attributable.
- **`--harness auto` CLI default**: `run`, `serve`, and `daemon` now
  default `-H` to the `auto` sentinel, resolved through
  `select_harness` after the role is loaded; explicit harness names
  bypass routing entirely.
- **Scheduler per-job harness override (P7 schema extension)**:
  `schedules:` jobs gain an optional `harness:` key. Effective harness
  per run: job `harness:` → daemon `-H` value → `auto` resolution
  against the job's role. Daemon startup now validates the resolved
  harness per job (previously one check against the last-loaded role).
- **Docs**: `personas/_template/persona.yaml` gains a commented
  `harnesses.routing:` example and the `schedules:` `harness:` key;
  CLAUDE.md gains a harness-routing note.

## Impact

- Affected specs: `harness-adapter` (ADDED requirements),
  `cli-interface` (MODIFIED harness selection + daemon requirements),
  `scheduler` (ADDED per-job override requirement),
  `persona-registry` (ADDED routing-section parsing requirement).
- Affected code: `src/assistant/core/harness_routing.py` (new),
  `src/assistant/core/persona.py`, `src/assistant/core/scheduler.py`,
  `src/assistant/harnesses/factory.py`, `src/assistant/cli.py`,
  `personas/_template/persona.yaml`.
- Backwards compatible: personas without `harnesses.routing:` and
  scripts passing explicit `-H` names behave exactly as before. The
  built-in default for every shipped role resolves to `deep_agents`
  on the personal persona (MSAF is disabled there), so the observable
  CLI behavior is unchanged until a persona opts in.
- Out of scope: P12 `delegation/router.py` intent classification
  (semantic routing), re-routing mid-session on `/role` switches
  (the session keeps its startup harness), and model routing (P19).
