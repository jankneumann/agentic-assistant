# scheduler — Design

## D1. One module, two halves, no import cycle

Both the `schedules:` schema and the runtime live in
`core/scheduler.py` (the roadmap names that file). `core/persona.py`
imports the schema half (`parse_schedule_config`, `ScheduleConfig`,
`ScheduleConfigError`), so the module keeps a strict import
discipline: module level imports only stdlib + `croniter`;
persona/role types are `TYPE_CHECKING`-only; runtime collaborators
(`RoleRegistry`, `CapabilityResolver`, the harness factory) are
imported lazily inside `HarnessJobRunner` — the same pattern the
harnesses already use for `CapabilityResolver`.

## D2. Trigger vocabulary and semantics

`trigger:` declares exactly one of:

- `cron: "<expr>"` — 5-field croniter syntax, validated at persona
  load (`croniter.is_valid`). Fire times are computed against UTC
  wall-clock (`datetime.now(UTC)`), consistent with the P13 budget
  windows.
- `interval: <seconds>` — positive number; the first fire is one
  period after daemon start (no thundering fire-at-boot: a triage job
  with `interval: 900` should not run the instant the laptop wakes).
- `calendar: <source>` + optional `lead_minutes` (default 15) —
  event-driven; see D5.

Ambiguity (zero or multiple kinds), invalid expressions, and
`lead_minutes` on non-calendar triggers are load-time
`ScheduleConfigError`s naming the job, surfaced by persona load
exactly like `models:`/`guardrails:` failures.

**Missed fires are skipped, not replayed**: the scheduler computes
next-fire from *now* after each run. If the process was down at 07:00,
the morning briefing runs tomorrow at 07:00, not at 11:23 when the
daemon restarts. Catch-up semantics need durable job history (persona
DB) and are out of scope.

## D3. Fresh harness per job run; consumer binding via provider wrap

Each run does `role_registry.load(job.role)` →
`create_harness(persona, rc, harness_name, model_provider=...)` →
`create_agent` → `invoke`, then discards the harness. A fresh harness
per run buys: current memory snippets at `create_agent` time (P21
prepend), no cross-job conversation bleed (fresh `thread_id` /
checkpointer), and crash isolation.

The job's `consumer` binding (default `scheduler`) is honored by
wrapping the persona's resolved `RegistryModelProvider` in
`ConsumerModelProvider`, which rewrites `ModelRequest.consumer` before
delegating. Harnesses keep asking with their own name
(`consumer=self.name()`) — the wrapper redirects the lookup, so no
harness code changes. Registry fallback semantics are preserved: an
unbound `scheduler` consumer falls back to the `default` binding, then
tag resolution (synthesized-default personas therefore work with zero
config). Budget gating is untouched — the binding path still runs
`check_model_call` against the persona's guardrails.

**Factory passthrough (deviation-adjacent, recorded here)**: the
wrapper must reach the harness constructor's documented
`model_provider=` kwarg, so `create_harness` gains `**sdk_kwargs`
forwarded to SDK harness constructors only (host harnesses reject
them). This is additive — the harness-adapter spec's
`create_harness(persona, role, harness_name)` contract and all its
scenarios hold unchanged — so no harness-adapter delta is filed.

## D4. Result storage: harness capture, no double-write (deviation)

The pre-made decision said "results stored via
`MemoryPolicy.record_interaction`". Both SDK harnesses ALREADY do that
on every successful `invoke` (P21 post-turn capture in
`SdkHarnessAdapter._capture_interaction`, error-swallowed). Having the
runner call `record_interaction` again would write two interaction
rows per job run. Deviation: the runner relies on the harness capture
for persistence and additionally logs the job name, role, consumer,
and a truncated response at INFO. Net behavior matches the intent
(scheduled results land in memory + logs) without duplicate rows.

## D5. Calendar triggers: protocol now, implementations later

`CalendarTriggerSource` is a `runtime_checkable` protocol —
`name: str` plus `async upcoming_events(*, within_minutes) ->
list[CalendarEvent]` — that calendar-capable extensions (gcal,
outlook) implement in their own phases. The daemon collects loaded
extensions satisfying the protocol (structural `isinstance`, same
posture as the extension lifecycle hooks) and hands them to the
scheduler; the scheduler polls each job's named source every
`calendar_poll_seconds` (default 300) and fires when an event's start
enters the `lead_minutes` window, deduplicating on
`(job_name, event_id)` so one meeting yields one brief. A declared
`calendar` job with no matching source is skipped with a WARNING at
startup (declared-but-deferred — persona configs can ship ahead of
the extension). Poll failures are logged and retried next cycle.
Scoped deferral: no production source ships in P7; the protocol is
exercised by a test fake.

## D6. Daemon CLI shape

`assistant daemon -p <persona>` — a subcommand, matching the existing
CLI grammar (`run`/`serve`/`export`/`simulate` are subcommands; a
`--daemon` flag on `run` would tangle REPL and headless lifecycles).
Recorded choice per the pre-made decision's "pick what fits" clause.

- Up-front validation (roles resolvable, harness SDK + enabled,
  ≥1 enabled job) so misconfiguration fails at start, not at 07:00.
- `--serve` co-hosts the AG-UI SSE server via
  `uvicorn.Server.serve()` as a sibling task (same process, same
  extension set), bound to the persona's `default_role`.
- Graceful shutdown: SIGINT/SIGTERM → stop event → server
  `should_exit` → `scheduler.stop()` (cancel + gather) →
  `PersonaRegistry.shutdown_extensions()` in the outer `finally`
  (P10), mirroring `_run_repl`'s teardown ownership.
- The discovery `httpx.AsyncClient` stays open for the daemon's
  lifetime (registered HTTP tools hold it), mirroring `_run_repl`'s
  context-manager structure.
- Budget posture: the CLI warns when a `model_call` budget uses the
  in-memory ledger — a daemon that restarts silently re-arms its
  ceilings; `persist: file` is the documented recommendation
  (template + CLAUDE.md).

## D7. Testability seams

`AssistantScheduler` takes injectable `now()` / `sleep()` (the P13
`PolicyGuardrails(now=...)` pattern extended with a sleep hook) so
tests drive cron math and loop behavior deterministically with a
virtual clock — no real sleeping, no flaky wall-clock assertions.
`HarnessJobRunner` takes `create_harness_fn` (the CLI passes its
module-level `_create_harness`, keeping the established monkeypatch
seam) and an injectable role registry. Rejected alternative: a
library scheduler (APScheduler) — croniter + ~150 lines of asyncio is
smaller than the dependency and keeps the injection seams native.
