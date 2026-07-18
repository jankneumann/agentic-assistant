"""Tests for P11 harness-routing (openspec change: harness-routing).

Covers the harness-adapter delta (Automatic Harness Selection +
Harness Routing Decision Telemetry), the persona-registry delta
(Harness Routing Rules Parsing), and the scheduler delta (Per-Job
Harness Override) at the unit level. CLI-level auto-default coverage
lives in ``tests/test_cli.py`` / ``tests/test_cli_daemon.py``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from assistant.core.harness_routing import (
    HarnessRoutingError,
    HarnessRoutingRule,
    parse_harness_routing,
    role_prefers_ms_tools,
    rule_matches,
)
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.core.scheduler import (
    HarnessJobRunner,
    ScheduleConfigError,
    ScheduledJob,
    ScheduleTrigger,
    parse_schedule_config,
)
from assistant.harnesses.factory import select_harness


def _persona(
    deep_enabled: bool = True,
    ms_enabled: bool = False,
    routing: tuple[HarnessRoutingRule, ...] = (),
) -> PersonaConfig:
    return PersonaConfig(
        name="p",
        display_name="P",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={
            "deep_agents": {"enabled": deep_enabled},
            "ms_agent_framework": {"enabled": ms_enabled},
            "claude_code": {"enabled": True},
        },
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
        harness_routing=routing,
    )


def _role(
    name: str = "r", preferred_tools: list[str] | None = None
) -> RoleConfig:
    return RoleConfig(
        name=name,
        display_name=name.title(),
        description="",
        prompt="test prompt",
        preferred_tools=preferred_tools or [],
        delegation={"allowed_sub_roles": []},
    )


# ── Rule schema parsing (persona-registry delta) ─────────────────────


def test_parse_absent_section_is_empty_tuple() -> None:
    assert parse_harness_routing(None) == ()
    assert parse_harness_routing([]) == ()


def test_parse_valid_rules_preserve_order() -> None:
    rules = parse_harness_routing(
        [
            {"tools": ["ms_graph:*"], "harness": "ms_agent_framework"},
            {"role": "*", "harness": "deep_agents"},
        ]
    )
    assert [r.harness for r in rules] == [
        "ms_agent_framework",
        "deep_agents",
    ]
    assert rules[0].tools == ("ms_graph:*",)
    assert rules[1].role == "*"


def test_parse_rejects_non_list() -> None:
    with pytest.raises(HarnessRoutingError, match="expected a list"):
        parse_harness_routing({"harness": "deep_agents"})


def test_parse_rejects_unknown_keys() -> None:
    with pytest.raises(HarnessRoutingError, match=r"rule\[0\].*model"):
        parse_harness_routing(
            [{"role": "*", "harness": "deep_agents", "model": "x"}]
        )


def test_parse_rejects_missing_harness() -> None:
    with pytest.raises(HarnessRoutingError, match=r"rule\[0\].*'harness'"):
        parse_harness_routing([{"role": "coder"}])


def test_parse_rejects_rule_without_matcher() -> None:
    with pytest.raises(HarnessRoutingError, match=r"rule\[0\].*matcher"):
        parse_harness_routing([{"harness": "deep_agents"}])


def test_parse_rejects_bad_tools_type() -> None:
    with pytest.raises(HarnessRoutingError, match=r"rule\[1\].*'tools'"):
        parse_harness_routing(
            [
                {"role": "*", "harness": "deep_agents"},
                {"tools": "ms_graph:*", "harness": "deep_agents"},
            ]
        )


def test_persona_load_parses_and_pops_routing(tmp_path: Path) -> None:
    """Persona-registry delta: rules land on ``harness_routing`` and
    the ``routing`` key leaves the harnesses mapping."""
    from assistant.core.persona import PersonaRegistry

    pdir = tmp_path / "routed"
    pdir.mkdir()
    (pdir / "persona.yaml").write_text(
        """
