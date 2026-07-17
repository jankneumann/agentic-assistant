# scheduler Specification (delta)

## ADDED Requirements

### Requirement: Per-Job Harness Override

A scheduled job SHALL accept an optional `harness:` key naming the
harness for that job's runs (a registered SDK harness name or the
`auto` sentinel). The effective harness per run SHALL be resolved as:
job `harness:` when declared, else the runner's configured harness
(the daemon `-H` value), and an effective value of `auto` SHALL be
resolved through `select_harness` against the job's role before the
harness factory is called — the factory never receives `auto`. A
declared `harness:` value that is not a non-empty string SHALL fail
persona load with an actionable error naming the job.

#### Scenario: Job harness override wins over the runner default

- **WHEN** the runner is configured with `deep_agents`
- **AND** a job declares `harness: ms_agent_framework`
- **THEN** that job's run MUST build its harness with
  `ms_agent_framework`

#### Scenario: Job without override inherits the runner harness

- **WHEN** the runner is configured with `deep_agents`
- **AND** a job declares no `harness:` key
- **THEN** the job's run MUST build its harness with `deep_agents`

#### Scenario: Auto resolves against the job's role

- **WHEN** the runner is configured with `auto`
- **AND** a job's role prefers `outlook:*` tools and
  `ms_agent_framework` is enabled for the persona
- **THEN** the job's run MUST build its harness with
  `ms_agent_framework`

#### Scenario: Non-string harness value fails persona load

- **WHEN** a job declares `harness: 3`
- **THEN** persona load MUST fail with an error naming the job
