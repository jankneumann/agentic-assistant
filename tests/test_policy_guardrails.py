"""Tests for PolicyGuardrails — security-hardening (P13).

Covers: protocol conformance, ``guardrails:`` config parsing +
validation errors, action policies (allow/deny/require_confirmation,
first-match-wins, resource globs), model-call budget ceilings
(allows-then-denies across calls, daily + monthly windows, cost
estimation ladder, unknown-cost degradation), file-persisted ledger,
delegation constraints, ``declare_risk`` tiers,
``require_confirmation`` on ``model_call`` denying via the P19 budget
hook, and resolver selection (PolicyGuardrails when the persona
declares ``guardrails:``, AllowAll otherwise, factory override
preserved).
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from assistant.core.capabilities.guardrails import (
    AllowAllGuardrails,
    GuardrailConfig,
    GuardrailConfigError,
    GuardrailProvider,
    InMemoryBudgetLedger,
    JsonFileBudgetLedger,
    PolicyGuardrails,
    parse_guardrail_config,
)
from assistant.core.capabilities.types import ActionRequest, RiskLevel

_NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)


def _request(
    action_type: str = "model_call",
    resource: str = "some-model",
    metadata: dict | None = None,
) -> ActionRequest:
    return ActionRequest(
        action_type=action_type,
        resource=resource,
        persona="personal",
        role="chief_of_staff",
        metadata=metadata or {},
    )


def _guardrails(raw: dict, **kwargs) -> PolicyGuardrails:
    config = parse_guardrail_config(raw)
    kwargs.setdefault("ledger", InMemoryBudgetLedger())
    kwargs.setdefault("now", lambda: _NOW)
    return PolicyGuardrails(config, persona="personal", **kwargs)


# ── protocol + config parsing ────────────────────────────────────────


def test_policy_guardrails_satisfies_protocol() -> None:
    assert isinstance(
        PolicyGuardrails(GuardrailConfig(), ledger=InMemoryBudgetLedger()),
        GuardrailProvider,
    )


def test_empty_config_is_falsy_and_allows_everything() -> None:
    config = parse_guardrail_config({})
    assert not config
    guardrails = PolicyGuardrails(config, ledger=InMemoryBudgetLedger())
    assert guardrails.check_action(_request()).allowed is True


@pytest.mark.parametrize(
    "raw, needle",
    [
        ({"bogus": {}}, "unknown keys"),
        ({"policies": "nope"}, "must be a list"),
        ({"policies": [{"effect": "deny"}]}, "action_type"),
        (
            {"policies": [{"action_type": "x", "effect": "explode"}]},
            "'explode'",
        ),
        ({"budgets": {"tool_call": {}}}, "only 'model_call'"),
        (
            {"budgets": {"model_call": {"daily_usd": "five"}}},
            "must be a number",
        ),
        (
            {"budgets": {"model_call": {"daily_usd": -1}}},
            ">=",
        ),
        (
            {"budgets": {"model_call": {"persist": "postgres"}}},
            "persist",
        ),
        ({"delegation": {"denied_sub_roles": "coder"}}, "list"),
    ],
)
def test_invalid_config_raises_actionable_error(raw: dict, needle: str) -> None:
    with pytest.raises(GuardrailConfigError) as excinfo:
        parse_guardrail_config(raw)
    assert needle in str(excinfo.value)


def test_persona_load_surfaces_guardrail_config_error(
    tmp_path: Path,
) -> None:
    from assistant.core.persona import PersonaRegistry

    persona_dir = tmp_path / "broken"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        textwrap.dedent(
            """
            name: broken
            display_name: broken
            database: {url_env: ''}
            graphiti: {url_env: ''}
            auth: {provider: custom, config: {}}
            guardrails:
              policies:
                - action_type: model_call
                  effect: not-an-effect
            """
        )
    )
    with pytest.raises(ValueError) as excinfo:
        PersonaRegistry(tmp_path).load("broken")
    assert "guardrails" in str(excinfo.value)


def test_persist_file_requires_persona_dir() -> None:
    raw = {"budgets": {"model_call": {"persist": "file"}}}
    with pytest.raises(GuardrailConfigError):
        parse_guardrail_config(raw)
    config = parse_guardrail_config(raw, persona_dir=Path("/tmp/p"))
    assert config.spend_file == Path("/tmp/p/.cache/guardrails/spend.json")


# ── action policies ──────────────────────────────────────────────────


def test_deny_policy_blocks_matching_resource() -> None:
    guardrails = _guardrails(
        {
            "policies": [
                {
                    "action_type": "model_call",
                    "resource": "expensive-*",
                    "effect": "deny",
                    "reason": "too pricey",
                }
            ]
        }
    )
    decision = guardrails.check_action(
        _request(resource="expensive-opus")
    )
    assert decision.allowed is False
    assert decision.reason == "too pricey"
    # Non-matching resource is untouched.
    assert guardrails.check_action(_request(resource="cheap-model")).allowed


def test_first_matching_policy_wins() -> None:
    guardrails = _guardrails(
        {
            "policies": [
                {"action_type": "model_call", "resource": "special", "effect": "allow"},
                {"action_type": "model_call", "resource": "*", "effect": "deny"},
            ]
        }
    )
    assert guardrails.check_action(_request(resource="special")).allowed
    assert not guardrails.check_action(_request(resource="other")).allowed


def test_wildcard_action_type_matches_all() -> None:
    guardrails = _guardrails(
        {"policies": [{"action_type": "*", "effect": "deny"}]}
    )
    assert not guardrails.check_action(_request(action_type="tool_call")).allowed
    assert not guardrails.check_action(_request(action_type="model_call")).allowed


def test_require_confirmation_policy_sets_flag() -> None:
    guardrails = _guardrails(
        {
            "policies": [
                {
                    "action_type": "tool_call",
                    "resource": "gmail.send",
                    "effect": "require_confirmation",
                }
            ]
        }
    )
    decision = guardrails.check_action(
        _request(action_type="tool_call", resource="gmail.send")
    )
    assert decision.allowed is True
    assert decision.require_confirmation is True


def test_require_confirmation_on_model_call_denies_via_budget_hook() -> None:
    """P19 verdict #2: until the approval interrupt flow exists,
    require_confirmation on model_call denies at the binding hook."""
    from assistant.core.capabilities.model_bindings import (
        ModelCallDeniedError,
        check_model_call,
    )
    from assistant.core.capabilities.models import ModelRef

    guardrails = _guardrails(
        {
            "policies": [
                {
                    "action_type": "model_call",
                    "resource": "*",
                    "effect": "require_confirmation",
                }
            ]
        }
    )
    ref = ModelRef(name="m", dialect="openai-compatible")
    with pytest.raises(ModelCallDeniedError) as excinfo:
        check_model_call(guardrails, ref, persona="personal", role="r")
    assert "confirmation" in str(excinfo.value)


# ── model-call budgets ───────────────────────────────────────────────


def test_daily_budget_allows_then_denies_across_calls() -> None:
    guardrails = _guardrails(
        {"budgets": {"model_call": {"daily_usd": 1.0}}}
    )
    metadata = {"estimated_cost_usd": 0.4}
    assert guardrails.check_action(_request(metadata=metadata)).allowed
    assert guardrails.check_action(_request(metadata=metadata)).allowed
    third = guardrails.check_action(_request(metadata=metadata))
    assert third.allowed is False
    assert "daily" in third.reason
    # Denied calls do not consume budget: a smaller call still fits.
    assert guardrails.check_action(
        _request(metadata={"estimated_cost_usd": 0.15})
    ).allowed


def test_daily_window_resets_next_day() -> None:
    ledger = InMemoryBudgetLedger()
    clock = {"now": _NOW}
    guardrails = PolicyGuardrails(
        parse_guardrail_config({"budgets": {"model_call": {"daily_usd": 1.0}}}),
        persona="personal",
        ledger=ledger,
        now=lambda: clock["now"],
    )
    metadata = {"estimated_cost_usd": 0.9}
    assert guardrails.check_action(_request(metadata=metadata)).allowed
    assert not guardrails.check_action(_request(metadata=metadata)).allowed
    clock["now"] = _NOW + timedelta(days=1)
    assert guardrails.check_action(_request(metadata=metadata)).allowed


def test_monthly_ceiling_outlives_daily_window() -> None:
    ledger = InMemoryBudgetLedger()
    clock = {"now": _NOW}
    guardrails = PolicyGuardrails(
        parse_guardrail_config(
            {"budgets": {"model_call": {"monthly_usd": 1.0}}}
        ),
        persona="personal",
        ledger=ledger,
        now=lambda: clock["now"],
    )
    assert guardrails.check_action(
        _request(metadata={"estimated_cost_usd": 0.9})
    ).allowed
    clock["now"] = _NOW + timedelta(days=5)  # same calendar month
    denied = guardrails.check_action(
        _request(metadata={"estimated_cost_usd": 0.2})
    )
    assert denied.allowed is False
    assert "monthly" in denied.reason


def test_cost_estimated_from_p19_pricing_metadata() -> None:
    """check_model_call puts ModelRef.pricing on the request; the
    budget estimates with the configured token counts."""
    guardrails = _guardrails(
        {
            "budgets": {
                "model_call": {
                    "daily_usd": 0.05,
                    "estimate_input_tokens": 1000,
                    "estimate_output_tokens": 1000,
                }
            }
        }
    )
    # 1000 * 0.00003 + 1000 * 0.00003 = $0.06 > $0.05 → denied outright.
    pricing = {"prompt": "0.00003", "completion": "0.00003"}
    decision = guardrails.check_action(_request(metadata={"pricing": pricing}))
    assert decision.allowed is False


def test_unknown_cost_uses_default_call_cost() -> None:
    guardrails = _guardrails(
        {
            "budgets": {
                "model_call": {
                    "daily_usd": 1.0,
                    "default_call_cost_usd": 0.6,
                }
            }
        }
    )
    # No pricing metadata → default_call_cost_usd applies.
    assert guardrails.check_action(_request()).allowed
    assert not guardrails.check_action(_request()).allowed


def test_unknown_cost_without_default_never_consumes_budget() -> None:
    """Cost is never guessed (mirrors compute_cost): with the default
    of 0.0, unpriced calls pass without consuming budget."""
    guardrails = _guardrails(
        {"budgets": {"model_call": {"daily_usd": 0.01}}}
    )
    for _ in range(5):
        assert guardrails.check_action(_request()).allowed


def test_budget_via_model_bindings_hook_allows_then_denies() -> None:
    """End-to-end through the P19 budget hook: ModelRef.pricing rides
    ActionRequest.metadata into the ceiling check."""
    from assistant.core.capabilities.model_bindings import (
        ModelCallDeniedError,
        check_model_call,
    )
    from assistant.core.capabilities.models import ModelRef

    guardrails = _guardrails(
        {
            "budgets": {
                "model_call": {
                    "daily_usd": 0.10,
                    "estimate_input_tokens": 1000,
                    "estimate_output_tokens": 1000,
                }
            }
        }
    )
    ref = ModelRef(
        name="metered",
        dialect="openai-compatible",
        pricing={"prompt": "0.00003", "completion": "0.00003"},
    )  # $0.06 per estimated call
    check_model_call(guardrails, ref, persona="personal", role="r")
    with pytest.raises(ModelCallDeniedError) as excinfo:
        check_model_call(guardrails, ref, persona="personal", role="r")
    assert "budget" in str(excinfo.value)


def test_json_file_ledger_persists_spend(tmp_path: Path) -> None:
    path = tmp_path / ".cache" / "guardrails" / "spend.json"
    ledger = JsonFileBudgetLedger(path)
    ledger.record(0.5, _NOW)
    reloaded = JsonFileBudgetLedger(path)
    assert reloaded.spent_since(_NOW - timedelta(hours=1)) == pytest.approx(0.5)


def test_json_file_ledger_corrupt_file_degrades_to_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "spend.json"
    path.write_text("{corrupt")
    with caplog.at_level("WARNING"):
        ledger = JsonFileBudgetLedger(path)
    assert ledger.spent_since(_NOW - timedelta(days=365)) == 0.0
    assert any("unreadable" in r.getMessage() for r in caplog.records)


def test_budget_state_survives_resolver_rebuilds(tmp_path: Path) -> None:
    """Harnesses build a fresh resolver per lookup; the process-wide
    ledger keyed by persona keeps ceilings cumulative across
    PolicyGuardrails instances."""
    from assistant.core.capabilities.resolver import CapabilityResolver
    from assistant.core.persona import PersonaRegistry

    persona_dir = tmp_path / "budgeted"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        textwrap.dedent(
            """
            name: budgeted
            display_name: budgeted
            database: {url_env: ''}
            graphiti: {url_env: ''}
            auth: {provider: custom, config: {}}
            guardrails:
              budgets:
                model_call:
                  daily_usd: 1.0
                  default_call_cost_usd: 0.6
            """
        )
    )
    pc = PersonaRegistry(tmp_path).load("budgeted")

    first = CapabilityResolver().resolve(pc, "sdk", None).guardrails
    second = CapabilityResolver().resolve(pc, "sdk", None).guardrails
    assert first is not second

    assert first.check_action(_request()).allowed
    assert not second.check_action(_request()).allowed


# ── delegation constraints ───────────────────────────────────────────


def test_delegation_denied_sub_role_glob() -> None:
    guardrails = _guardrails(
        {"delegation": {"denied_sub_roles": ["cod*"]}}
    )
    denied = guardrails.check_delegation("chief_of_staff", "coder", "task")
    assert denied.allowed is False
    assert "coder" in denied.reason
    assert guardrails.check_delegation("chief_of_staff", "writer", "task").allowed


def test_delegation_max_task_chars() -> None:
    guardrails = _guardrails({"delegation": {"max_task_chars": 10}})
    assert guardrails.check_delegation("a", "b", "short").allowed
    long_task = guardrails.check_delegation("a", "b", "x" * 11)
    assert long_task.allowed is False


def test_spawner_raises_on_denied_delegation() -> None:
    """Existing check_delegation semantics preserved: the spawner
    raises PermissionError on allowed=False."""
    import asyncio
    from typing import Any, cast

    from assistant.delegation.spawner import DelegationSpawner

    class _Role:
        def __init__(self) -> None:
            self.name = "chief_of_staff"
            self.delegation = {
                "allowed_sub_roles": ["coder"],
                "max_concurrent": 3,
            }

    class _RoleReg:
        def available_for_persona(self, persona: Any) -> list[str]:
            return ["coder"]

        def load(self, name: str, persona: Any) -> Any:  # pragma: no cover
            raise AssertionError("must deny before loading the role")

    class _Persona:
        def __init__(self) -> None:
            self.name = "personal"

    spawner = DelegationSpawner(
        cast(Any, _Persona()),
        cast(Any, _Role()),
        harness=cast(Any, None),
        tools=[],
        extensions=[],
        role_registry=cast(Any, _RoleReg()),
        guardrails=_guardrails(
            {"delegation": {"denied_sub_roles": ["coder"]}}
        ),
    )
    with pytest.raises(PermissionError):
        asyncio.run(spawner.delegate("coder", "do a thing"))


# ── declare_risk ─────────────────────────────────────────────────────


def test_declare_risk_tiers() -> None:
    guardrails = _guardrails(
        {
            "budgets": {"model_call": {"daily_usd": 1.0}},
            "policies": [
                {"action_type": "tool_call", "resource": "gmail.*", "effect": "deny"}
            ],
        }
    )
    assert (
        guardrails.declare_risk(
            _request(action_type="tool_call", resource="gmail.send")
        )
        == RiskLevel.HIGH
    )
    assert guardrails.declare_risk(_request()) == RiskLevel.MEDIUM
    assert (
        guardrails.declare_risk(
            _request(action_type="tool_call", resource="other")
        )
        == RiskLevel.LOW
    )


# ── resolver selection ───────────────────────────────────────────────


def _persona_with(guardrails_yaml: str, tmp_path: Path, name: str):
    from assistant.core.persona import PersonaRegistry

    persona_dir = tmp_path / name
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        textwrap.dedent(
            f"""
            name: {name}
            display_name: {name}
            database: {{url_env: ''}}
            graphiti: {{url_env: ''}}
            auth: {{provider: custom, config: {{}}}}
            """
        )
        + guardrails_yaml
    )
    return PersonaRegistry(tmp_path).load(name)


def test_resolver_selects_policy_guardrails_when_declared(
    tmp_path: Path,
) -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    pc = _persona_with(
        "guardrails:\n  policies:\n"
        "    - {action_type: model_call, effect: deny}\n",
        tmp_path,
        "guarded",
    )
    for harness_type in ("sdk", "host"):
        capabilities = CapabilityResolver().resolve(pc, harness_type, None)
        assert isinstance(capabilities.guardrails, PolicyGuardrails)
        assert not capabilities.guardrails.check_action(_request()).allowed


def test_resolver_defaults_to_allow_all_without_guardrails(
    tmp_path: Path,
) -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    pc = _persona_with("", tmp_path, "unguarded")
    for harness_type in ("sdk", "host"):
        capabilities = CapabilityResolver().resolve(pc, harness_type, None)
        assert isinstance(capabilities.guardrails, AllowAllGuardrails)


def test_resolver_factory_override_preserved(tmp_path: Path) -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    pc = _persona_with(
        "guardrails:\n  policies:\n"
        "    - {action_type: model_call, effect: deny}\n",
        tmp_path,
        "overridden",
    )
    sentinel = AllowAllGuardrails()
    capabilities = CapabilityResolver(
        guardrail_factory=lambda: sentinel
    ).resolve(pc, "sdk", None)
    assert capabilities.guardrails is sentinel
