# continual-learning — Memory That Grows (P28)

## Why

The assistant remembers (P21 retrieval + capture are live) but nothing
*learns*: no feedback capture, no consolidation, no preference
distillation — role learning has been deferred since roadmap v2.
Ecosystem pillar 2 (docs/architecture-analysis/2026-07-16-ecosystem-
pillars.md) re-scopes it as a **source-agnostic feedback abstraction**:
a `FeedbackEvent` → `ImprovementProposal` pipeline whose sources are
both human (explicit CLI/REPL feedback) and machine (P27 eval results,
P13 guardrail spend pressure, P9 circuit-breaker stats, P19/P20 cost
metadata gaps). The binding constraint from the roadmap and P27:
**self-improvement is propose → eval → human-approved diff, NEVER
self-merge** — git in the persona submodule is the approval workflow.

## What Changes

- **Persona `learning:` section** (validated at load, actionable
  errors): `enabled`, `auto_apply_low_risk` (default false), a
  `reflection.consumer` models-binding override (default: the
  reserved `memory` key from P20), and `proposals_dir` (default
  `<persona_dir>/proposals`). **No section = fully dormant** — every
  entry point (feedback, collectors, reflection, propose, apply)
  refuses, mirroring the P26 clean-room posture.
- **`FeedbackEvent`** (`core/learning.py`): source-agnostic dataclass
  (closed source vocabulary `human | eval | guardrail | resilience |
  cost | critique`; subject, signal, context ref, structured data,
  identity, timestamps). Human capture: `assistant feedback -p
  <persona> [-r role] [--prefer cat:key=value] TEXT` and a REPL
  `/feedback` command — stored via `MemoryManager.store_interaction`
  with `metadata.source = "feedback"`. Machine collectors read what
  already exists (eval-gate output, the budget spend ledger, the
  breaker registry snapshot, unpriced registry entries) on demand via
  `assistant learning collect` or as scheduler jobs — no new daemons.
- **Reflection/consolidation**: `assistant reflect -p <persona>` (and
  a new `kind: reflect` scheduled-job kind in the P7 `schedules:`
  schema) summarizes new interactions — model-backed under the
  reflection consumer binding when an `openai-compatible` entry
  resolves, deterministic digest otherwise — into
  `learning/reflection/<ts>` facts with `source=reflection`
  provenance, plus a Graphiti episode write-back through
  `MemoryManager.store_episode` (closing the deferred P21 follow-up
  cheaply). A `learning/last_reflection` watermark prevents
  re-consolidation.
- **`ImprovementProposal`**: `{id, kind (prompt_layer | preference |
  routing_config), target, content, rationale, risk (RiskLevel name),
  provenance (feedback event ids), created_at, status}` written as
  JSON files under the persona `proposals/` dir by `assistant
  learning propose`. Risk tiers by kind: preference=LOW,
  prompt_layer=MEDIUM, routing_config=HIGH.
- **Gated apply**: `assistant learning apply` refuses unless (1) the
  `learning_apply` guardrail action allows (deny AND
  require_confirmation both refuse — P13 semantics until P30), (2)
  the P27 eval gate (`evaluation/run-gate.sh`) passes — SKIP counts
  as pass with a warning (G7-style), and (3) the proposal is LOW risk
  or the operator passes `--approved`. Preference proposals write
  through a new `MemoryManager.store_preference`; prompt_layer
  proposals append a marked suggestion block to the target file
  inside the persona dir (path-escape refused); routing_config is
  review-only. ONLY preference+LOW may auto-apply, and only under
  `auto_apply_low_risk: true` — through the same full gate chain.
- **MemoryManager addition**: `store_preference` upsert; the
  `trace_memory_op` vocabulary gains `preference_write` (P26/P27
  precedent). `CircuitBreakerRegistry` gains a read-only `breakers()`
  snapshot for the resilience collector.
- **Audit**: every op emits a `learning.<op>` span
  (feedback/reflect/propose/apply) through the `start_span` escape
  hatch, identity-stamped (P25/P26 precedent).

## Impact

- Affected specs: **learning** (ADDED capability), cli-interface
  (feedback/reflect/learning commands + `/feedback` REPL), scheduler
  (`kind: reflect` jobs), memory-policy (`store_preference`),
  observability (`preference_write` op).
- Affected code: new `src/assistant/core/learning.py`;
  `core/memory.py`, `core/persona.py`, `core/scheduler.py`,
  `core/resilience.py`, `telemetry/providers/base.py`,
  `telemetry/decorators.py`, `cli.py`,
  `personas/_template/persona.yaml`; new fixture persona
  `tests/fixtures/personas/learning_lab/`.
- Non-goals (recorded): AG-UI/email/messaging feedback channels (P24
  channel adapters land with P29 multimodal-io); the approval
  interrupt flow (P30 durable-sessions — until then
  `require_confirmation` denies and `--approved` is the human seam);
  machine application of routing_config proposals; Langfuse-trace
  feedback mining (P27 D5 follow-up).
