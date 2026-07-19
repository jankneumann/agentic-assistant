# learning Specification

## Purpose
TBD - created by archiving change continual-learning. Update Purpose after archive.
## Requirements
### Requirement: Learning Configuration Section

The system SHALL parse an optional persona `learning:` section into a
`LearningConfig` (in `core/learning.py`) with `enabled` (boolean,
default `true` when the section is present), `auto_apply_low_risk`
(boolean, default `false`), an optional `reflection.consumer` models
bindings key (default the reserved `memory` consumer), and an
optional `proposals_dir` path (default `<persona_dir>/proposals` when
loaded through the registry). Validation MUST follow the
actionable-error posture: unknown keys and mis-typed values fail
persona load with an error naming the offender. A missing section (or
`enabled: false`) MUST parse to a falsy config, and every learning
entry point — feedback recording, machine collection, reflection,
proposal derivation, and application — MUST refuse for a persona with
a falsy config: continual learning is dormant by default (the P26
clean-room posture).

#### Scenario: Valid section parses

- **WHEN** a persona declares `learning: {auto_apply_low_risk: true}`
- **THEN** persona load MUST succeed with a truthy
  `PersonaConfig.learning` whose `enabled` is true and whose
  `proposals_dir` defaults under the persona directory

#### Scenario: Invalid section fails persona load actionably

- **WHEN** a persona declares `learning: {bogus_key: 1}`
- **THEN** persona load MUST raise a `ValueError` naming the
  `learning:` section and the unknown key

#### Scenario: No section means dormant

- **WHEN** a persona declares no `learning:` section
- **THEN** `PersonaConfig.learning` MUST be falsy
- **AND** `record_feedback`, `collect_machine_feedback`,
  `run_reflection`, `derive_proposals`, and `apply_proposal` MUST all
  refuse with a denial naming the missing section

### Requirement: Source-Agnostic Feedback Events

The system SHALL define a `FeedbackEvent` dataclass with a closed
source vocabulary (`human`, `eval`, `guardrail`, `resilience`,
`cost`, `critique` — unknown sources rejected at construction),
`subject` (role/persona/config path), `signal` (score/verdict/text),
optional `context` reference and structured `data` payload, a unique
`event_id`, a `created_at` timestamp, and the serialized acting
identity. `record_feedback` SHALL persist events through
`MemoryManager.store_interaction` with `metadata.source = "feedback"`
and the full event payload under `metadata.feedback`, and
`list_feedback` SHALL round-trip stored events (newest first),
skipping malformed payloads with a warning. Each recording MUST emit
a `learning.feedback` span through the telemetry `start_span` escape
hatch, identity-stamped.

#### Scenario: Unknown source is rejected

- **WHEN** `FeedbackEvent(source="telepathy", ...)` is constructed
- **THEN** a `ValueError` MUST be raised naming the invalid source

#### Scenario: Recorded feedback round-trips

- **WHEN** a human feedback event is recorded and `list_feedback` is
  called
- **THEN** the stored interaction's metadata MUST carry
  `source="feedback"`
- **AND** the listed event MUST preserve the original `event_id` and
  structured `data`

### Requirement: Machine Feedback Collectors

The system SHALL provide machine collectors that read ONLY existing
surfaces — no new stores and no new daemons: `collect_eval_feedback`
parses P27 eval-gate output text (each `eval-gate: FAIL — <what>`
line yields a failing event; `SKIP` and `PASS` lines yield advisory
events); `collect_guardrail_feedback` reads the persona's model-call
budget ceilings and spend ledger and emits one event per window at or
above 80% utilization; `collect_resilience_feedback` snapshots the
circuit-breaker registry (via a read-only
`CircuitBreakerRegistry.breakers()` accessor) and emits one event per
breaker that is not closed or carries consecutive failures;
`collect_cost_feedback` flags cloud registry entries without pricing
metadata while a model-call budget is configured and
`default_call_cost_usd` is zero. The `collect_machine_feedback`
aggregate MUST refuse for a persona whose learning config is falsy.
Collectors run on demand (CLI) or as scheduled jobs.

#### Scenario: Eval gate failures become eval events

