"""make_app(enable_a2a=True) integration — A2A mounted alongside AG-UI.

Spec scenarios: a2a-server + web-server (P6 a2a-server change).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from tests.a2a.helpers import (
    FakeHarness,
    fixture_persona,
    fixture_roles,
    rpc_envelope,
    text_events,
    user_message_payload,
)


async def _trivial_agent_factory(
    harness: Any, pc: Any, rc: Any, persona_reg: Any, http_client: Any = None
) -> Any:
    return await harness.create_agent(tools=[], extensions=[])


@contextmanager
def _a2a_client(**make_app_kwargs):
    """Yield (client, created_harnesses) with the harness factory patched
    for the WHOLE client lifetime — A2A session factories run create_harness
    lazily per request, so the patch must outlive app construction."""
    from assistant.web.app import make_app

    created: list[FakeHarness] = []

    def _harness_factory(persona, role, harness_name):
        harness = FakeHarness(events=text_events("ok"))
        created.append(harness)
        return harness

    pc = fixture_persona()
    roles = {r.name: r for r in fixture_roles()}

    with (
        patch("assistant.web.app.create_harness", side_effect=_harness_factory),
        patch("assistant.web.app.PersonaRegistry") as mock_pr,
        patch("assistant.web.app.RoleRegistry") as mock_rr,
    ):
        mock_pr.return_value.load.return_value = pc
        mock_pr.return_value.shutdown_extensions = AsyncMock()
        mock_rr.return_value.load.side_effect = (
            lambda name, persona: roles[name]
        )
        mock_rr.return_value.available_for_persona.return_value = list(roles)
        app = make_app(
            "fixture",
            "coder",
            "deep_agents",
            _agent_factory=_trivial_agent_factory,
            **make_app_kwargs,
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, created


def test_a2a_routes_mounted_alongside_ag_ui():
    with _a2a_client(
        enable_a2a=True, a2a_base_url="http://127.0.0.1:9999"
    ) as (client, _):
        # AG-UI surface still live.
        health = client.get("/health")
        assert health.status_code == 200

        # Agent card reflects the CLI-provided base URL and the roles.
        card = client.get("/.well-known/agent-card.json")
        assert card.status_code == 200
        body = card.json()
        assert body["url"] == "http://127.0.0.1:9999/a2a/v1"
        assert {s["id"] for s in body["skills"]} == {"coder", "researcher"}


def test_a2a_sessions_are_fresh_harnesses_not_the_ag_ui_one():
    with _a2a_client(enable_a2a=True) as (client, created):
        # Startup built exactly one (AG-UI) harness.
        assert len(created) == 1

        resp = client.post(
            "/a2a/v1",
            json=rpc_envelope("message/send", user_message_payload()),
        )
        task = resp.json()["result"]
        assert task["status"]["state"] == "completed"

        # The A2A task ran on a NEW harness (session), not the AG-UI one.
        assert len(created) == 2
        assert created[1].invocations == ["hello"]
        assert created[0].invocations == []
        assert task["contextId"] == created[1].thread_id


def test_a2a_routes_absent_by_default():
    with _a2a_client() as (client, _):
        assert (
            client.get("/.well-known/agent-card.json").status_code == 404
        )
        assert client.post("/a2a/v1", json={}).status_code == 404
