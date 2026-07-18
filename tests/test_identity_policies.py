"""Identity-aware guardrail policies + delegation-chain attribution.

Spec: openspec/changes/agent-iam/specs/{guardrail-provider,
delegation-spawner}/spec.md.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from assistant.core.capabilities.guardrails import (
    DEFAULT_MAX_CHAIN_DEPTH,
    GuardrailConfigError,
    PolicyGuardrails,
    parse_guardrail_config,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.types import ActionDecision, ActionRequest
from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.spawner import DelegationSpawner
from assistant.harnesses.base import SdkHarnessAdapter
from assistant.telemetry import factory


def _request(
    *,
    action_type: str = "model_call",
    resource: str = "expensive-opus",
    role: str = "researcher",
    identity: AgentIdentity | None = None,
) -> ActionRequest:
    return ActionRequest(
        action_type=action_type,
        resource=resource,
        persona="fixture",
        role=role,
        identity=identity,
    )


# ── Identity-aware policy dimensions ───────────────────────────────────


def test_role_dimension_matches_identity_role():
    config = parse_guardrail_config(
        {
            "policies": [
                {
                    "action_type": "model_call",
                    "role": "research*",
                    "effect": "deny",
                    "reason": "researchers use the local tier",
                }
            ]
        }
    )
    guardrails = PolicyGuardrails(config, persona="fixture")

    denied = guardrails.check_action(
        _request(identity=AgentIdentity(persona="fixture", role="researcher"))
    )
    assert denied.allowed is False
    assert "local tier" in denied.reason

    allowed = guardrails.check_action(
        _request(identity=AgentIdentity(persona="fixture", role="coder"))
    )
    assert allowed.allowed is True


def test_role_dimension_falls_back_to_request_role_without_identity():
    config = parse_guardrail_config(
        {
            "policies": [
                {"action_type": "*", "role": "writer", "effect": "deny"}
            ]
        }
    )
    guardrails = PolicyGuardrails(config, persona="fixture")
    assert guardrails.check_action(_request(role="writer")).allowed is False
    assert guardrails.check_action(_request(role="coder")).allowed is True


def test_min_chain_depth_matches_only_deep_identities():
    config = parse_guardrail_config(
        {
            "policies": [
                {
                    "action_type": "model_call",
                    "min_chain_depth": 2,
                    "effect": "deny",
                    "reason": "no model calls below two delegation hops",
                }
            ]
        }
    )
    guardrails = PolicyGuardrails(config, persona="fixture")

    deep = AgentIdentity(
        persona="fixture", role="writer", delegation_chain=("root", "coder")
    )
    shallow = AgentIdentity(
        persona="fixture", role="coder", delegation_chain=("root",)
    )
    assert guardrails.check_action(_request(identity=deep)).allowed is False
    assert guardrails.check_action(_request(identity=shallow)).allowed is True
    # Depth cannot be established without an identity → policy skipped.
    assert guardrails.check_action(_request(identity=None)).allowed is True


def test_identity_dimensions_are_additive_to_resource_globs():
    config = parse_guardrail_config(
        {
            "policies": [
                {
                    "action_type": "model_call",
                    "resource": "expensive-*",
                    "role": "researcher",
                    "effect": "deny",
                }
            ]
        }
    )
    guardrails = PolicyGuardrails(config, persona="fixture")
    identity = AgentIdentity(persona="fixture", role="researcher")
    assert (
        guardrails.check_action(
            _request(resource="expensive-opus", identity=identity)
        ).allowed
        is False
    )
    # Same identity, non-matching resource → allowed.
    assert (
        guardrails.check_action(
            _request(resource="cheap-local", identity=identity)
        ).allowed
        is True
    )


@pytest.mark.parametrize(
    ("policy", "needle"),
    [
        ({"action_type": "x", "role": ""}, "role"),
        ({"action_type": "x", "min_chain_depth": -1}, "min_chain_depth"),
        ({"action_type": "x", "surprise": 1}, "surprise"),
    ],
)
def test_invalid_identity_policy_fields_fail_parse(policy, needle):
    with pytest.raises(GuardrailConfigError) as exc:
        parse_guardrail_config({"policies": [policy]})
    assert needle in str(exc.value)


# ── delegation.max_chain_depth parsing ─────────────────────────────────


def test_max_chain_depth_defaults_to_five():
    config = parse_guardrail_config({})
    assert config.delegation.max_chain_depth == DEFAULT_MAX_CHAIN_DEPTH == 5


def test_max_chain_depth_configurable_and_validated():
    config = parse_guardrail_config(
        {"delegation": {"max_chain_depth": 2}}
    )
    assert config.delegation.max_chain_depth == 2
    with pytest.raises(GuardrailConfigError):
        parse_guardrail_config({"delegation": {"max_chain_depth": -3}})


def test_default_config_stays_falsy_so_allow_all_selection_unchanged():
    # The max_chain_depth default must NOT flip personas without a
    # guardrails: section onto PolicyGuardrails.
    assert not parse_guardrail_config({})
    assert not parse_guardrail_config(None)


# ── Spawner chain attribution + depth enforcement ──────────────────────


class _RecordingHarness(SdkHarnessAdapter):
    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        super().__init__(persona, role)
        self.spawn_calls: list[tuple[str, str]] = []

    def name(self) -> str:
        return "fake"

    async def create_agent(self, tools, extensions):
        return object()

    async def invoke(self, agent, message) -> str:
        return "ok"

    async def spawn_sub_agent(
        self, role, task, tools, extensions, context=None
    ) -> str:
        self.spawn_calls.append((role.name, task))
        return "ok"


class _SpanSpy:
    name = "spy"

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict]] = []

    def start_span(self, name, attributes=None):
        self.spans.append((name, dict(attributes or {})))
        from contextlib import nullcontext

        return nullcontext()

    def trace_delegation(self, **kwargs):
        # @traced_delegation reaches the provider too; accept silently.
        return None


@pytest.fixture
def span_spy(monkeypatch: pytest.MonkeyPatch) -> _SpanSpy:
    spy = _SpanSpy()
    monkeypatch.setattr(factory, "_provider", spy)
    return spy


@pytest.fixture
def personal(personas_dir: Path) -> PersonaConfig:
    return PersonaRegistry(personas_dir).load("personal")


@pytest.fixture
def researcher_parent(
    roles_dir: Path, personas_dir: Path, personal: PersonaConfig
) -> RoleConfig:
    return RoleRegistry(roles_dir, personas_dir).load("researcher", personal)


def _spawner(
    personal: PersonaConfig,
    researcher_parent: RoleConfig,
    roles_dir: Path,
    personas_dir: Path,
    *,
    identity: AgentIdentity | None = None,
) -> tuple[DelegationSpawner, _RecordingHarness]:
    harness = _RecordingHarness(personal, researcher_parent)
    spawner = DelegationSpawner(
        personal,
        researcher_parent,
        harness,
        tools=[],
        extensions=[],
        role_registry=RoleRegistry(roles_dir, personas_dir),
        identity=identity,
    )
    return spawner, harness


def test_spawner_synthesizes_root_identity(
    personal, researcher_parent, roles_dir, personas_dir
):
    spawner, _ = _spawner(
        personal, researcher_parent, roles_dir, personas_dir
    )
    assert spawner.identity.persona == personal.name
    assert spawner.identity.role == "researcher"
    assert spawner.identity.delegation_chain == ()


def test_delegation_within_depth_proceeds_and_audits_chain(
    personal, researcher_parent, roles_dir, personas_dir, span_spy
):
    spawner, harness = _spawner(
        personal, researcher_parent, roles_dir, personas_dir
    )
    result = asyncio.run(spawner.delegate("writer", "draft it"))
    assert result == "ok"
    assert harness.spawn_calls == [("writer", "draft it")]

    audits = [
        attrs
        for name, attrs in span_spy.spans
        if name == "guardrail.decision"
    ]
    assert len(audits) == 1
    assert audits[0]["action_type"] == "delegation"
    assert audits[0]["resource"] == "writer"
    assert audits[0]["decision"] == "allow"
    assert audits[0]["delegation_chain"] == []
    assert audits[0]["role"] == "researcher"


def test_chain_depth_ceiling_denies_with_chain_in_reason(
    personal, researcher_parent, roles_dir, personas_dir, span_spy
):
    # Parent already sits at the default ceiling (depth 5): one more
    # hop would make the child chain depth 6 > 5.
    deep_identity = AgentIdentity(
        persona=personal.name,
        role="researcher",
        delegation_chain=("a", "b", "c", "d", "e")[:5],
    )
    spawner, harness = _spawner(
        personal,
        researcher_parent,
        roles_dir,
        personas_dir,
        identity=deep_identity,
    )
    with pytest.raises(PermissionError) as exc:
        asyncio.run(spawner.delegate("writer", "too deep"))
    assert "max_chain_depth" in str(exc.value)
    assert "researcher -> writer" in str(exc.value)
    assert harness.spawn_calls == []

    audits = [
        attrs
        for name, attrs in span_spy.spans
        if name == "guardrail.decision"
    ]
    assert len(audits) == 1
    assert audits[0]["decision"] == "deny"


def test_chain_extends_hop_by_hop(
    personal, researcher_parent, roles_dir, personas_dir
):
    # Simulate two hops by re-injecting the child identity, as a
    # nested spawner would receive it.
    spawner1, _ = _spawner(
        personal, researcher_parent, roles_dir, personas_dir
    )
    child = spawner1.identity.delegate_to("coder")
    spawner2, _ = _spawner(
        personal,
        researcher_parent,
        roles_dir,
        personas_dir,
        identity=child,
    )
    grandchild = spawner2.identity.delegate_to("writer")
    assert grandchild.delegation_chain == ("researcher", "coder")
    assert grandchild.chain_depth == 2


def test_guardrail_denial_still_audited(
    personal, researcher_parent, roles_dir, personas_dir, span_spy
):
    class _DenyAll:
        def check_action(self, action):
            return ActionDecision(allowed=True)

        def check_delegation(self, parent_role, sub_role, task):
            return ActionDecision(allowed=False, reason="nope")

        def declare_risk(self, action):
            from assistant.core.capabilities.types import RiskLevel

            return RiskLevel.LOW

    harness = _RecordingHarness(personal, researcher_parent)
    spawner = DelegationSpawner(
        personal,
        researcher_parent,
        harness,
        tools=[],
        extensions=[],
        role_registry=RoleRegistry(roles_dir, personas_dir),
        guardrails=_DenyAll(),
    )
    with pytest.raises(PermissionError, match="nope"):
        asyncio.run(spawner.delegate("writer", "x"))
    audits = [
        attrs
        for name, attrs in span_spy.spans
        if name == "guardrail.decision"
    ]
    assert len(audits) == 1
    assert audits[0]["decision"] == "deny"
    assert audits[0]["reason"] == "nope"
