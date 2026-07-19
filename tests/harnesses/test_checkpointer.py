"""Durable checkpointer seam (P30) — DeepAgents harness injection +
persona-config resolution. Checkpointer interactions are faked; no
Postgres exists in the public suite.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from assistant.core.durable import SessionsConfig
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.sdk import checkpointer as cp
from assistant.harnesses.sdk.deep_agents import DeepAgentsHarness


def _persona(sessions: SessionsConfig | None = None, database_url: str = "") -> PersonaConfig:
    return PersonaConfig(
        name="fixture",
        display_name="Fixture",
        database_url=database_url,
        graphiti_url="",
        auth_provider="none",
        auth_config={},
        harnesses={"deep_agents": {"enabled": True}},
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
        sessions=sessions or SessionsConfig(),
    )


def _role() -> RoleConfig:
    return RoleConfig(
        name="coder", display_name="Coder", description="", prompt="p"
    )


@pytest.fixture(autouse=True)
def _clean_saver_cache():
    from assistant.core import durable

    cp._clear_checkpointer_cache()
    durable._clear_durable_state()
    yield
    cp._clear_checkpointer_cache()
    durable._clear_durable_state()


class TestResolveCheckpointer:
    def test_non_durable_persona_gets_in_memory_saver(self):
        saver = asyncio.run(cp.resolve_checkpointer(_persona()))
        assert isinstance(saver, InMemorySaver)

    def test_each_resolution_gets_a_fresh_in_memory_saver(self):
        a = asyncio.run(cp.resolve_checkpointer(_persona()))
        b = asyncio.run(cp.resolve_checkpointer(_persona()))
        assert a is not b

    def test_durable_without_url_raises_actionable_error(self):
        persona = _persona(sessions=SessionsConfig(durable=True))
        with pytest.raises(ValueError, match="database"):
            asyncio.run(cp.resolve_checkpointer(persona))

    def test_durable_persona_builds_and_caches_the_saver(self):
        fake_saver = MagicMock(name="AsyncPostgresSaver")

        async def _fake_build(url: str):
            return fake_saver

        persona = _persona(
            sessions=SessionsConfig(durable=True),
            database_url="postgresql://u@h/db",
        )
        with patch.object(
            cp, "_build_durable_saver", side_effect=_fake_build
        ) as build_mock:
            first = asyncio.run(cp.resolve_checkpointer(persona))
            second = asyncio.run(cp.resolve_checkpointer(persona))
        assert first is fake_saver
        assert second is fake_saver
        build_mock.assert_called_once_with("postgresql://u@h/db")

    def test_psycopg_conn_string_strips_driver_suffix(self):
        assert (
            cp._psycopg_conn_string("postgresql+asyncpg://u@h/db")
            == "postgresql://u@h/db"
        )
        assert (
            cp._psycopg_conn_string("postgresql://u@h/db")
            == "postgresql://u@h/db"
        )


class TestHarnessCheckpointerInjection:
    def _create(self, harness: DeepAgentsHarness):
        with patch(
            "assistant.harnesses.sdk.deep_agents.init_chat_model",
            return_value=MagicMock(),
        ), patch(
            "assistant.harnesses.sdk.deep_agents.create_deep_agent"
        ) as cda_mock:
            cda_mock.return_value = MagicMock(name="agent")
            asyncio.run(harness.create_agent(tools=[], extensions=[]))
            return cda_mock.call_args.kwargs

    def test_injected_checkpointer_reaches_create_deep_agent(self):
        sentinel = MagicMock(name="injected-checkpointer")
        h = DeepAgentsHarness(_persona(), _role(), checkpointer=sentinel)
        kwargs = self._create(h)
        assert kwargs["checkpointer"] is sentinel

    def test_default_stays_in_memory_saver(self):
        h = DeepAgentsHarness(_persona(), _role())
        kwargs = self._create(h)
        assert isinstance(kwargs["checkpointer"], InMemorySaver)

    def test_durable_persona_resolves_the_durable_saver(self):
        fake_saver = MagicMock(name="durable-saver")

        async def _fake_resolve(persona):
            return fake_saver

        # asyncpg-flavored url: the resolver's memory-policy branch also
        # sees database_url and builds a (lazy, never-connected) async
        # engine — keep it on the installed asyncpg dialect.
        persona = _persona(
            sessions=SessionsConfig(durable=True),
            database_url="postgresql+asyncpg://u@h/db",
        )
        h = DeepAgentsHarness(persona, _role())
        with patch(
            "assistant.harnesses.sdk.deep_agents.resolve_checkpointer",
            side_effect=_fake_resolve,
        ):
            kwargs = self._create(h)
        assert kwargs["checkpointer"] is fake_saver

    def test_explicit_thread_id_rebinds_the_conversation(self):
        h = DeepAgentsHarness(_persona(), _role(), thread_id="resume-me")
        assert h.thread_id == "resume-me"

    def test_default_thread_id_is_synthesized_and_stable(self):
        h = DeepAgentsHarness(_persona(), _role())
        assert h.thread_id
        assert h.thread_id == h.thread_id

    def test_spawn_propagates_injected_checkpointer(self):
        sentinel = MagicMock(name="shared-checkpointer")
        h = DeepAgentsHarness(_persona(), _role(), checkpointer=sentinel)
        assert h._checkpointer is sentinel
