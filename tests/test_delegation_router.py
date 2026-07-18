"""Tests for the P12 delegation router (intent classification).

Covers deterministic scoring, the binding-gated model-assisted path
(mocked invoker — no real model calls), fallback-to-deterministic on
model failure or garbage replies, and ``DelegationSpawner.delegate_auto``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from assistant.core.capabilities.models import ModelRef, ModelRegistry
from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.router import (
    DelegationRouter,
    RoutingError,
    score_role,
)
from assistant.delegation.spawner import DelegationSpawner
from assistant.harnesses.base import SdkHarnessAdapter


def _role(
    name: str,
    description: str = "",
    preferred_tools: list[str] | None = None,
) -> RoleConfig:
    return RoleConfig(
        name=name,
        display_name=name.title(),
        description=description,
        prompt="p",
        preferred_tools=preferred_tools or [],
        delegation={},
    )


def _persona(router_bound: bool = False) -> PersonaConfig:
    models = ModelRegistry()
    if router_bound:
        ref = ModelRef(name="cheap", dialect="openai-compatible")
        models = ModelRegistry(
            entries={"cheap": ref},
            fallbacks={"cheap": []},
            bindings={"router": "cheap", "default": "cheap"},
        )
    return PersonaConfig(
        name="p",
        display_name="P",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={"deep_agents": {"enabled": True}},
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
        models=models,
    )


_WRITER = _role(
    "writer",
    "Draft and edit emails, documents, and prose",
    ["gmail:send_email", "gdrive:create_document"],
)
_CODER = _role(
    "coder",
    "Write and debug code, run tests, fix bugs",
    ["github:create_pull_request"],
)
_RESEARCHER = _role(
    "researcher",
    "Deep research and analysis with source synthesis",
    ["content_analyzer:search"],
)

_CANDIDATES = [_WRITER, _CODER, _RESEARCHER]


# ── Deterministic scoring ────────────────────────────────────────────


def test_score_role_matches_description_tokens() -> None:
    assert score_role("please debug the failing tests", _CODER) > 0
    assert score_role("please debug the failing tests", _WRITER) == 0


def test_score_role_weights_name_hits_highest() -> None:
    name_hit = score_role("ask the coder", _CODER)
    description_hit = score_role("debug something", _CODER)
    assert name_hit > description_hit


def test_score_role_matches_preferred_tool_tokens() -> None:
    # "gmail" appears only in the writer's preferred_tools source.
    assert score_role("send it via gmail", _WRITER) > 0
    assert score_role("send it via gmail", _CODER) == 0


def test_deterministic_route_picks_best_match() -> None:
    router = DelegationRouter(_persona())
    decision = asyncio.run(
        router.route("debug the code and fix the bugs", _CANDIDATES)
    )
    assert decision.sub_role == "coder"
    assert decision.method == "deterministic"
    assert decision.scores["coder"] > decision.scores["writer"]


def test_deterministic_route_tie_breaks_by_candidate_order() -> None:
    router = DelegationRouter(_persona())
    a = _role("alpha", "handle the frobnicate request")
    b = _role("beta", "handle the frobnicate request")
    decision = asyncio.run(router.route("frobnicate request", [a, b]))
    assert decision.sub_role == "alpha"


def test_route_with_no_signal_raises_routing_error() -> None:
    router = DelegationRouter(_persona())
    with pytest.raises(RoutingError) as exc:
        asyncio.run(router.route("zzz qqq xyzzy", _CANDIDATES))
    assert "scores" in str(exc.value)


def test_route_with_no_candidates_raises() -> None:
    router = DelegationRouter(_persona())
    with pytest.raises(RoutingError):
        asyncio.run(router.route("anything", []))


# ── Model-assisted path (binding-gated) ──────────────────────────────


def test_model_path_used_when_router_binding_present() -> None:
    calls: list[str] = []

    async def invoker(prompt: str) -> str:
        calls.append(prompt)
        return "researcher"

    router = DelegationRouter(
        _persona(router_bound=True), model_invoker=invoker
    )
    decision = asyncio.run(
        router.route("debug the code and fix the bugs", _CANDIDATES)
    )
    # The model's pick wins even though deterministic scoring says coder.
    assert decision.sub_role == "researcher"
    assert decision.method == "model"
    assert len(calls) == 1
    # The prompt names every candidate.
    for role in _CANDIDATES:
        assert role.name in calls[0]


def test_model_path_off_without_binding_even_with_invoker() -> None:
    """The explicit ``router`` binding is the ONLY gate — an injected
    invoker alone must never enable model-assisted classification."""
    calls: list[str] = []

    async def invoker(prompt: str) -> str:
        calls.append(prompt)
        return "researcher"

    router = DelegationRouter(_persona(), model_invoker=invoker)
    decision = asyncio.run(router.route("debug the code", _CANDIDATES))
    assert decision.method == "deterministic"
    assert decision.sub_role == "coder"
    assert calls == []


def test_default_binding_does_not_enable_model_path() -> None:
    persona = _persona(router_bound=True)
    persona.models.bindings.pop("router")  # leaves only `default`
    router = DelegationRouter(persona, model_invoker=None)
    assert router.model_routing_enabled() is False


def test_model_failure_falls_back_to_deterministic() -> None:
    async def invoker(prompt: str) -> str:
        raise ConnectionError("model down")

    router = DelegationRouter(
        _persona(router_bound=True), model_invoker=invoker
    )
    decision = asyncio.run(router.route("debug the code", _CANDIDATES))
    assert decision.method == "deterministic"
    assert decision.sub_role == "coder"


def test_garbage_model_reply_falls_back_to_deterministic() -> None:
    async def invoker(prompt: str) -> str:
        return "I think you should try the planner role!"  # not a candidate

    router = DelegationRouter(
        _persona(router_bound=True), model_invoker=invoker
    )
    decision = asyncio.run(router.route("debug the code", _CANDIDATES))
    assert decision.method == "deterministic"
    assert decision.sub_role == "coder"


def test_model_reply_substring_match_accepted() -> None:
    async def invoker(prompt: str) -> str:
        return "The best role is `writer`."

    router = DelegationRouter(
        _persona(router_bound=True), model_invoker=invoker
    )
    decision = asyncio.run(router.route("debug the code", _CANDIDATES))
    assert decision.sub_role == "writer"
    assert decision.method == "model"


# ── delegate_auto integration ────────────────────────────────────────


class _FakeHarness(SdkHarnessAdapter):
    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        super().__init__(persona, role)
        self.spawn_calls: list[tuple[str, str]] = []

    def name(self) -> str:
        return "fake"

    async def create_agent(self, tools, extensions) -> Any:
        return object()

    async def invoke(self, agent, message) -> str:
        return "ok"

    async def spawn_sub_agent(
        self, role, task, tools, extensions, context=None
    ) -> str:
        self.spawn_calls.append((role.name, task))
        return "ok"


class _NullPolicy:
    def resolve(self, persona, harness_name):  # pragma: no cover
        raise NotImplementedError

    def export_memory_context(self, persona) -> str:
        return ""

    async def get_recent_snippets(self, persona, role, *, limit=10):
        return []

    async def record_interaction(self, persona, role, *, user_message, response):
        return None


def test_delegate_auto_routes_and_delegates(
    roles_dir: Path, personas_dir: Path
) -> None:
    personal = PersonaRegistry(personas_dir).load("personal")
    registry = RoleRegistry(roles_dir, personas_dir)
    parent = registry.load("researcher", personal)  # allows writer+coder
    harness = _FakeHarness(personal, parent)
    spawner = DelegationSpawner(
        personal,
        parent,
        harness,
        tools=[],
        extensions=[],
        role_registry=registry,
        memory_policy=_NullPolicy(),
    )
    result = asyncio.run(
        spawner.delegate_auto("write and edit a short story draft")
    )
    assert result == "ok"
    assert harness.spawn_calls == [
        ("writer", "write and edit a short story draft")
    ]


def test_delegate_auto_unroutable_task_raises(
    roles_dir: Path, personas_dir: Path
) -> None:
    personal = PersonaRegistry(personas_dir).load("personal")
    registry = RoleRegistry(roles_dir, personas_dir)
    parent = registry.load("researcher", personal)
    spawner = DelegationSpawner(
        personal,
        parent,
        _FakeHarness(personal, parent),
        tools=[],
        extensions=[],
        role_registry=registry,
        memory_policy=_NullPolicy(),
    )
    with pytest.raises(RoutingError):
        asyncio.run(spawner.delegate_auto("xyzzy plugh"))


def test_delegate_auto_no_candidates_raises(
    roles_dir: Path, personas_dir: Path
) -> None:
    personal = PersonaRegistry(personas_dir).load("personal")
    registry = RoleRegistry(roles_dir, personas_dir)
    parent = registry.load("researcher", personal)
    parent.delegation["allowed_sub_roles"] = []
    spawner = DelegationSpawner(
        personal,
        parent,
        _FakeHarness(personal, parent),
        tools=[],
        extensions=[],
        role_registry=registry,
        memory_policy=_NullPolicy(),
    )
    with pytest.raises(ValueError, match="no available"):
        asyncio.run(spawner.delegate_auto("anything"))
