# scheduler Specification (delta)

## ADDED Requirements

### Requirement: Reflection Job Kind

The system SHALL support an optional `kind:` key on `schedules:` jobs
with values `agent` (default — the existing harness-spawning run
path, fully backward compatible) and `reflect` (P28
continual-learning). For `kind: reflect` jobs, `role` and `prompt`
SHALL be optional (unused); unknown kinds MUST fail schedule parsing
with an actionable error naming the job. At run time the job runner
MUST dispatch `reflect` jobs to the learning reflection pass
(`run_reflection_for_persona`) instead of creating a harness, with
the same per-job error isolation as agent jobs. The daemon CLI MUST
validate `reflect` jobs' prerequisites up front — an enabled
`learning:` section and a configured `database_url` — instead of
role/harness validation, so misconfiguration fails at startup rather
than mid-flight.

#### Scenario: Reflect job parses without role or prompt

- **WHEN** a job declares `{trigger: {cron: "0 3 * * *"}, kind:
  reflect}`
- **THEN** schedule parsing MUST succeed with `kind="reflect"` and
  empty role/prompt

#### Scenario: Agent jobs keep requiring role and prompt

- **WHEN** a job without `kind:` omits `role`
- **THEN** parsing MUST fail naming the job and the missing role

#### Scenario: Unknown kind fails actionably

- **WHEN** a job declares `kind: dream`
- **THEN** parsing MUST fail naming the job and the allowed kinds

#### Scenario: Runner dispatches reflect jobs to the learning pass

- **WHEN** the job runner runs a `kind: reflect` job
- **THEN** it MUST invoke the learning reflection entry point and
  MUST NOT create a harness

#### Scenario: Daemon validates reflect prerequisites up front

- **WHEN** `assistant daemon` starts for a persona with a `reflect`
  job but no enabled `learning:` section (or no `database_url`)
- **THEN** the daemon MUST refuse to start with an error naming the
  job and the missing prerequisite