- **WHEN** gate output containing `eval-gate: FAIL — triage.yaml` is
  collected
- **THEN** one event with `source="eval"`, `subject="triage.yaml"`,
  and `signal="fail"` MUST be returned

#### Scenario: Budget pressure becomes a guardrail event

- **WHEN** a persona has a $1.00 daily model-call ceiling and $0.90
  recorded spend today
- **THEN** `collect_guardrail_feedback` MUST return one event naming
  the daily budget window

#### Scenario: Unhealthy breaker becomes a resilience event

- **WHEN** a registered circuit breaker has recorded a failure
- **THEN** `collect_resilience_feedback` MUST return an event whose
  subject is the breaker key

#### Scenario: Unpriced cloud entry becomes a cost event

- **WHEN** a budgeted persona's registry has a cloud entry without
  pricing and a local entry with an endpoint
- **THEN** `collect_cost_feedback` MUST flag only the cloud entry

### Requirement: Reflection Consolidates Interactions Into Memory

The system SHALL provide a reflection pass (`run_reflection`) that
reads recent interactions, skips those already consolidated (tracked
via a `learning/last_reflection` watermark fact), summarizes the
remainder, and stores the result as a `learning/reflection/<ts>` fact
whose value carries the summary plus provenance
(`source="reflection"`, the consolidated interaction ids and count,
`used_model`, timestamp, and the reflecting identity). Summarization
SHALL resolve the persona `models:` registry under the configured
reflection consumer binding and dispatch through the budget-gated
`OpenAICompatibleClient` when an `openai-compatible` entry with an
endpoint resolves; otherwise it MUST degrade to a deterministic
bounded digest (never a network call). The summary MUST also be
written back as a Graphiti episode via `MemoryManager.store_episode`
(which degrades gracefully without a graph). A pass with nothing new
to consolidate MUST return `None` without writing. Each consolidation
MUST emit a `learning.reflect` span. The pass SHALL be runnable via
`assistant reflect` and via `kind: reflect` scheduled jobs.

#### Scenario: Reflection stores a provenance-stamped fact

- **WHEN** two new interactions exist and reflection runs
- **THEN** one `learning/reflection/*` fact MUST be stored whose
  provenance carries `source="reflection"` and both interaction ids
- **AND** one episode MUST be written with source `reflection`

#### Scenario: Repeated reflection does not re-consolidate

- **WHEN** reflection runs twice with no interactions arriving in
  between
- **THEN** the second pass MUST return `None` and store nothing

#### Scenario: No dispatchable model degrades to a digest

- **WHEN** no `openai-compatible` endpoint entry resolves under the
  reflection consumer binding
- **THEN** reflection MUST still consolidate using the deterministic
  digest and record `used_model: false`

### Requirement: Risk-Tiered Improvement Proposals As Files

The system SHALL define an `ImprovementProposal` (`proposal_id`,
`kind` ∈ {`prompt_layer`, `preference`, `routing_config`}, `target`,
`content`, `rationale`, `risk` as a `RiskLevel` name, `provenance`
feedback-event ids, `created_at`, `status`) serialized as JSON files
(`format: learning-proposal`, `version: 1`) under the persona's
proposals directory — reviewable diffs in the persona submodule, the
approval workflow. Risk SHALL tier deterministically by kind:
`preference` = LOW, `prompt_layer` = MEDIUM, `routing_config` = HIGH.
`derive_proposals` SHALL map feedback deterministically: human events
carrying a structured preference payload → `preference` proposals
(distillation); other human/critique events → `prompt_layer`
suggestions targeting the subject role's override prompt or
`prompt.md`; eval failures → `prompt_layer` suggestions; guardrail/
cost/resilience events → `routing_config` proposals. Events mapping
to the same `(kind, target)` MUST merge into one proposal with
combined provenance.

#### Scenario: Preference feedback distills to a LOW proposal

- **WHEN** a human event with `data.preference = {category, key,
  value}` is derived
- **THEN** one `preference` proposal with `risk="LOW"` MUST result

#### Scenario: Machine signals become HIGH routing_config proposals

- **WHEN** a cost event and a guardrail event are derived together
- **THEN** one `routing_config` proposal with `risk="HIGH"` MUST
  result, carrying both event ids in its provenance

