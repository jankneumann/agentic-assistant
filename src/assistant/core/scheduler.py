"""Scheduler — cron / interval / calendar-event triggers (P7 scheduler).

Two halves live here:

1. **Schema**: the persona ``schedules:`` section is parsed and
   validated at persona load by :func:`parse_schedule_config` with the
   same actionable-error posture as the ``models:`` registry and the
   ``guardrails:`` section (a bad section fails persona load naming
   the offending job and key).
2. **Runtime**: :class:`AssistantScheduler` runs the enabled jobs on
   an asyncio loop — cron next-fire math via ``croniter``, fixed
   ``interval`` sleeps, and a polling loop over
   :class:`CalendarTriggerSource` providers for ``calendar`` triggers.
   Each job run is delegated to a :class:`JobRunner` (production:
   :class:`HarnessJobRunner`, which spawns a fresh SDK harness per run
   with the job's role and its ``consumer`` model binding). A failing
   job run never kills the daemon (per-job error isolation), and
   ``stop()`` cancels all job tasks for graceful shutdown.

Scheduled work is a **model consumer** (P19): every job resolves its
chat model through the persona ``models:`` registry under the job's
``consumer`` binding key — default ``"scheduler"`` — so owners can
route recurring background work (morning briefing, email triage,
pre-meeting briefs) to local/cheap tiers without touching the
interactive bindings. See
:class:`~assistant.core.capabilities.models.ModelRequest`.

Import discipline: ``core/persona.py`` imports the schema half of this
module, so nothing here may import persona/role/harness modules at
module level — runtime collaborators are imported lazily inside
:class:`HarnessJobRunner` (the same pattern the harnesses use for
``CapabilityResolver``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from croniter import croniter

if TYPE_CHECKING:
    from assistant.core.capabilities.models import ModelProvider, ModelRef, ModelRequest
    from assistant.core.persona import PersonaConfig

logger = logging.getLogger(__name__)

#: Default ``bindings:`` lookup key for scheduled jobs (P19 consumer
#: vocabulary). Personas SHOULD bind ``scheduler`` to a cheap/local
#: entry so recurring background work never burns the interactive tier.
DEFAULT_SCHEDULER_CONSUMER: str = "scheduler"

#: Default minutes-before-event-start at which a ``calendar`` trigger
#: fires its job.
DEFAULT_CALENDAR_LEAD_MINUTES: int = 15

#: Default seconds between polls of a job's CalendarTriggerSource.
DEFAULT_CALENDAR_POLL_SECONDS: float = 300.0

_TRIGGER_KINDS = ("cron", "interval", "calendar")
_JOB_KEYS = frozenset({"trigger", "role", "prompt", "consumer", "enabled"})
_TRIGGER_KEYS = frozenset({*_TRIGGER_KINDS, "lead_minutes"})


class ScheduleConfigError(ValueError):
    """A persona ``schedules:`` section failed validation at load time."""


@dataclass
class ScheduleTrigger:
    """One job trigger — exactly one of the three kinds.

    - ``cron``: 5-field cron expression (``croniter`` syntax), fires at
      each matching wall-clock time (UTC).
    - ``interval``: fixed period in seconds; first fire is one period
      after daemon start.
    - ``calendar``: named :class:`CalendarTriggerSource` (an extension
      implementing the protocol, e.g. ``gcal`` / ``outlook`` when P14
      lands); fires ``lead_minutes`` before each upcoming event starts.
    """

    kind: str
    cron: str = ""
    interval_seconds: float = 0.0
    calendar_source: str = ""
    lead_minutes: int = DEFAULT_CALENDAR_LEAD_MINUTES


@dataclass
class ScheduledJob:
    """One named entry of the persona ``schedules:`` section."""

    name: str
    trigger: ScheduleTrigger
    role: str
    prompt: str
    consumer: str = DEFAULT_SCHEDULER_CONSUMER
    enabled: bool = True


@dataclass
class ScheduleConfig:
    """Parsed persona ``schedules:`` section.

    Falsy (the default) when the persona declares no schedules — the
    ``daemon`` CLI refuses to start without jobs.
    """

    jobs: dict[str, ScheduledJob] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.jobs)

    def enabled_jobs(self) -> list[ScheduledJob]:
        return [job for job in self.jobs.values() if job.enabled]


def _parse_trigger(job_name: str, raw: Any) -> ScheduleTrigger:
    if not isinstance(raw, dict):
        raise ScheduleConfigError(
            f"schedules job {job_name!r}: 'trigger' must be a mapping "
            f"with exactly one of {list(_TRIGGER_KINDS)}, got "
            f"{type(raw).__name__}."
        )
    unknown = sorted(set(raw) - _TRIGGER_KEYS)
    if unknown:
        raise ScheduleConfigError(
            f"schedules job {job_name!r}: trigger has unknown keys "
            f"{unknown}. Allowed: {sorted(_TRIGGER_KEYS)}."
        )
    declared = [k for k in _TRIGGER_KINDS if k in raw]
    if len(declared) != 1:
        raise ScheduleConfigError(
            f"schedules job {job_name!r}: trigger must declare exactly "
            f"one of {list(_TRIGGER_KINDS)}, got {declared or 'none'}."
        )
    kind = declared[0]

    if "lead_minutes" in raw and kind != "calendar":
        raise ScheduleConfigError(
            f"schedules job {job_name!r}: 'lead_minutes' applies only "
            f"to calendar triggers."
        )

    if kind == "cron":
        expr = raw["cron"]
        if not isinstance(expr, str) or not croniter.is_valid(expr):
            raise ScheduleConfigError(
                f"schedules job {job_name!r}: invalid cron expression "
                f"{expr!r} (expected 5-field croniter syntax, e.g. "
                f"'0 7 * * *')."
            )
        return ScheduleTrigger(kind="cron", cron=expr)

    if kind == "interval":
        seconds = raw["interval"]
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or seconds <= 0
        ):
            raise ScheduleConfigError(
                f"schedules job {job_name!r}: 'interval' must be a "
                f"positive number of seconds, got {seconds!r}."
            )
        return ScheduleTrigger(kind="interval", interval_seconds=float(seconds))

    # kind == "calendar"
    source = raw["calendar"]
    if not isinstance(source, str) or not source:
        raise ScheduleConfigError(
            f"schedules job {job_name!r}: 'calendar' must name a "
            f"calendar trigger source (e.g. an extension name), got "
            f"{source!r}."
        )
    lead = raw.get("lead_minutes", DEFAULT_CALENDAR_LEAD_MINUTES)
    if isinstance(lead, bool) or not isinstance(lead, int) or lead <= 0:
        raise ScheduleConfigError(
            f"schedules job {job_name!r}: 'lead_minutes' must be a "
            f"positive integer, got {lead!r}."
        )
    return ScheduleTrigger(
        kind="calendar", calendar_source=source, lead_minutes=lead
    )


def parse_schedule_config(raw: dict[str, Any] | None) -> ScheduleConfig:
    """Parse and validate a persona ``schedules:`` section.

    Shape::

        schedules:
          morning_briefing:
            trigger: {cron: "0 7 * * *"}     # or {interval: 900}
            role: chief_of_staff             # or {calendar: gcal,
            prompt: "Prepare my briefing."   #     lead_minutes: 15}
            consumer: scheduler              # optional models binding key
            enabled: true                    # optional, default true

    Unknown keys, missing/empty ``role`` or ``prompt``, ambiguous or
    invalid triggers, and non-boolean ``enabled`` fail with
    :class:`ScheduleConfigError` naming the offending job — persona
    load surfaces this as an actionable error (same posture as
    ``models:`` / ``guardrails:``).
    """
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ScheduleConfigError(
            f"schedules: expected a mapping of job name -> job spec, "
            f"got {type(raw).__name__}."
        )

    jobs: dict[str, ScheduledJob] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ScheduleConfigError(
                f"schedules job {name!r}: expected a mapping, got "
                f"{type(spec).__name__}."
            )
        unknown = sorted(set(spec) - _JOB_KEYS)
        if unknown:
            raise ScheduleConfigError(
                f"schedules job {name!r}: unknown keys {unknown}. "
                f"Allowed: {sorted(_JOB_KEYS)}."
            )
        if "trigger" not in spec:
            raise ScheduleConfigError(
                f"schedules job {name!r}: missing required 'trigger'."
            )
        trigger = _parse_trigger(name, spec["trigger"])

        role = spec.get("role", "")
        if not isinstance(role, str) or not role:
            raise ScheduleConfigError(
                f"schedules job {name!r}: 'role' must be a non-empty "
                f"role name."
            )
        prompt = spec.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ScheduleConfigError(
                f"schedules job {name!r}: 'prompt' must be non-empty "
                f"task text."
            )
        consumer = spec.get("consumer", DEFAULT_SCHEDULER_CONSUMER)
        if not isinstance(consumer, str) or not consumer:
            raise ScheduleConfigError(
                f"schedules job {name!r}: 'consumer' must be a "
                f"non-empty models bindings key (default "
                f"{DEFAULT_SCHEDULER_CONSUMER!r})."
            )
        enabled = spec.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ScheduleConfigError(
                f"schedules job {name!r}: 'enabled' must be a boolean, "
                f"got {enabled!r}."
            )
        jobs[name] = ScheduledJob(
            name=name,
            trigger=trigger,
            role=role,
            prompt=prompt,
            consumer=consumer,
            enabled=enabled,
        )
    return ScheduleConfig(jobs=jobs)


def next_fire_time(trigger: ScheduleTrigger, now: datetime) -> datetime | None:
    """Next wall-clock fire time for a time-based trigger.

    ``cron`` triggers use croniter's next-match math; ``interval``
    triggers fire one period from ``now``. ``calendar`` triggers are
    event-driven (polled, not computed) and return ``None``.
    """
    if trigger.kind == "cron":
        result: datetime = croniter(trigger.cron, now).get_next(datetime)
        return result
    if trigger.kind == "interval":
        return now + timedelta(seconds=trigger.interval_seconds)
    return None


# ── Calendar-event trigger source (interface now, impls in P14) ──────


@dataclass
class CalendarEvent:
    """One upcoming event surfaced by a :class:`CalendarTriggerSource`."""

    event_id: str
    title: str
    start: datetime
    detail: str = ""


@runtime_checkable
class CalendarTriggerSource(Protocol):
    """Protocol a calendar-capable extension implements to feed
    ``calendar`` triggers.

    ``name`` must match the job trigger's ``calendar:`` value (for
    extensions, the extension name — ``gcal`` / ``outlook``).
    ``upcoming_events`` returns events starting within the next
    ``within_minutes`` minutes; the scheduler polls it and fires the
    job once per event (deduplicated on ``event_id``) when the event
    enters the trigger's ``lead_minutes`` window. Implementations land
    with the google-extensions / work-persona phases; until then the
    interface is exercised by test fakes only (P7 scoped deferral).
    """

    name: str

    async def upcoming_events(
        self, *, within_minutes: int
    ) -> list[CalendarEvent]: ...


# ── Job execution ─────────────────────────────────────────────────────


@runtime_checkable
class JobRunner(Protocol):
    """Execute one scheduled job run; returns the agent's response."""

    async def run(self, job: ScheduledJob, *, context: str = "") -> str: ...


