# scheduler — Tasks

## 1. Schema + persona wiring

- [x] 1.1 `core/scheduler.py` — `ScheduleTrigger` / `ScheduledJob` /
  `ScheduleConfig` dataclasses, `parse_schedule_config` with
  actionable `ScheduleConfigError`s (exactly-one-trigger rule, cron
  validation via croniter, positive interval, calendar source +
  lead_minutes, consumer default `scheduler`, enabled bool)
- [x] 1.2 `core/persona.py` — parse `schedules:` at load onto
  `PersonaConfig.schedules` (same error posture as models/guardrails)
- [x] 1.3 `personas/_template/persona.yaml` — documented `schedules:`
  example (morning briefing / email triage / pre-meeting brief) +
  daemon `persist: file` note
- [x] 1.4 `pyproject.toml` — add `croniter` (runtime) and
  `types-croniter` (dev)

## 2. Scheduler runtime

- [x] 2.1 `next_fire_time` — croniter next-match for cron, now+period
  for interval, `None` for calendar
- [x] 2.2 `AssistantScheduler` — one task per enabled job, timer loop
  (cron/interval) + calendar polling loop, per-job error isolation
  (`run_job_once` logs and swallows, CancelledError propagates),
  `stop()` cancel+gather; injectable `now`/`sleep`
- [x] 2.3 `CalendarTriggerSource` protocol + `CalendarEvent`;
  per-event dedupe, lead-window check, missing-source startup
  warning, poll-failure isolation
- [x] 2.4 `ConsumerModelProvider` + `HarnessJobRunner` — fresh harness
  per run via `create_harness(..., model_provider=wrapped)`,
  role-filtered tool resolution, host-harness rejection; result
  persisted by the harness's P21 capture (see design D4)
- [x] 2.5 `harnesses/factory.py` — `**sdk_kwargs` passthrough to SDK
  constructors; host harnesses reject injection kwargs

## 3. Daemon CLI

- [x] 3.1 `cli.py` — `assistant daemon -p <persona> [-H harness]
  [--serve --host --port]`; up-front validation (schedules present,
  ≥1 enabled job, roles load, harness SDK+enabled); in-memory budget
  ledger warning
- [x] 3.2 `_run_daemon` — discovery client held open, extensions via
  `load_extensions_async`, scheduler + optional uvicorn server tasks,
  SIGINT/SIGTERM stop event, teardown: server → scheduler.stop() →
  `shutdown_extensions()`

## 4. Tests

- [x] 4.1 `tests/test_scheduler.py` — parse validation (valid +
  parametrized error table), persona-load integration, frozen-time
  cron/interval next-fire math, interval/cron loop firing with
  virtual clock, disabled jobs, per-job error isolation, graceful
  shutdown, calendar fake (protocol conformance, lead window, dedupe,
  missing source, poll-failure isolation), `ConsumerModelProvider`
  rewrite, `HarnessJobRunner` happy path (default `scheduler`
  consumer resolves the scheduler binding) + context append + host
  rejection, factory sdk_kwargs passthrough/rejection
- [x] 4.2 `tests/test_cli_daemon.py` — command registration, required
  persona, no-schedules / all-disabled / unknown-role / host-harness /
  disabled-harness errors, happy-path wiring (stubbed `_run_daemon`),
  `--serve` forwarding, budget-ledger warning on/off

## 5. Docs + gates

- [x] 5.1 OpenSpec change: proposal / design / tasks + deltas
  (ADDED `scheduler`; MODIFIED `cli-interface`, `persona-registry`);
  `openspec validate scheduler --strict` passes
- [x] 5.2 CLAUDE.md — daemon/scheduler section
- [x] 5.3 Gates: `uv run pytest tests/ -q`, `uv run ruff check src
  tests`, `uv run mypy src tests`
