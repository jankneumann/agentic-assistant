"""Tests for the scheduler capability (P7 — openspec change ``scheduler``).

Covers: ``schedules:`` parsing/validation, croniter next-fire math
(frozen time), the AssistantScheduler job loops (happy path, per-job
error isolation, graceful shutdown), the calendar trigger source
protocol with a test fake, and the ``scheduler`` consumer binding
default via ConsumerModelProvider / HarnessJobRunner.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from assistant.core.capabilities.models import (
    ModelRegistry,
    ModelRequest,
    RegistryModelProvider,
    parse_model_registry,
)
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.core.scheduler import (
    DEFAULT_SCHEDULER_CONSUMER,
    AssistantScheduler,
    CalendarEvent,
    CalendarTriggerSource,
    ConsumerModelProvider,
    HarnessJobRunner,
    ScheduleConfig,
    ScheduleConfigError,
    ScheduledJob,
    ScheduleTrigger,
    next_fire_time,
    parse_schedule_config,
)
from assistant.harnesses.base import SdkHarnessAdapter

# ── Helpers ───────────────────────────────────────────────────────────


def make_persona(**overrides: Any) -> PersonaConfig:
    defaults: dict[str, Any] = dict(
        name="fixture",
        display_name="Fixture",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={"deep_agents": {"enabled": True}},
        tool_sources={},
        extensions=[],
        extensions_dir=Path("/nonexistent"),
    )
    defaults.update(overrides)
    return PersonaConfig(**defaults)


def make_job(**overrides: Any) -> ScheduledJob:
    defaults: dict[str, Any] = dict(
        name="job",
        trigger=ScheduleTrigger(kind="interval", interval_seconds=60.0),
        role="chief_of_staff",
        prompt="do the thing",
    )
    defaults.update(overrides)
    return ScheduledJob(**defaults)


class RecordingRunner:
    """JobRunner fake that records (job name, context) per run."""

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.runs: list[tuple[str, str]] = []
        self.fail_for = fail_for or set()

    async def run(self, job: ScheduledJob, *, context: str = "") -> str:
        self.runs.append((job.name, context))
        if job.name in self.fail_for:
            raise RuntimeError(f"boom in {job.name}")
        return f"ran {job.name}"


class ManualClock:
    """Injectable now()/sleep() pair driving the scheduler deterministically.

    ``sleep`` advances the virtual clock by the requested delay and
    yields control; after ``max_sleeps`` total sleeps it blocks forever
    so job loops stop firing without busy-spinning the test loop.
    """

    def __init__(self, start: datetime, *, max_sleeps: int) -> None:
        self.current = start
        self.sleeps: list[float] = []
        self.max_sleeps = max_sleeps
        self._blocked = asyncio.Event()

    def now(self) -> datetime:
        return self.current

    async def sleep(self, delay: float) -> None:
        if len(self.sleeps) >= self.max_sleeps:
            await self._blocked.wait()  # parks forever (cancelled at stop)
        self.sleeps.append(delay)
        self.current = self.current + timedelta(seconds=delay)
        await asyncio.sleep(0)


async def drain(scheduler: AssistantScheduler, cycles: int = 20) -> None:
    """Let scheduler tasks make progress, then stop them."""
    for _ in range(cycles):
        await asyncio.sleep(0)
    await scheduler.stop()


# ── Schedule parsing / validation ─────────────────────────────────────


class TestParseScheduleConfig:
    def test_empty_section_is_falsy(self) -> None:
        cfg = parse_schedule_config({})
        assert not cfg
        assert cfg.enabled_jobs() == []
        assert not parse_schedule_config(None)

    def test_valid_jobs_parse_with_defaults(self) -> None:
        cfg = parse_schedule_config(
            {
                "morning": {
                    "trigger": {"cron": "0 7 * * *"},
                    "role": "chief_of_staff",
                    "prompt": "brief me",
                },
                "triage": {
                    "trigger": {"interval": 900},
                    "role": "chief_of_staff",
                    "prompt": "triage email",
                    "consumer": "bulk",
                    "enabled": False,
                },
                "meeting": {
                    "trigger": {"calendar": "gcal", "lead_minutes": 10},
                    "role": "researcher",
                    "prompt": "prep the meeting",
                },
            }
        )
        assert bool(cfg)
        morning = cfg.jobs["morning"]
        assert morning.trigger.kind == "cron"
        assert morning.trigger.cron == "0 7 * * *"
        assert morning.consumer == DEFAULT_SCHEDULER_CONSUMER == "scheduler"
        assert morning.enabled is True

        triage = cfg.jobs["triage"]
        assert triage.trigger.kind == "interval"
        assert triage.trigger.interval_seconds == 900.0
        assert triage.consumer == "bulk"
        assert triage.enabled is False

        meeting = cfg.jobs["meeting"]
        assert meeting.trigger.kind == "calendar"
        assert meeting.trigger.calendar_source == "gcal"
        assert meeting.trigger.lead_minutes == 10

        assert [j.name for j in cfg.enabled_jobs()] == ["morning", "meeting"]

    @pytest.mark.parametrize(
        ("raw", "needle"),
        [
            ("not-a-mapping", "expected a mapping"),
            ({"j": "nope"}, "expected a mapping"),
            ({"j": {"trigger": {"cron": "0 7 * * *"}, "prompt": "x", "role": "r", "surprise": 1}}, "unknown keys"),
            ({"j": {"role": "r", "prompt": "x"}}, "missing required 'trigger'"),
            ({"j": {"trigger": "hourly", "role": "r", "prompt": "x"}}, "'trigger' must be a mapping"),
            ({"j": {"trigger": {}, "role": "r", "prompt": "x"}}, "exactly one"),
            ({"j": {"trigger": {"cron": "0 7 * * *", "interval": 60}, "role": "r", "prompt": "x"}}, "exactly one"),
            ({"j": {"trigger": {"cron": "not a cron"}, "role": "r", "prompt": "x"}}, "invalid cron expression"),
            ({"j": {"trigger": {"interval": 0}, "role": "r", "prompt": "x"}}, "positive number"),
            ({"j": {"trigger": {"interval": -5}, "role": "r", "prompt": "x"}}, "positive number"),
            ({"j": {"trigger": {"interval": True}, "role": "r", "prompt": "x"}}, "positive number"),
            ({"j": {"trigger": {"calendar": ""}, "role": "r", "prompt": "x"}}, "calendar"),
            ({"j": {"trigger": {"calendar": "gcal", "lead_minutes": 0}, "role": "r", "prompt": "x"}}, "lead_minutes"),
            ({"j": {"trigger": {"interval": 60, "lead_minutes": 5}, "role": "r", "prompt": "x"}}, "lead_minutes"),
            ({"j": {"trigger": {"interval": 60}, "prompt": "x"}}, "'role'"),
            ({"j": {"trigger": {"interval": 60}, "role": "r", "prompt": "   "}}, "'prompt'"),
            ({"j": {"trigger": {"interval": 60}, "role": "r", "prompt": "x", "consumer": ""}}, "'consumer'"),
            ({"j": {"trigger": {"interval": 60}, "role": "r", "prompt": "x", "enabled": "yes"}}, "'enabled'"),
        ],
    )
    def test_invalid_sections_raise_actionable_errors(
        self, raw: Any, needle: str
    ) -> None:
        with pytest.raises(ScheduleConfigError, match="(?i)" + needle.replace("'", ".")):
            parse_schedule_config(raw)

    def test_error_names_the_offending_job(self) -> None:
        with pytest.raises(ScheduleConfigError, match="'bad_job'"):
            parse_schedule_config(
                {"bad_job": {"trigger": {"cron": "@@"}, "role": "r", "prompt": "x"}}
            )


class TestPersonaLoadSchedules:
    def test_persona_yaml_schedules_parse_at_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from assistant.core.persona import PersonaRegistry

        pdir = tmp_path / "sched"
        pdir.mkdir()
        (pdir / "persona.yaml").write_text(
            "name: sched\n"
            "schedules:\n"
            "  morning:\n"
            "    trigger: {cron: '0 7 * * *'}\n"
            "    role: chief_of_staff\n"
            "    prompt: brief me\n"
        )
        pc = PersonaRegistry(tmp_path).load("sched")
        assert pc.schedules
        assert pc.schedules.jobs["morning"].consumer == "scheduler"

    def test_invalid_schedules_fail_persona_load_with_context(
        self, tmp_path: Path
    ) -> None:
        from assistant.core.persona import PersonaRegistry

        pdir = tmp_path / "sched"
        pdir.mkdir()
        (pdir / "persona.yaml").write_text(
            "name: sched\n"
            "schedules:\n"
            "  broken:\n"
            "    trigger: {interval: -1}\n"
            "    role: chief_of_staff\n"
            "    prompt: x\n"
        )
        with pytest.raises(ValueError, match="invalid schedules: section"):
            PersonaRegistry(tmp_path).load("sched")

    def test_persona_without_schedules_is_falsy(self, tmp_path: Path) -> None:
        from assistant.core.persona import PersonaRegistry

        pdir = tmp_path / "plain"
        pdir.mkdir()
        (pdir / "persona.yaml").write_text("name: plain\n")
        pc = PersonaRegistry(tmp_path).load("plain")
        assert not pc.schedules


# ── next-fire math (frozen time) ──────────────────────────────────────


class TestNextFireTime:
    FROZEN = datetime(2026, 7, 17, 6, 30, tzinfo=UTC)

    def test_cron_daily_fires_at_next_match(self) -> None:
        trigger = ScheduleTrigger(kind="cron", cron="0 7 * * *")
        assert next_fire_time(trigger, self.FROZEN) == datetime(
            2026, 7, 17, 7, 0, tzinfo=UTC
        )

    def test_cron_rolls_to_next_day_after_todays_match(self) -> None:
        trigger = ScheduleTrigger(kind="cron", cron="0 7 * * *")
        after = datetime(2026, 7, 17, 7, 0, tzinfo=UTC)
        assert next_fire_time(trigger, after) == datetime(
            2026, 7, 18, 7, 0, tzinfo=UTC
        )

    def test_cron_weekday_field(self) -> None:
        # 2026-07-17 is a Friday; next Monday 09:00 is 2026-07-20.
        trigger = ScheduleTrigger(kind="cron", cron="0 9 * * 1")
        assert next_fire_time(trigger, self.FROZEN) == datetime(
            2026, 7, 20, 9, 0, tzinfo=UTC
        )

    def test_interval_fires_one_period_from_now(self) -> None:
        trigger = ScheduleTrigger(kind="interval", interval_seconds=900)
        assert next_fire_time(trigger, self.FROZEN) == self.FROZEN + timedelta(
            seconds=900
        )

    def test_calendar_trigger_has_no_computed_fire_time(self) -> None:
        trigger = ScheduleTrigger(kind="calendar", calendar_source="gcal")
        assert next_fire_time(trigger, self.FROZEN) is None


# ── Scheduler runtime ─────────────────────────────────────────────────


class TestAssistantScheduler:
    async def test_interval_job_fires_and_reschedules(self) -> None:
        clock = ManualClock(
            datetime(2026, 7, 17, 6, 0, tzinfo=UTC), max_sleeps=3
        )
        runner = RecordingRunner()
        job = make_job(name="triage")
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs={"triage": job}),
            job_runner=runner,
            now=clock.now,
            sleep=clock.sleep,
        )
        scheduler.start()
        await drain(scheduler)
        assert [name for name, _ in runner.runs] == ["triage"] * 3
        assert clock.sleeps == [60.0, 60.0, 60.0]

    async def test_cron_job_sleeps_until_next_match(self) -> None:
        clock = ManualClock(
            datetime(2026, 7, 17, 6, 30, tzinfo=UTC), max_sleeps=2
        )
        runner = RecordingRunner()
        job = make_job(
            name="morning",
            trigger=ScheduleTrigger(kind="cron", cron="0 7 * * *"),
        )
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs={"morning": job}),
            job_runner=runner,
            now=clock.now,
            sleep=clock.sleep,
        )
        scheduler.start()
        await drain(scheduler)
        # First sleep: 06:30 → 07:00 (1800s); second: 07:00 → next-day 07:00.
        assert clock.sleeps == [1800.0, 86400.0]
        assert [name for name, _ in runner.runs] == ["morning", "morning"]

    async def test_disabled_jobs_are_not_scheduled(self) -> None:
        clock = ManualClock(datetime(2026, 7, 17, tzinfo=UTC), max_sleeps=2)
        runner = RecordingRunner()
        job = make_job(name="off", enabled=False)
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs={"off": job}),
            job_runner=runner,
            now=clock.now,
            sleep=clock.sleep,
        )
        scheduler.start()
        await drain(scheduler)
        assert runner.runs == []

    async def test_failing_job_is_isolated_from_other_jobs(self) -> None:
        clock = ManualClock(datetime(2026, 7, 17, tzinfo=UTC), max_sleeps=4)
        runner = RecordingRunner(fail_for={"bad"})
        jobs = {
            "bad": make_job(
                name="bad",
                trigger=ScheduleTrigger(kind="interval", interval_seconds=60),
            ),
            "good": make_job(
                name="good",
                trigger=ScheduleTrigger(kind="interval", interval_seconds=60),
            ),
        }
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs=jobs),
            job_runner=runner,
            now=clock.now,
            sleep=clock.sleep,
        )
        scheduler.start()
        await drain(scheduler)
        ran = [name for name, _ in runner.runs]
        # The failing job keeps rescheduling AND the good job keeps running.
        assert ran.count("bad") >= 2
        assert ran.count("good") >= 2

    async def test_stop_cancels_all_tasks(self) -> None:
        runner = RecordingRunner()
        job = make_job(
            name="slow",
            trigger=ScheduleTrigger(kind="interval", interval_seconds=3600),
        )
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs={"slow": job}),
            job_runner=runner,
        )
        scheduler.start()
        tasks = list(scheduler._tasks)
        assert tasks and all(not t.done() for t in tasks)
        await scheduler.stop()
        assert all(t.done() for t in tasks)
        assert scheduler._tasks == []
        assert runner.runs == []  # never fired within the hour


# ── Calendar triggers ─────────────────────────────────────────────────


class FakeCalendarSource:
    """Test fake implementing the CalendarTriggerSource protocol."""

    def __init__(self, name: str, events: list[CalendarEvent]) -> None:
        self.name = name
        self.events = events
        self.polls: list[int] = []

    async def upcoming_events(
        self, *, within_minutes: int
    ) -> list[CalendarEvent]:
        self.polls.append(within_minutes)
        return list(self.events)


class TestCalendarTriggers:
    NOW = datetime(2026, 7, 17, 9, 0, tzinfo=UTC)

    def make_calendar_job(self, lead: int = 15) -> ScheduledJob:
        return make_job(
            name="meeting_brief",
            trigger=ScheduleTrigger(
                kind="calendar", calendar_source="gcal", lead_minutes=lead
            ),
            role="researcher",
            prompt="prep the meeting",
        )

    def test_fake_satisfies_protocol(self) -> None:
        assert isinstance(FakeCalendarSource("gcal", []), CalendarTriggerSource)

    async def test_event_in_lead_window_fires_once(self) -> None:
        event = CalendarEvent(
            event_id="evt-1",
            title="Design review",
            start=self.NOW + timedelta(minutes=10),
            detail="Room 4",
        )
        source = FakeCalendarSource("gcal", [event])
        clock = ManualClock(self.NOW, max_sleeps=3)
        runner = RecordingRunner()
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs={"meeting_brief": self.make_calendar_job()}),
            job_runner=runner,
            calendar_sources=[source],
            calendar_poll_seconds=60.0,
            now=clock.now,
            sleep=clock.sleep,
        )
        scheduler.start()
        await drain(scheduler)
        # Several polls happened, but the event fired exactly once.
        assert len(source.polls) >= 2
        assert source.polls[0] == 15
        assert len(runner.runs) == 1
        name, context = runner.runs[0]
        assert name == "meeting_brief"
        assert "Design review" in context
        assert "Room 4" in context

    async def test_event_outside_lead_window_does_not_fire(self) -> None:
        event = CalendarEvent(
            event_id="evt-2",
            title="Far future",
            start=self.NOW + timedelta(hours=3),
        )
        source = FakeCalendarSource("gcal", [event])
        clock = ManualClock(self.NOW, max_sleeps=2)
        runner = RecordingRunner()
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs={"meeting_brief": self.make_calendar_job()}),
            job_runner=runner,
            calendar_sources=[source],
            now=clock.now,
            sleep=clock.sleep,
        )
        scheduler.start()
        await drain(scheduler)
        assert runner.runs == []

    async def test_missing_calendar_source_skips_job_without_task(self) -> None:
        runner = RecordingRunner()
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs={"meeting_brief": self.make_calendar_job()}),
            job_runner=runner,
            calendar_sources=[],  # gcal not available yet (deferred impl)
        )
        scheduler.start()
        assert scheduler._tasks == []
        await scheduler.stop()

    async def test_source_poll_failure_is_isolated(self) -> None:
        class ExplodingSource:
            name = "gcal"

            def __init__(self) -> None:
                self.calls = 0

            async def upcoming_events(self, *, within_minutes: int):
                self.calls += 1
                raise ConnectionError("calendar API down")

        source = ExplodingSource()
        clock = ManualClock(self.NOW, max_sleeps=2)
        runner = RecordingRunner()
        scheduler = AssistantScheduler(
            make_persona(),
            ScheduleConfig(jobs={"meeting_brief": self.make_calendar_job()}),
            job_runner=runner,
            calendar_sources=[source],
            now=clock.now,
            sleep=clock.sleep,
        )
        scheduler.start()
        await drain(scheduler)
        assert source.calls >= 2  # kept polling despite the failure
        assert runner.runs == []


# ── Consumer binding (P19) ────────────────────────────────────────────


def _registry_with_scheduler_binding() -> ModelRegistry:
    return parse_model_registry(
        {
            "entries": {
                "sonnet": {"dialect": "anthropic", "id": "claude-sonnet"},
                "local-cheap": {
                    "dialect": "openai-compatible",
                    "id": "llama-3.1-8b",
                    "endpoint": "http://gx10.local:8000/v1",
                    "tags": ["cheap", "local-only"],
                },
            },
            "bindings": {
                "default": "sonnet",
                "deep_agents": "sonnet",
                "scheduler": "local-cheap",
            },
        }
    )


class TestConsumerModelProvider:
    def test_rewrites_consumer_to_scheduler_binding(self) -> None:
        provider = RegistryModelProvider(_registry_with_scheduler_binding())
        wrapped = ConsumerModelProvider(provider, "scheduler")
        # A harness asks with its own name; the wrapper resolves the
        # scheduler binding instead of deep_agents' sonnet.
        chain = wrapped.resolve(ModelRequest(consumer="deep_agents"))
        assert [ref.name for ref in chain] == ["local-cheap"]

    def test_list_models_passes_through(self) -> None:
        provider = RegistryModelProvider(_registry_with_scheduler_binding())
        wrapped = ConsumerModelProvider(provider, "scheduler")
        assert [r.name for r in wrapped.list_models()] == [
            "sonnet",
            "local-cheap",
        ]


class CapturingHarness(SdkHarnessAdapter):
    """SDK-harness stub capturing constructor kwargs and invocations."""

    last_instance: CapturingHarness | None = None

    def __init__(self, persona: PersonaConfig, role: RoleConfig, **kwargs: Any) -> None:
        super().__init__(persona, role)
        self.kwargs = kwargs
        self.invocations: list[str] = []
        CapturingHarness.last_instance = self

    def name(self) -> str:
        return "capturing"

    async def create_agent(self, tools: list[Any], extensions: list[Any]) -> Any:
        self.agent_tools = tools
        self.agent_extensions = extensions
        return object()

    async def invoke(self, agent: Any, message: str) -> str:
        self.invocations.append(message)
        return "job done"

    async def spawn_sub_agent(
        self, role, task, tools, extensions, context=None
    ) -> str:
        return "n/a"


class TestHarnessJobRunner:
    def make_role_registry(self) -> Any:
        class FakeRoleRegistry:
            def __init__(self) -> None:
                self.loaded: list[str] = []

            def load(self, role_name: str, persona: PersonaConfig) -> RoleConfig:
                self.loaded.append(role_name)
                return RoleConfig(
                    name=role_name,
                    display_name=role_name.title(),
                    description="",
                    prompt="You are a test role.",
                )

        return FakeRoleRegistry()

    async def test_happy_path_runs_job_under_consumer_binding(self) -> None:
        persona = make_persona(
            models=parse_model_registry(
                {
                    "entries": {
                        "sonnet": {"dialect": "anthropic", "id": "s"},
                        "local-cheap": {
                            "dialect": "openai-compatible",
                            "id": "l",
                            "endpoint": "http://gx10.local:8000/v1",
                        },
                    },
                    "bindings": {
                        "default": "sonnet",
                        "scheduler": "local-cheap",
                    },
                }
            )
        )
        role_reg = self.make_role_registry()

        def fake_create_harness(pc, rc, harness_name, **kwargs):
            assert harness_name == "deep_agents"
            return CapturingHarness(pc, rc, **kwargs)

        runner = HarnessJobRunner(
            persona,
            role_registry=role_reg,
            create_harness_fn=fake_create_harness,
        )
        job = make_job(name="morning", prompt="brief me")
        response = await runner.run(job)

        assert response == "job done"
        assert role_reg.loaded == ["chief_of_staff"]
        harness = CapturingHarness.last_instance
        assert harness is not None
        assert harness.invocations == ["brief me"]
        # The injected model provider resolves under the job's consumer
        # binding — default `scheduler` → local-cheap, not the default
        # sonnet binding.
        provider = harness.kwargs["model_provider"]
        chain = provider.resolve(ModelRequest(consumer="deep_agents"))
        assert [ref.name for ref in chain] == ["local-cheap"]

    async def test_context_is_appended_to_prompt(self) -> None:
        persona = make_persona()
        runner = HarnessJobRunner(
            persona,
            role_registry=self.make_role_registry(),
            create_harness_fn=lambda pc, rc, hn, **kw: CapturingHarness(
                pc, rc, **kw
            ),
        )
        await runner.run(make_job(prompt="prep"), context="Upcoming event: X")
        harness = CapturingHarness.last_instance
        assert harness is not None
        assert harness.invocations == ["prep\n\nUpcoming event: X"]

    async def test_host_harness_is_rejected(self) -> None:
        from assistant.harnesses.host.claude_code import ClaudeCodeHarness

        persona = make_persona()
        runner = HarnessJobRunner(
            persona,
            harness_name="claude_code",
            role_registry=self.make_role_registry(),
            create_harness_fn=lambda pc, rc, hn, **kw: ClaudeCodeHarness(pc, rc),
        )
        with pytest.raises(ValueError, match="host harness"):
            await runner.run(make_job())


class TestFactorySdkKwargs:
    def test_factory_forwards_sdk_kwargs(self) -> None:
        from assistant.harnesses.factory import create_harness

        persona = make_persona()
        role = RoleConfig(
            name="chief_of_staff",
            display_name="CoS",
            description="",
            prompt="",
        )
        sentinel = object()
        adapter = create_harness(
            persona, role, "deep_agents", model_provider=sentinel
        )
        assert adapter._model_provider is sentinel  # type: ignore[attr-defined]

    def test_factory_rejects_sdk_kwargs_for_host_harness(self) -> None:
        from assistant.harnesses.factory import create_harness

        persona = make_persona()
        role = RoleConfig(
            name="chief_of_staff",
            display_name="CoS",
            description="",
            prompt="",
        )
        with pytest.raises(ValueError, match="host harness"):
            create_harness(
                persona, role, "claude_code", model_provider=object()
            )