class ConsumerModelProvider:
    """ModelProvider wrapper that pins the ``consumer`` binding key.

    Harnesses resolve their chat model with
    ``ModelRequest(consumer=<harness name>)``; wrapping the resolved
    registry provider with this class makes that request resolve under
    the scheduled job's ``consumer`` key instead (default
    ``scheduler``), so the P19 binding table — not the harness name —
    picks the model tier for background work.
    """

    def __init__(self, inner: ModelProvider, consumer: str) -> None:
        self._inner = inner
        self._consumer = consumer

    def resolve(self, request: ModelRequest) -> list[ModelRef]:
        return self._inner.resolve(replace(request, consumer=self._consumer))

    def list_models(self) -> list[ModelRef]:
        return self._inner.list_models()


class HarnessJobRunner:
    """Production JobRunner: fresh SDK harness per job run.

    Per run: load the job's role, wrap the persona's registry
    ModelProvider in :class:`ConsumerModelProvider` (job ``consumer``
    binding), build the harness through the factory, resolve the
    role-filtered tool set, ``create_agent`` + ``invoke``. The
    interaction is persisted by the harness's own post-turn capture
    (``SdkHarnessAdapter._capture_interaction`` →
    ``MemoryPolicy.record_interaction``, P21) — the runner does not
    double-write; it logs the response summary.

    ``create_harness_fn`` is the injectable factory seam (tests pass a
    stub; the CLI passes its module-level ``_create_harness``).
    """

    def __init__(
        self,
        persona: PersonaConfig,
        *,
        harness_name: str = "deep_agents",
        role_registry: Any = None,
        http_tool_registry: Any = None,
        extensions: Sequence[Any] = (),
        create_harness_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._persona = persona
        self._harness_name = harness_name
        self._role_registry = role_registry
        self._http_tool_registry = http_tool_registry
        self._extensions = list(extensions)
        self._create_harness = create_harness_fn

    def _load_role(self, role_name: str) -> Any:
        registry = self._role_registry
        if registry is None:
            from assistant.core.role import RoleRegistry

            registry = RoleRegistry()
            self._role_registry = registry
        return registry.load(role_name, self._persona)

    def _build_model_provider(self, rc: Any, consumer: str) -> ConsumerModelProvider:
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver(
            http_tool_registry=self._http_tool_registry
        )
        provider = resolver.resolve(self._persona, "sdk", rc).models
        assert provider is not None  # resolver always fills slot #6
        return ConsumerModelProvider(provider, consumer)

    def _authorized_tools(self, rc: Any) -> list[Any]:
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver(
            http_tool_registry=self._http_tool_registry
        )
        capabilities = resolver.resolve(self._persona, "sdk", rc)
        return capabilities.tools.authorized_tools(
            self._persona, rc, loaded_extensions=self._extensions
        )

    async def run(self, job: ScheduledJob, *, context: str = "") -> str:
        from assistant.harnesses.base import SdkHarnessAdapter
        from assistant.harnesses.factory import (
            create_harness as default_create_harness,
        )

        rc = self._load_role(job.role)
        create = self._create_harness or default_create_harness
        adapter = create(
            self._persona,
            rc,
            self._harness_name,
            model_provider=self._build_model_provider(rc, job.consumer),
        )
        if not isinstance(adapter, SdkHarnessAdapter):
            raise ValueError(
                f"Scheduled job {job.name!r}: harness "
                f"{self._harness_name!r} is a host harness; scheduled "
                f"jobs require an SDK harness."
            )
        agent = await adapter.create_agent(
            tools=self._authorized_tools(rc), extensions=self._extensions
        )
        message = job.prompt if not context else f"{job.prompt}\n\n{context}"
        response = await adapter.invoke(agent, message)
        logger.info(
            "scheduled job %r (role=%s, consumer=%s) completed: %.200s",
            job.name,
            job.role,
            job.consumer,
            response,
        )
        return response


# ── Scheduler runtime ─────────────────────────────────────────────────


class AssistantScheduler:
    """Asyncio scheduler for one persona's ``schedules:`` jobs.

    One task per enabled job. Cron/interval tasks sleep until the next
    fire time and run the job; calendar tasks poll their
    :class:`CalendarTriggerSource` and fire once per upcoming event
    inside the lead window. A job run that raises is logged and the
    job's loop continues — a failing job never kills the daemon.
    ``stop()`` cancels all tasks and awaits them (graceful shutdown);
    extension shutdown is owned by the caller (the ``daemon`` CLI runs
    ``PersonaRegistry.shutdown_extensions()`` in its teardown).

    ``now`` / ``sleep`` are injectable for deterministic tests.
    """

    def __init__(
        self,
        persona: PersonaConfig,
        config: ScheduleConfig,
        *,
        job_runner: JobRunner,
        calendar_sources: Sequence[Any] = (),
        calendar_poll_seconds: float = DEFAULT_CALENDAR_POLL_SECONDS,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._persona = persona
        self._config = config
        self._runner = job_runner
        self._calendar_sources = list(calendar_sources)
        self._calendar_poll_seconds = calendar_poll_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._sleep = sleep or asyncio.sleep
        self._tasks: list[asyncio.Task[None]] = []
        self._fired_events: set[tuple[str, str]] = set()

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        """Spawn one asyncio task per enabled job. Idempotent-unsafe —
        call once per scheduler instance."""
        for job in self._config.enabled_jobs():
            if job.trigger.kind == "calendar":
                source = self._find_calendar_source(job)
                if source is None:
                    logger.warning(
                        "scheduled job %r: no CalendarTriggerSource named "
                        "%r is available (calendar extensions land in a "
                        "later phase); job declared but not scheduled.",
                        job.name,
                        job.trigger.calendar_source,
                    )
                    continue
                coro = self._calendar_loop(job, source)
            else:
                coro = self._timer_loop(job)
            self._tasks.append(
                asyncio.get_running_loop().create_task(
                    coro, name=f"schedule:{job.name}"
                )
            )
        logger.info(
            "scheduler started for persona %r with %d job task(s)",
            getattr(self._persona, "name", "<unknown>"),
            len(self._tasks),
        )

    async def stop(self) -> None:
        """Cancel all job tasks and await their completion."""
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("scheduler stopped (%d task(s) cancelled)", len(tasks))

    # -- job loops -----------------------------------------------------

    async def _timer_loop(self, job: ScheduledJob) -> None:
        while True:
            now = self._now()
            fire_at = next_fire_time(job.trigger, now)
            assert fire_at is not None  # timer loop only gets cron/interval
            delay = max((fire_at - now).total_seconds(), 0.0)
            await self._sleep(delay)
            await self.run_job_once(job)

    def _find_calendar_source(self, job: ScheduledJob) -> Any | None:
        for source in self._calendar_sources:
            if getattr(source, "name", "") == job.trigger.calendar_source:
                return source
        return None

    async def _calendar_loop(self, job: ScheduledJob, source: Any) -> None:
        lead = job.trigger.lead_minutes
        while True:
            try:
                events = await source.upcoming_events(within_minutes=lead)
            except Exception:
                logger.exception(
                    "scheduled job %r: calendar source %r poll failed; "
                    "retrying next cycle",
                    job.name,
                    job.trigger.calendar_source,
                )
                events = []
            now = self._now()
            for event in events:
                key = (job.name, event.event_id)
                if key in self._fired_events:
                    continue
                seconds_to_start = (event.start - now).total_seconds()
                if 0 <= seconds_to_start <= lead * 60:
                    self._fired_events.add(key)
                    context = (
                        f"Upcoming event: {event.title} at "
                        f"{event.start.isoformat()}"
                    )
                    if event.detail:
                        context = f"{context}\n{event.detail}"
                    await self.run_job_once(job, context=context)
            await self._sleep(self._calendar_poll_seconds)

    # -- execution -----------------------------------------------------

    async def run_job_once(self, job: ScheduledJob, *, context: str = "") -> None:
        """Run one job with per-job error isolation.

        Cancellation propagates (shutdown must win); every other
        exception is logged and swallowed so the job's loop — and every
        other job — keeps running.
        """
        logger.info("scheduled job %r firing (trigger=%s)", job.name, job.trigger.kind)
        try:
            await self._runner.run(job, context=context)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "scheduled job %r failed; the daemon and other jobs "
                "continue",
                job.name,
            )