#### Scenario: Proposal files round-trip

- **WHEN** a proposal is written and re-loaded from its file
- **THEN** every field MUST be preserved, and a file with the wrong
  format marker MUST be rejected with an error

### Requirement: Eval-Gated, Guardrail-Gated, Human-Approved Apply

The system SHALL apply proposals only through `apply_proposal`, which
enforces, in order: (1) an enabled learning config; (2) the proposal
is not already applied; (3) the `learning_apply` guardrail action
(`resource = "<kind>:<target>"`, identity attached) — a deny OR a
`require_confirmation` decision both refuse (P13 semantics; real
approvals arrive with the P30 durable-session interrupt flow); (4)
the P27 eval gate (`evaluation/run-gate.sh`) MUST pass — a SKIP
outcome (gen-eval unavailable or script missing) counts as pass with
a WARNING, a nonzero exit refuses; (5) LOW-risk proposals apply
as-is, MEDIUM/HIGH require the explicit operator `--approved` flag.
Application by kind: `preference` writes through
`MemoryManager.store_preference`; `prompt_layer` appends a marked
suggestion block to the target file resolved STRICTLY inside the
persona directory (escaping targets refused); `routing_config` is
review-only and always refuses machine application. Auto-application
(`maybe_auto_apply`) MUST consider only `preference` proposals with
LOW risk, only when the persona sets `auto_apply_low_risk: true`, and
MUST run the full gate chain per proposal. Every application MUST
emit a `learning.apply` span and stamp the proposal
`status="applied"` with `applied_at`. Self-improvement never
self-merges: nothing outside these rules mutates persona config or
prompts.

#### Scenario: LOW preference applies through the memory store

- **WHEN** a LOW `preference` proposal is applied with a passing gate
- **THEN** `store_preference` MUST be called with the proposal's
  category/key/value and the proposal MUST be stamped applied

#### Scenario: Gate failure refuses application

- **WHEN** the eval gate exits nonzero
- **THEN** `apply_proposal` MUST refuse and apply nothing

#### Scenario: Gate SKIP passes with a warning

- **WHEN** the gate reports SKIP (gen-eval unavailable)
- **THEN** the proposal MUST apply and a WARNING MUST be logged

#### Scenario: MEDIUM risk requires explicit approval

- **WHEN** a `prompt_layer` proposal is applied without `--approved`
- **THEN** it MUST refuse naming the approval flag
- **AND** with approval it MUST append the suggestion block to the
  target inside the persona directory

#### Scenario: Path escape is refused

- **WHEN** a `prompt_layer` proposal targets `../../etc/passwd`
- **THEN** application MUST refuse naming the escape

#### Scenario: routing_config is review-only

- **WHEN** a `routing_config` proposal is applied even with approval
- **THEN** it MUST refuse and direct the operator to apply the edit
  by hand

#### Scenario: Guardrail deny and require_confirmation both refuse

- **WHEN** a `learning_apply` policy declares `effect: deny` (or
  `effect: require_confirmation`)
- **THEN** `apply_proposal` MUST refuse citing the guardrail decision

#### Scenario: Auto-apply is opt-in and LOW-preference-only

- **WHEN** `maybe_auto_apply` runs for a persona without
  `auto_apply_low_risk: true`
- **THEN** nothing applies
- **AND** with the opt-in, only LOW `preference` proposals apply while
  other kinds stay `proposed`

### Requirement: Learning Operations Are Audited

The system SHALL emit one identity-stamped span per learning
operation through the telemetry `start_span` escape hatch —
`learning.feedback`, `learning.reflect`, `learning.propose`,
`learning.apply` — following the P25 `guardrail.decision` / P26
`cleanroom.<op>` precedent (no new first-class trace method).
Emission MUST be defensive: a failing telemetry provider logs a
WARNING and never changes the pipeline outcome. Guardrail decisions
additionally flow through the existing `emit_guardrail_audit`.

#### Scenario: Apply emits an identity-stamped span

- **WHEN** a proposal is applied
- **THEN** one `learning.apply` span MUST be emitted carrying the
  proposal id, kind, risk, and the acting identity fields

