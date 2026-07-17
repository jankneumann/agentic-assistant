# persona-registry Specification (delta)

## ADDED Requirements

### Requirement: Schedules Section Parsing

Persona load SHALL parse and validate an optional `schedules:` section
into `PersonaConfig.schedules`: a mapping of job name to a job spec
with a `trigger:` mapping declaring exactly one of `cron:` (validated
5-field croniter expression), `interval:` (positive seconds), or
`calendar:` (non-empty source name, optional positive `lead_minutes`),
plus required non-empty `role:` and `prompt:`, optional `consumer:`
(non-empty models bindings key, default `scheduler`) and `enabled:`
(boolean, default true). Unknown job or trigger keys, ambiguous or
invalid triggers, and malformed fields SHALL fail persona load with an
actionable error naming the persona, config path, and offending job —
the same posture as the `models:` and `guardrails:` sections. A
persona without a `schedules:` section SHALL load with a falsy,
empty schedule config.

#### Scenario: Valid schedules parse with defaults

- **WHEN** a persona declares a job with
  `trigger: {cron: "0 7 * * *"}`, a role, and a prompt
- **THEN** `PersonaConfig.schedules` MUST contain the job with
  `consumer == "scheduler"` and `enabled == True`

#### Scenario: Invalid schedule fails persona load with context

- **WHEN** a persona declares a job with `trigger: {interval: -1}`
- **THEN** persona load MUST raise an error containing
  `"invalid schedules: section"` and the persona name

#### Scenario: Ambiguous trigger is rejected

- **WHEN** a job's trigger declares both `cron:` and `interval:`
- **THEN** persona load MUST fail with an error naming the job and
  requiring exactly one trigger kind

#### Scenario: Missing schedules section is falsy

- **WHEN** a persona declares no `schedules:` section
- **THEN** `PersonaConfig.schedules` MUST be falsy
