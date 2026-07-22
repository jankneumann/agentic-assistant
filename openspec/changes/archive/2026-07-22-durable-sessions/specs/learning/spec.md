# learning Specification (delta)

## MODIFIED Requirements

### Requirement: Eval-Gated, Guardrail-Gated, Human-Approved Apply

The system SHALL apply proposals only through `apply_proposal`, which
enforces, in order: (1) an enabled learning config; (2) the proposal
is not already applied; (3) the `learning_apply` guardrail action
(`resource = "<kind>:<target>"`, identity attached) — a deny refuses;
a `require_confirmation` decision SUSPENDS into the P30 approval
interrupt flow when a durable approval store is supplied (pending
`ApprovalRequest` persisted, typed `PendingApprovalError` raised; a
retried apply consults resolved approvals and consumes an approve
decision exactly once, while a human deny surfaces as a denial) and
refuses with the P13 fallback when the persona has no durable
sessions; (4) the P27 eval gate (`evaluation/run-gate.sh`) MUST
pass — a SKIP outcome (gen-eval unavailable or script missing) counts
as pass with a WARNING, a nonzero exit refuses; (5) LOW-risk
proposals apply as-is, MEDIUM/HIGH require the explicit operator
`--approved` flag. Application by kind: `preference` writes through
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

#### Scenario: Guardrail deny refuses

- **WHEN** a `learning_apply` policy declares `effect: deny`
- **THEN** `apply_proposal` MUST refuse citing the guardrail decision

#### Scenario: require_confirmation without durable sessions refuses

- **WHEN** a `learning_apply` policy declares
  `effect: require_confirmation`
- **AND** `apply_proposal` runs with no approval store
- **THEN** it MUST refuse naming the missing durable approval store

#### Scenario: require_confirmation with durable sessions suspends then applies

- **WHEN** a `learning_apply` policy declares
  `effect: require_confirmation`
- **AND** `apply_proposal` runs with the persona's durable approval
  store
- **THEN** the first attempt MUST suspend with a persisted pending
  approval and apply nothing
- **AND** after an approve decision, the retried apply MUST proceed
  and consume the approval exactly once

#### Scenario: Auto-apply is opt-in and LOW-preference-only

- **WHEN** `maybe_auto_apply` runs for a persona without
  `auto_apply_low_risk: true`
- **THEN** nothing applies
- **AND** with the opt-in, only LOW `preference` proposals apply while
  other kinds stay `proposed`
