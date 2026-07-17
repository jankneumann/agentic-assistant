# scheduler — Cron / Calendar / Polling Triggers + Daemon Mode (P7)

## Why

Every capability so far is reactive: the assistant only acts when a
human opens the REPL or POSTs to `/chat`. The roadmap's flagship
workflows — morning briefing, email triage, pre-meeting briefs
(roadmap row P7; perplexity §2.1/§8.6) — are proactive: they must fire
on wall-clock schedules and calendar events with nobody at the
keyboard. There is no scheduling primitive anywhere in the stack, and
no CLI mode that keeps a persona resident.

Scheduled work also changes the cost calculus: a job firing every 15
minutes must not burn the interactive model tier. P19 built exactly
the right seam for this — per-consumer model bindings — but nothing
non-interactive consumes it yet.

## What Changes

- **`core/scheduler.py`** (new): the `schedules:` schema
  (`parse_schedule_config`, validated at persona load with the same
  actionable-error posture as `models:`/`guardrails:`) and the
  asyncio runtime (`AssistantScheduler` — one task per enabled job,
  croniter next-fire math for `cron` triggers, fixed sleeps for
  `interval` triggers, polling of `CalendarTriggerSource` providers
  for `calendar` triggers; per-job error isolation; `stop()` cancels
  all tasks).
- **`schedules:` section in persona.yaml**: named jobs with
  `trigger:` (`cron:` | `interval:` | `calendar:` + `lead_minutes`),
  `role:`, `prompt:`, optional `consumer:` (models bindings key,
  default `scheduler`) and `enabled:`. Parsed onto
  `PersonaConfig.schedules`; documented in `personas/_template/`.
- **Scheduled jobs are model consumers (P19)**: each run resolves its
  chat model under the job's `consumer` binding via a
  `ConsumerModelProvider` wrapper injected through the harness
  factory (`create_harness` gains optional SDK-constructor
  passthrough kwargs), so owners route background work to cheap/local
  tiers without touching interactive bindings.
- **`assistant daemon -p <persona>`** (new CLI subcommand): validates
  jobs/roles/harness up front, loads extensions
  (`load_extensions_async`), runs HTTP-tool discovery once, starts
  the scheduler, optionally co-hosts the AG-UI SSE server
  (`--serve`), handles SIGINT/SIGTERM gracefully, and runs
  `shutdown_extensions()` on teardown. Warns when a model-call budget
  uses the in-memory ledger (daemons should set `persist: file`).
- **Calendar triggers ship as interface + test fake only** (scoped
  deferral): the `CalendarTriggerSource` protocol is defined now so
  gcal/outlook extensions can implement it in their own phases;
  declared `calendar` jobs are skipped with a warning until a
  matching source is enabled.
- **New dependency**: `croniter` (roadmap-approved) + `types-croniter`
  (dev).

## Impact

- Affected specs: `scheduler` (ADDED), `cli-interface` (MODIFIED —
  new `daemon` subcommand), `persona-registry` (MODIFIED — new
  `schedules:` section parsing).
- Affected code: `src/assistant/core/scheduler.py` (new),
  `src/assistant/core/persona.py` (parse + `PersonaConfig.schedules`),
  `src/assistant/harnesses/factory.py` (optional SDK kwargs
  passthrough), `src/assistant/cli.py` (`daemon` subcommand),
  `personas/_template/persona.yaml`, `pyproject.toml`, `CLAUDE.md`.
- Not in scope: real calendar sources (land with the Google/work
  extension phases), durable job history / missed-fire catch-up
  (needs the persona DB — a run that the process sleeps through is
  skipped), persona-DB budget ledger (P13 deferral unchanged).
