# harness-routing — Design

## D1. Deterministic, config-driven — no LLM calls

`select_harness` is a pure precedence walk over data that already
exists at persona/role load time. Rationale: harness selection sits on
the startup path of every CLI invocation and every scheduled job run;
an LLM-based classifier there would add latency, cost, and
nondeterminism to a decision with exactly three viable outcomes.
Semantic *task* routing is P12's `delegation/router.py` and is
explicitly out of scope here.

Precedence (first hit wins):

1. **Explicit request** (`-H <name>` other than `auto`): returned
   verbatim, reason `explicit`. Enablement/registration validation
   stays where it always was — `create_harness`.
2. **Persona `harnesses.routing:` rules**, ordered, first match. A
   rule matches when its `role:` glob (fnmatch, case-sensitive)
   matches the role name AND (when declared) any of its `tools:`
   globs matches any role `preferred_tools` entry. `tools:` patterns
   containing `:` match the full `source:operation` string; bare
   patterns match the source prefix (`ms_graph` ≡ `ms_graph:*`).
   A matching rule naming a harness that is not enabled for the
   persona is **skipped with a WARNING** (resilient-but-loud: a
   disabled target is a config drift, not a reason to abort an
   interactive run); a matching rule naming an unknown or host
   harness raises (that is a hard config error — see D2).
3. **Built-in defaults**: if any role `preferred_tools` entry's
   source prefix is one of `ms_graph` / `outlook` / `teams` /
   `sharepoint` AND `ms_agent_framework` is enabled → MSAF
   (reason `builtin:ms-tools`). Else `deep_agents` when enabled
   (reason `builtin:default`). Else the remaining enabled SDK harness
   (`builtin:only-enabled-sdk`). Else `ValueError` naming the enabled
   set and pointing at explicit `-H` for the host tier.

## D2. Host tier is explicit-only

A host harness (`claude_code`) is never returned by rules or
defaults, and a routing rule targeting one fails persona-authoring
loudly at selection time. Why: host harnesses do not execute — they
`export_context` for a subscription-seat host (Claude Code). If
`auto` could resolve to one, `assistant run -p X` would silently
produce the "use assistant export" error (or worse, a no-op) based on
invisible config. Recognizing that a task belongs on the host tier is
therefore surfaced as *documentation + explicit flag*
(`-H claude_code` + `assistant export`), not as an automatic branch.

## D3. Rule schema parses in core, registry validation in factory

`core/harness_routing.py` owns the schema (shape validation at
persona load, actionable errors naming the rule index) because
`core/persona.py` cannot import the factory — `harnesses/factory.py`
imports `core/persona.py` at module level (same import-discipline
constraint the scheduler schema documents). Consequence: *shape*
errors (unknown keys, no matcher, missing harness) fail persona load;
*registry* errors (unknown/host/disabled target) are enforced by
`select_harness` in the factory, where `HARNESS_REGISTRY` lives.
The parsed rules are stored on `PersonaConfig.harness_routing` and
the `routing` key is popped out of `PersonaConfig.harnesses` so that
mapping remains strictly harness-name → config.

## D4. Telemetry via the `start_span` escape hatch

The routing decision emits a `harness.routing` span (attributes:
persona, role, requested, selected, reason) through
`get_observability_provider().start_span(...)` — exactly the
`guardrail.decision` audit pattern from P25 (no new trace op; the
closed trace-op vocabulary is untouched; emission is defensive and
never breaks selection) — plus one INFO log line for grep-ability.
The `_active_model` pattern informs the metadata shape (decision
labels ride on span metadata, not new signatures).

## D5. `auto` is a CLI sentinel, not a factory value

`create_harness` never sees `auto`; callers resolve first. `run`
gains `auto` in its `click.Choice` and all three subcommands default
to it. The REPL resolves once at startup: an in-session `/role`
switch keeps the session's harness (rebuilding conversation state on
an invisible harness flip would surprise more than it helps; noted as
follow-up if usage says otherwise).

## D6. Scheduler override rides the existing seam

`ScheduledJob` gains `harness: str = ""` (empty = inherit the daemon
`-H` value). `HarnessJobRunner.run` computes
`job.harness or runner default`, resolves `auto` via `select_harness`
against the job's role, and passes a concrete name to the injected
`create_harness_fn`. Daemon startup validation moves inside the
per-job loop (it previously validated one harness against whatever
role the loop left behind — a latent bug this change fixes), so a bad
per-job override fails at startup, not at 7am.

## Deviations from the pre-made design brief

- Registry-level validation of rule targets happens at selection time
  rather than persona-load time (D3 import-discipline constraint);
  shape validation still fails persona load.
- A matching rule whose target harness is *disabled* is skipped with
  a WARNING instead of raising, so the built-in fallback chain still
  produces a runnable harness (the disabled-harness fallback exit
  criterion); unknown/host targets still raise.
