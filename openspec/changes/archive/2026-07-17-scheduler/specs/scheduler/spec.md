# scheduler Specification (delta)

## ADDED Requirements

### Requirement: Trigger Vocabulary and Next-Fire Computation

The system SHALL support exactly three schedule trigger kinds — `cron`
(5-field croniter expression, fired at matching UTC wall-clock times),
`interval` (positive number of seconds, first fire one period after
scheduler start), and `calendar` (named calendar trigger source with a
positive `lead_minutes` window, default 15) — and SHALL compute
next-fire times for `cron` triggers via croniter and for `interval`
triggers as now plus the period, while `calendar` triggers have no
computed fire time (they are event-driven, polled).

#### Scenario: Cron next-fire uses croniter math

- **WHEN** `next_fire_time` is called for a `cron: "0 7 * * *"`
  trigger at 2026-07-17T06:30Z
- **THEN** the result MUST be 2026-07-17T07:00Z
- **AND** calling it again at 2026-07-17T07:00Z MUST return
  2026-07-18T07:00Z

#### Scenario: Interval fires one period from now

- **WHEN** `next_fire_time` is called for an `interval: 900` trigger
- **THEN** the result MUST be exactly 900 seconds after the supplied
  `now`

#### Scenario: Calendar triggers have no computed fire time

- **WHEN** `next_fire_time` is called for a `calendar` trigger
- **THEN** the result MUST be `None`

#### Scenario: Missed fires are skipped, not replayed

- **WHEN** the daemon starts after a `cron` job's most recent match
  time has passed
- **THEN** the job MUST next run at the following cron match
- **AND** the missed occurrence MUST NOT be executed retroactively

### Requirement: Scheduled Job Execution Spawns a Fresh Harness Per Run

The scheduler SHALL execute each job run by loading the job's `role`,
constructing a fresh SDK harness through the harness factory,
resolving the role-filtered tool set, and calling `create_agent`
followed by `invoke` with the job's `prompt` (plus trigger context,
when present, appended after a blank line). The completed interaction
SHALL be persisted through the harness's post-turn memory capture
(`MemoryPolicy.record_interaction`) and the response summary SHALL be
logged. A host harness selection MUST be rejected with an actionable
error.

#### Scenario: Job run drives role, harness, and prompt

- **WHEN** a job with `role: chief_of_staff` and `prompt: "brief me"`
  fires
- **THEN** the runner MUST load `chief_of_staff`, build a harness via
  the factory, and invoke the created agent with `"brief me"`

#### Scenario: Trigger context is appended to the prompt

- **WHEN** a calendar-triggered run supplies event context
- **THEN** the invoked message MUST be the job prompt followed by a
  blank line and the context

#### Scenario: Host harness is rejected

- **WHEN** the runner is configured with a host harness name
- **THEN** the job run MUST fail with an error identifying the harness
  as a host harness

### Requirement: Scheduled Jobs Resolve Models Under Their Consumer Binding

Each scheduled job run SHALL resolve its chat model through the
persona's model registry under the job's `consumer` binding key
(default `scheduler`), by injecting a consumer-rewriting
`ModelProvider` wrapper into the harness, so persona owners can route
background work to cheap/local tiers (P19) without changing
interactive bindings. Registry fallback semantics MUST be preserved:
an unbound consumer falls back to the `default` binding, then
tag-filtered resolution, so personas without a `scheduler` binding
keep working.

#### Scenario: Scheduler binding overrides the harness binding

- **WHEN** the persona binds `deep_agents: sonnet` and
  `scheduler: local-cheap` and a scheduled job fires with the default
  consumer
- **THEN** the harness's model resolution MUST return the
  `local-cheap` chain, not `sonnet`

#### Scenario: Unbound scheduler consumer falls back

- **WHEN** the persona registry declares no `scheduler` binding
- **THEN** resolution MUST fall back to the `default` binding, then to
  tag-filtered resolution, rather than failing

### Requirement: Per-Job Error Isolation

The scheduler SHALL isolate job failures: an exception raised by one
job run MUST be logged and swallowed, the failing job's loop MUST
continue to its next fire, and other jobs MUST be unaffected.
Cancellation MUST propagate so shutdown always wins.

#### Scenario: A failing job never kills the daemon

- **WHEN** one job's runner raises on every fire while a second job is
  scheduled
- **THEN** both jobs MUST continue to fire on their subsequent
  schedules

#### Scenario: Calendar source poll failure is isolated

- **WHEN** a job's calendar source raises during a poll
- **THEN** the failure MUST be logged and the source MUST be polled
  again on the next cycle

### Requirement: Calendar Trigger Source Protocol

The system SHALL define a `CalendarTriggerSource` protocol — a `name`
attribute plus `async upcoming_events(*, within_minutes)` returning
upcoming `CalendarEvent`s — that calendar-capable extensions implement
in later phases. The scheduler SHALL poll each calendar job's named
source and fire the job once per event (deduplicated on event id) when
the event's start time enters the job's `lead_minutes` window, passing
event context into the run. A declared calendar job whose named source
is not available SHALL be skipped with a startup warning rather than
failing the daemon.

#### Scenario: Event inside the lead window fires exactly once

- **WHEN** a source reports an event starting 10 minutes from now for
  a job with `lead_minutes: 15`
- **THEN** the job MUST fire exactly once for that event across
  subsequent polls
- **AND** the run context MUST include the event title and start time

#### Scenario: Event outside the lead window does not fire

- **WHEN** a source reports only an event starting 3 hours from now
- **THEN** the job MUST NOT fire

#### Scenario: Missing source defers the job

- **WHEN** a persona declares a calendar job naming a source that no
  loaded extension provides
- **THEN** the scheduler MUST log a warning naming the job and source
- **AND** MUST schedule no task for that job
- **AND** all other jobs MUST start normally

### Requirement: Graceful Scheduler Shutdown

The scheduler SHALL expose `stop()` that cancels every job task and
awaits their completion, leaving no running tasks behind; extension
shutdown is owned by the daemon caller (which runs
`PersonaRegistry.shutdown_extensions()` in its teardown).

#### Scenario: Stop cancels all job tasks

- **WHEN** `stop()` is called while job tasks are sleeping toward
  their next fire
- **THEN** every task MUST be cancelled and awaited
- **AND** the scheduler's task list MUST be empty afterward
