"""A2A inbound bearer-token auth (agent-iam / P25).

Spec: openspec/changes/agent-iam/specs/a2a-server/spec.md.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant.a2a.server import (
    A2A_MESSAGE_STREAM_PATH,
    A2A_RPC_PATH,
    WELL_KNOWN_AGENT_CARD_PATH,
    build_a2a_state,
    register_a2a_routes,
)
from assistant.core.capabilities.credentials import EnvCredentialProvider
from assistant.core.persona import A2AAuthConfig, parse_a2a_auth
from tests.a2a.helpers import (
    fixture_persona,
    fixture_roles,
    make_session_factory,
    rpc_envelope,
    text_events,
    user_message_payload,
)

TOKEN = "sekrit-token"


def _auth_persona(token_env: str = "A2A_TOKEN", token: str | None = TOKEN):
    persona = fixture_persona()
    scoped = {} if token is None else {token_env: token}
    return dataclasses.replace(
        persona,
        a2a_auth=A2AAuthConfig(type="bearer", token_env=token_env),
        credentials=EnvCredentialProvider(scoped=scoped),
    )


def _make_client(persona=None, events=None) -> TestClient:
    app = FastAPI()
    factory, _created = make_session_factory(events)
    app.state.a2a = build_a2a_state(
        persona if persona is not None else fixture_persona(),
        fixture_roles(),
        session_factory=factory,
        base_url="http://127.0.0.1:8765",
    )
    register_a2a_routes(app)
    return TestClient(app, raise_server_exceptions=False)


# ── auth.a2a parsing ───────────────────────────────────────────────────


def test_parse_a2a_auth_none_when_undeclared():
    assert parse_a2a_auth(None) is None
    assert parse_a2a_auth({}) is None


def test_parse_a2a_auth_bearer():
    parsed = parse_a2a_auth({"type": "bearer", "token_env": "A2A_TOKEN"})
    assert parsed == A2AAuthConfig(type="bearer", token_env="A2A_TOKEN")


def test_parse_a2a_auth_type_defaults_to_bearer():
    parsed = parse_a2a_auth({"token_env": "A2A_TOKEN"})
    assert parsed is not None and parsed.type == "bearer"


@pytest.mark.parametrize(
    ("raw", "needle"),
    [
        ({"type": "oauth2", "token_env": "X"}, "oauth2"),
        ({"type": "bearer"}, "token_env"),
        ({"type": "bearer", "token_env": "X", "extra": 1}, "extra"),
        (["bearer"], "mapping"),
    ],
)
def test_parse_a2a_auth_invalid_raises(raw, needle):
    with pytest.raises(ValueError) as exc:
        parse_a2a_auth(raw)
    assert needle in str(exc.value)


# ── startup posture ────────────────────────────────────────────────────


def test_unauthenticated_state_warns_at_startup(caplog):
    with caplog.at_level("WARNING"):
        _make_client()
    assert any(
        "UNAUTHENTICATED" in r.getMessage() for r in caplog.records
    )


def test_declared_but_unresolvable_token_fails_startup():
    persona = _auth_persona(token=None)
    with pytest.raises(ValueError) as exc:
        _make_client(persona)
    assert "A2A_TOKEN" in str(exc.value)


def test_expected_token_excluded_from_state_repr():
    app = FastAPI()
    factory, _ = make_session_factory()
    state = build_a2a_state(
        _auth_persona(),
        fixture_roles(),
        session_factory=factory,
        base_url="http://x",
    )
    del app
    assert TOKEN not in repr(state)


# ── enforcement on the JSON-RPC route ──────────────────────────────────


def test_rpc_without_token_returns_401_with_challenge():
    client = _make_client(_auth_persona())
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/send", user_message_payload()),
    )
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    # HTTP-level failure — no JSON-RPC error envelope.
    assert "jsonrpc" not in resp.json()


def test_rpc_with_wrong_token_returns_401():
    client = _make_client(_auth_persona())
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/send", user_message_payload()),
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_rpc_with_wrong_scheme_returns_401():
    client = _make_client(_auth_persona())
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/send", user_message_payload()),
        headers={"Authorization": f"Basic {TOKEN}"},
    )
    assert resp.status_code == 401


def test_rpc_with_valid_token_succeeds():
    client = _make_client(_auth_persona(), events=text_events("Hi"))
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/send", user_message_payload()),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"]["state"] == "completed"


def test_rest_alias_enforces_the_same_token():
    client = _make_client(_auth_persona(), events=text_events("Hi"))
    denied = client.post(A2A_MESSAGE_STREAM_PATH, json=user_message_payload())
    assert denied.status_code == 401
    allowed = client.post(
        A2A_MESSAGE_STREAM_PATH,
        json=user_message_payload(),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert allowed.status_code == 200
    assert "text/event-stream" in allowed.headers["content-type"]


def test_unauthenticated_server_accepts_without_token():
    client = _make_client(events=text_events("Hi"))
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/send", user_message_payload()),
    )
    assert resp.status_code == 200


# ── agent card advertises the scheme, stays public ─────────────────────


def test_card_advertises_security_schemes_when_auth_configured():
    client = _make_client(_auth_persona())
    resp = client.get(WELL_KNOWN_AGENT_CARD_PATH)
    # The card itself is NOT gated — it is how clients discover auth.
    assert resp.status_code == 200
    card = resp.json()
    assert card["securitySchemes"] == {
        "bearer": {
            "type": "http",
            "scheme": "bearer",
            "description": (
                "Static bearer token; present as "
                "'Authorization: Bearer <token>'."
            ),
        }
    }
    assert card["security"] == [{"bearer": []}]
    # The token (or its ref) never leaks onto the card.
    assert TOKEN not in resp.text
    assert "A2A_TOKEN" not in resp.text


def test_card_omits_security_fields_when_unauthenticated():
    client = _make_client()
    card = client.get(WELL_KNOWN_AGENT_CARD_PATH).json()
    assert "securitySchemes" not in card
    assert "security" not in card
