# continual-learning — Design

## D1. Dormant-by-default, including collectors

The mission brief left one question open: should read-only machine
collectors work for personas without a `learning:` section? Decision:
**no** — `collect_machine_feedback` (and every other entry point)
refuses via `require_learning`, exactly like the clean-room gateway's
"no config, no sharing". One posture, one test, no half-enabled
states. The individual collector functions stay importable/pure for
tests, but the aggregate and all CLI surfaces gate on config.

## D2. Feedback storage rides the interactions table

Human and stored machine feedback are `store_interaction` rows with
`metadata.source = "feedback"` and the full event payload under
`metadata.feedback`. No new table, no migration; feedback shows up in
recent-snippet retrieval as labeled `[feedback:human] …` lines
(useful signal for the agent itself) and round-trips losslessly via
`list_feedback`. The P24/P29 channel adapters (AG-UI thumbs, email)
can construct the same `FeedbackEvent` later without schema work.

## D3. Machine collectors read existing surfaces only

- **eval**: parses `evaluation/run-gate.sh` output text (`FAIL — x` /
  `SKIP — why` / `PASS` lines) — the gate's actual contract; gen-eval
  report internals stay external (ADR 0006).
- **guardrail**: budget utilization ≥ 80% from `budget_ledger_for`
  (file-backed when `persist: file`). Denial *counts* have no durable
  store today (audit is telemetry-sink-only, P25) — recorded
  limitation, revisit with the P30 durable audit log.
- **resilience**: new read-only `CircuitBreakerRegistry.breakers()`
  snapshot; non-closed breakers / consecutive failures become events.
- **cost**: cloud registry entries without pricing while a model-call
  budget is active and `default_call_cost_usd` is 0 — the spend blind
  spot; local (endpoint-carrying) entries are legitimately unpriced.

## D4. Reflection summarization and its fallback

Reflection resolves the persona registry under the
`learning.reflection.consumer` binding (default the reserved `memory`
key; unbound consumers fall back to `default` inside
`RegistryModelProvider`). Only `openai-compatible` + endpoint entries
are dispatchable harness-free (via the budget-gated
`OpenAICompatibleClient` — P19); other dialects degrade to a
deterministic bounded digest with `used_model: false` recorded in
provenance. This keeps reflection dependency-free and testable;
harness-based summarization for hosted dialects is a follow-up.
Graphiti episode write-back goes through the existing
`MemoryManager.store_episode` (no-graph degrades with a warning), so
the deferred P21 follow-up closes with zero new graph code. A
`learning/last_reflection` watermark fact (ISO timestamp compare)
prevents re-consolidation; `ModelCallDeniedError` propagates —
budget-denied reflection must not silently fall back to a write.

## D5. Proposal files ARE the approval workflow

Proposals serialize to `<persona_dir>/proposals/<id>.json`
(`format: learning-proposal, version: 1`). The persona dir is the
private submodule, so a proposal (and any applied prompt_layer block)
lands as a reviewable git diff there — propose → eval → human-approved
diff, never self-merge. Risk is a pure function of kind
(LOW/MEDIUM/HIGH); escalation heuristics can layer on later without
schema change. Apply semantics per kind:

- `preference` → `MemoryManager.store_preference` (new upsert;
  `preference_write` trace op). The only auto-applicable kind.
- `prompt_layer` → append a `<!-- applied learning proposal … -->`
  block to the target file, resolved under the persona dir with a
  path-escape check. MEDIUM ⇒ requires `--approved`.
- `routing_config` → **review-only**: machine-rewriting persona.yaml
  is riskier than the human applying the suggested edit; apply always
  refuses with instructions. (Recorded deviation from a literal
  reading of "apply <proposal>": HIGH-tier config edits stay human.)

## D6. Gate + approval semantics (interim until P30)

`apply_proposal` gate order: enabled → not-already-applied →
`learning_apply` guardrail action (require_confirmation DENIES — P13
semantics) → P27 eval gate (exit 0 = pass; `eval-gate: SKIP` in the
output = pass with WARNING; missing script = SKIP; nonzero = refuse)
→ risk/approval. The `--approved` flag is the explicit human seam
until P30 durable-sessions delivers the channel-agnostic approval
interrupt; when that lands, `require_confirmation` policies become
usable and `--approved` can be superseded by real interrupts.

## D7. Scheduler integration: job `kind`

`schedules:` jobs gain an optional `kind: agent | reflect` (default
`agent`, fully backward compatible). `reflect` jobs skip the harness
entirely — `HarnessJobRunner.run` dispatches to
`learning.run_reflection_for_persona` (lazy import, keeping the
schema half of scheduler.py import-light for persona.py). `role` /
`prompt` become optional for reflect jobs; the daemon CLI validates
reflect-job prerequisites (enabled learning + database_url) up front
instead of role/harness. Alternative considered: OS cron running
`assistant reflect` — rejected because P7 already owns per-job error
isolation, consumer bindings, and daemon lifecycle.

## D8. Observability

No new trace op beyond `preference_write` (which follows the
`interaction_list`/`fact_list` vocabulary-extension precedent).
Pipeline-level audit uses `learning.feedback` / `learning.reflect` /
`learning.propose` / `learning.apply` spans through the `start_span`
escape hatch, identity-stamped — the P25 `guardrail.decision` and P26
`cleanroom.<op>` precedent. Guardrail decisions additionally flow
through the existing `emit_guardrail_audit`.