name: routed
harnesses:
  deep_agents: {enabled: true}
  routing:
    - tools: ["ms_graph:*"]
      harness: ms_agent_framework
"""
    )
    pc = PersonaRegistry(personas_dir=tmp_path).load("routed")
    assert pc.harness_routing == (
        HarnessRoutingRule(
            harness="ms_agent_framework", tools=("ms_graph:*",)
        ),
    )
    assert "routing" not in pc.harnesses


def test_persona_load_surfaces_routing_error_with_context(
    tmp_path: Path,
) -> None:
    from assistant.core.persona import PersonaRegistry

    pdir = tmp_path / "broken"
    pdir.mkdir()
    (pdir / "persona.yaml").write_text(
        """
name: broken
harnesses:
  routing:
    - harness: deep_agents
"""
    )
    with pytest.raises(
        ValueError, match=r"invalid harnesses\.routing: section"
    ):
        PersonaRegistry(personas_dir=tmp_path).load("broken")


# ── Matching helpers ─────────────────────────────────────────────────


def test_rule_matches_role_glob() -> None:
    rule = HarnessRoutingRule(harness="deep_agents", role="cod*")
    assert rule_matches(rule, "coder", [])
    assert not rule_matches(rule, "writer", [])


def test_rule_matches_tools_full_and_prefix_patterns() -> None:
    full = HarnessRoutingRule(
        harness="ms_agent_framework", tools=("outlook:send_*",)
    )
    bare = HarnessRoutingRule(
        harness="ms_agent_framework", tools=("outlook",)
    )
    tools = ["outlook:send_mail", "content_analyzer:search"]
    assert rule_matches(full, "any", tools)
    assert rule_matches(bare, "any", tools)
    assert not rule_matches(full, "any", ["outlook:list_folders"])
    assert not rule_matches(bare, "any", ["content_analyzer:search"])


def test_rule_matchers_are_anded() -> None:
    rule = HarnessRoutingRule(
        harness="ms_agent_framework", role="coder", tools=("ms_graph:*",)
    )
    assert rule_matches(rule, "coder", ["ms_graph:list_users"])
    assert not rule_matches(rule, "coder", ["coding_tools:repo_status"])
    assert not rule_matches(rule, "writer", ["ms_graph:list_users"])


def test_role_prefers_ms_tools_detects_all_four_sources() -> None:
    for source in ("ms_graph", "outlook", "teams", "sharepoint"):
        assert role_prefers_ms_tools([f"{source}:anything"])
    assert not role_prefers_ms_tools(
        ["content_analyzer:search", "coding_tools:repo_status"]
    )
    assert not role_prefers_ms_tools([])


# ── select_harness precedence (harness-adapter delta) ────────────────


def test_explicit_request_bypasses_rules() -> None:
    persona = _persona(
        ms_enabled=True,
        routing=(
            HarnessRoutingRule(harness="ms_agent_framework", role="*"),
        ),
    )
    assert (
        select_harness(persona, _role(), requested="deep_agents")
        == "deep_agents"
    )


def test_explicit_request_passes_through_even_when_disabled() -> None:
    """Enablement validation stays in create_harness — select just
    honors the explicit choice."""
    persona = _persona(ms_enabled=False)
    assert (
        select_harness(persona, _role(), requested="ms_agent_framework")
        == "ms_agent_framework"
    )


def test_auto_sentinel_behaves_like_none() -> None:
    persona = _persona()
    assert select_harness(persona, _role(), requested="auto") == (
        select_harness(persona, _role())
    )


def test_rules_win_over_builtin_defaults() -> None:
    persona = _persona(
        ms_enabled=True,
        routing=(
            HarnessRoutingRule(harness="ms_agent_framework", role="coder"),
        ),
    )
    # coder prefers no MS tools, yet the rule routes it to MSAF.
    assert select_harness(persona, _role("coder")) == "ms_agent_framework"


def test_rules_first_match_wins() -> None:
    persona = _persona(
        ms_enabled=True,
        routing=(
            HarnessRoutingRule(harness="deep_agents", role="coder"),
            HarnessRoutingRule(harness="ms_agent_framework", role="*"),
        ),
    )
    assert select_harness(persona, _role("coder")) == "deep_agents"
    assert select_harness(persona, _role("writer")) == "ms_agent_framework"


def test_matching_rule_with_disabled_target_is_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    persona = _persona(
        ms_enabled=False,
        routing=(
            HarnessRoutingRule(harness="ms_agent_framework", role="*"),
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert select_harness(persona, _role()) == "deep_agents"
    assert any(
        "rule[0]" in record.getMessage() and "not enabled" in record.getMessage()
        for record in caplog.records
    )


def test_rule_naming_unknown_harness_raises() -> None:
    persona = _persona(
        routing=(HarnessRoutingRule(harness="nonexistent", role="*"),)
    )
    with pytest.raises(ValueError, match="unknown harness"):
        select_harness(persona, _role())


def test_rule_naming_host_harness_raises() -> None:
    persona = _persona(
        routing=(HarnessRoutingRule(harness="claude_code", role="*"),)
    )
    with pytest.raises(ValueError, match="host harness"):
        select_harness(persona, _role())


def test_ms_source_role_routes_to_msaf_when_enabled() -> None:
    persona = _persona(ms_enabled=True)
    role = _role("triage", ["outlook:send_mail", "content_analyzer:search"])
    assert select_harness(persona, role) == "ms_agent_framework"


def test_ms_source_role_falls_back_when_msaf_disabled() -> None:
    persona = _persona(ms_enabled=False)
    role = _role("triage", ["ms_graph:list_users"])
    assert select_harness(persona, role) == "deep_agents"


def test_general_role_routes_to_deep_agents() -> None:
    persona = _persona(ms_enabled=True)
    role = _role("researcher", ["content_analyzer:search"])
    assert select_harness(persona, role) == "deep_agents"


def test_only_enabled_sdk_harness_wins_without_ms_signal() -> None:
    persona = _persona(deep_enabled=False, ms_enabled=True)
    assert select_harness(persona, _role()) == "ms_agent_framework"


def test_host_harness_never_auto_selected() -> None:
    """claude_code is enabled but auto must not pick it: host
    harnesses export config rather than execute."""
    persona = _persona(deep_enabled=False, ms_enabled=False)
    with pytest.raises(ValueError, match="explicit-only"):
        select_harness(persona, _role())


# ── Routing decision telemetry ───────────────────────────────────────


def test_routing_decision_emits_span() -> None:
    provider = MagicMock()
    with patch(
        "assistant.telemetry.get_observability_provider",
        return_value=provider,
    ):
        selected = select_harness(_persona(), _role())
    assert selected == "deep_agents"
    provider.start_span.assert_called_once()
    args, kwargs = provider.start_span.call_args
    assert args[0] == "harness.routing"
    attributes = kwargs["attributes"]
    assert attributes["selected"] == "deep_agents"
    assert attributes["reason"].startswith("builtin:")
    assert attributes["requested"] == "auto"
    assert attributes["persona"] == "p"
    assert attributes["role"] == "r"


def test_routing_decision_span_carries_rule_reason() -> None:
    provider = MagicMock()
    persona = _persona(
        ms_enabled=True,
        routing=(
            HarnessRoutingRule(harness="ms_agent_framework", role="*"),
        ),
    )
    with patch(
        "assistant.telemetry.get_observability_provider",
        return_value=provider,
    ):
        select_harness(persona, _role())
    attributes = provider.start_span.call_args.kwargs["attributes"]
    assert attributes["reason"] == "rule[0]"


def test_telemetry_failure_does_not_break_selection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = MagicMock()
    provider.start_span.side_effect = RuntimeError("collector down")
    with patch(
        "assistant.telemetry.get_observability_provider",
        return_value=provider,
    ), caplog.at_level(logging.WARNING):
        selected = select_harness(_persona(), _role())
    assert selected == "deep_agents"
    assert any(
        "routing span not emitted" in record.getMessage()
        for record in caplog.records
    )


# ── Scheduler per-job harness override (scheduler delta) ─────────────


def test_parse_schedule_accepts_harness_key() -> None:
    cfg = parse_schedule_config(
        {
            "j": {
                "trigger": {"interval": 60},
                "role": "coder",
                "prompt": "go",
                "harness": "ms_agent_framework",
            }
        }
    )
    assert cfg.jobs["j"].harness == "ms_agent_framework"


def test_parse_schedule_harness_defaults_to_inherit() -> None:
    cfg = parse_schedule_config(
        {"j": {"trigger": {"interval": 60}, "role": "r", "prompt": "go"}}
    )
    assert cfg.jobs["j"].harness == ""


@pytest.mark.parametrize("bad", [3, "", None, True])
def test_parse_schedule_rejects_bad_harness(bad: object) -> None:
    with pytest.raises(ScheduleConfigError, match="'harness'"):
        parse_schedule_config(
            {
                "j": {
                    "trigger": {"interval": 60},
                    "role": "r",
                    "prompt": "go",
                    "harness": bad,
                }
            }
        )


def _make_job(harness: str = "") -> ScheduledJob:
    return ScheduledJob(
        name="j",
        trigger=ScheduleTrigger(kind="interval", interval_seconds=60),
        role="r",
        prompt="go",
        harness=harness,
    )


def _runner_with_capture(
    persona: PersonaConfig, harness_name: str, seen: list[str]
):
    from assistant.harnesses.base import SdkHarnessAdapter

    class _Adapter(SdkHarnessAdapter):
        def name(self) -> str:
            return "stub"

        def harness_type(self) -> str:
            return "sdk"

        async def create_agent(self, tools, extensions):
            return object()

        async def invoke(self, agent, message) -> str:
            return "ok"

        async def spawn_sub_agent(
            self, role, task, tools, extensions, context=None
        ):
            return "ok"

    def fake_create(pc, rc, name, **kwargs):
        seen.append(name)
        return _Adapter(pc, rc)

    role_registry = MagicMock()
    role_registry.load.return_value = _role("r", ["outlook:send_mail"])
    runner = HarnessJobRunner(
        persona,
        harness_name=harness_name,
        role_registry=role_registry,
        create_harness_fn=fake_create,
    )
    # Model-provider / tool aggregation pull the full capability
    # resolver; stub them out — harness selection is what's under test.
    runner._build_model_provider = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]
    runner._authorized_tools = MagicMock(return_value=[])  # type: ignore[method-assign]
    return runner


def test_job_harness_override_wins_over_runner_default() -> None:
    seen: list[str] = []
    runner = _runner_with_capture(_persona(ms_enabled=True), "deep_agents", seen)
    asyncio.run(runner.run(_make_job(harness="ms_agent_framework")))
    assert seen == ["ms_agent_framework"]


def test_job_without_override_inherits_runner_harness() -> None:
    seen: list[str] = []
    runner = _runner_with_capture(_persona(), "deep_agents", seen)
    asyncio.run(runner.run(_make_job()))
    assert seen == ["deep_agents"]


def test_auto_runner_resolves_against_job_role() -> None:
    """Runner default 'auto' + MS-tool role + MSAF enabled → MSAF."""
    seen: list[str] = []
    runner = _runner_with_capture(_persona(ms_enabled=True), "auto", seen)
    asyncio.run(runner.run(_make_job()))
    assert seen == ["ms_agent_framework"]


def test_job_auto_override_resolves_even_with_concrete_runner() -> None:
    seen: list[str] = []
    runner = _runner_with_capture(
        _persona(ms_enabled=True), "deep_agents", seen
    )
    asyncio.run(runner.run(_make_job(harness="auto")))
    assert seen == ["ms_agent_framework"]
