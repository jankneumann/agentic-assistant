"""A2A server route tests — agent-card GET, JSON-RPC envelope, SSE streams.

Spec scenarios: a2a-server (openspec/changes/a2a-server).
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant.a2a.server import (
    A2A_MESSAGE_STREAM_PATH,
    A2A_RPC_PATH,
    WELL_KNOWN_AGENT_CARD_PATH,
    WELL_KNOWN_AGENT_JSON_PATH,
    build_a2a_state,
    register_a2a_routes,
)
from assistant.a2a.types import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
)
from tests.a2a.helpers import (
    error_events,
    fixture_persona,
    fixture_roles,
    make_session_factory,
    rpc_envelope,
    text_events,
    user_message_payload,
)


def _make_client(events=None) -> tuple[TestClient, list]:
    app = FastAPI()
    factory, created = make_session_factory(events)
    app.state.a2a = build_a2a_state(
        fixture_persona(),
        fixture_roles(),
        session_factory=factory,
        base_url="http://127.0.0.1:8765",
    )
    register_a2a_routes(app)
    return TestClient(app, raise_server_exceptions=False), created


def _parse_sse(body: str) -> list[dict]:
    out = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:"):].strip()))
    return out


# ---------------------------------------------------------------------------
# Agent card routes
# ---------------------------------------------------------------------------


def test_agent_card_served_at_canonical_well_known_path():
    client, _ = _make_client()
    resp = client.get(WELL_KNOWN_AGENT_CARD_PATH)
    assert resp.status_code == 200
    card = resp.json()
    assert card["protocolVersion"]
    assert card["capabilities"]["streaming"] is True
    assert [s["id"] for s in card["skills"]] == ["coder", "researcher"]


def test_agent_card_served_at_legacy_agent_json_path():
    client, _ = _make_client()
    canonical = client.get(WELL_KNOWN_AGENT_CARD_PATH).json()
    legacy = client.get(WELL_KNOWN_AGENT_JSON_PATH)
    assert legacy.status_code == 200
    assert legacy.json() == canonical


# ---------------------------------------------------------------------------
# JSON-RPC envelope validation
# ---------------------------------------------------------------------------


def test_invalid_json_returns_parse_error():
    client, _ = _make_client()
    resp = client.post(
        A2A_RPC_PATH,
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"]["code"] == PARSE_ERROR


def test_missing_method_returns_invalid_request():
    client, _ = _make_client()
    resp = client.post(A2A_RPC_PATH, json={"jsonrpc": "2.0", "id": "1"})
    assert resp.json()["error"]["code"] == INVALID_REQUEST


def test_wrong_jsonrpc_version_returns_invalid_request():
    client, _ = _make_client()
    resp = client.post(
        A2A_RPC_PATH,
        json={"jsonrpc": "1.0", "id": "1", "method": "message/send"},
    )
    assert resp.json()["error"]["code"] == INVALID_REQUEST


def test_unknown_method_returns_method_not_found():
    client, _ = _make_client()
    resp = client.post(
        A2A_RPC_PATH, json=rpc_envelope("tasks/cancel", {})
    )
    body = resp.json()
    assert body["error"]["code"] == METHOD_NOT_FOUND
    assert body["id"] == "req-1"


def test_malformed_params_returns_invalid_params():
    client, _ = _make_client()
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/send", {"message": {"role": "user"}}),
    )
    assert resp.json()["error"]["code"] == INVALID_PARAMS


# ---------------------------------------------------------------------------
# message/send
# ---------------------------------------------------------------------------


def test_message_send_happy_path_returns_completed_task():
    client, created = _make_client(text_events("Hello", " world"))
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/send", user_message_payload("do a thing")),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == "req-1"
    task = body["result"]
    assert task["kind"] == "task"
    assert task["status"]["state"] == "completed"
    assert task["contextId"] == created[0].thread_id
    texts = [
        p["text"]
        for a in task["artifacts"]
        for p in a["parts"]
        if p["kind"] == "text"
    ]
    assert "".join(texts) == "Hello world"
    assert created[0].invocations == ["do a thing"]


def test_message_send_unknown_context_returns_jsonrpc_error():
    client, _ = _make_client()
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope(
            "message/send", user_message_payload(context_id="ghost")
        ),
    )
    assert resp.json()["error"]["code"] == INVALID_PARAMS


def test_multi_task_multiplexing_over_json_rpc():
    """Two sends without contextId → two sessions; reusing a contextId
    routes onto the same session."""
    client, created = _make_client()
    t1 = client.post(
        A2A_RPC_PATH, json=rpc_envelope("message/send", user_message_payload())
    ).json()["result"]
    t2 = client.post(
        A2A_RPC_PATH, json=rpc_envelope("message/send", user_message_payload())
    ).json()["result"]
    assert t1["contextId"] != t2["contextId"]
    assert len(created) == 2

    t3 = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope(
            "message/send",
            user_message_payload("again", context_id=t1["contextId"]),
        ),
    ).json()["result"]
    assert t3["contextId"] == t1["contextId"]
    assert len(created) == 2
    assert created[0].invocations == ["hello", "again"]


# ---------------------------------------------------------------------------
# message/stream (SSE)
# ---------------------------------------------------------------------------


def test_message_stream_sse_event_sequence():
    client, _ = _make_client(text_events("Hi"))
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/stream", user_message_payload()),
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    frames = _parse_sse(resp.text)
    # Every frame is a JSON-RPC envelope with the request id.
    assert all(f["jsonrpc"] == "2.0" and f["id"] == "req-1" for f in frames)
    results = [f["result"] for f in frames]
    assert results[0]["kind"] == "task"
    assert results[0]["status"]["state"] == "submitted"
    kinds_states = [
        (r["kind"], r.get("status", {}).get("state")) for r in results
    ]
    assert ("status-update", "working") in kinds_states
    assert any(r["kind"] == "artifact-update" for r in results)
    assert results[-1]["kind"] == "status-update"
    assert results[-1]["status"]["state"] == "completed"
    assert results[-1]["final"] is True


def test_message_stream_two_phase_error_ends_with_final_failed():
    client, _ = _make_client(error_events("RuntimeError"))
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/stream", user_message_payload()),
    )
    results = [f["result"] for f in _parse_sse(resp.text)]
    terminal = results[-1]
    assert terminal["kind"] == "status-update"
    assert terminal["status"]["state"] == "failed"
    assert terminal["final"] is True
    # Class-name-only redaction survives the wire.
    failure_text = terminal["status"]["message"]["parts"][0]["text"]
    assert failure_text == "RuntimeError"
    # No completed state anywhere in the failed stream.
    assert all(
        r.get("status", {}).get("state") != "completed" for r in results
    )


def test_message_stream_approval_denial_surfaces_input_required():
    client, _ = _make_client(error_events("ModelCallDeniedError"))
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope("message/stream", user_message_payload()),
    )
    results = [f["result"] for f in _parse_sse(resp.text)]
    states = [
        r["status"]["state"]
        for r in results
        if r["kind"] == "status-update"
    ]
    assert "input-required" in states
    assert states[-1] == "failed"


def test_message_stream_protocol_error_emits_jsonrpc_error_frame():
    client, _ = _make_client()
    resp = client.post(
        A2A_RPC_PATH,
        json=rpc_envelope(
            "message/stream", user_message_payload(context_id="ghost")
        ),
    )
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert len(frames) == 1
    assert frames[0]["error"]["code"] == INVALID_PARAMS


# ---------------------------------------------------------------------------
# REST-style alias
# ---------------------------------------------------------------------------


def test_rest_message_stream_alias_emits_bare_events():
    client, _ = _make_client(text_events("Hi"))
    resp = client.post(
        A2A_MESSAGE_STREAM_PATH, json=user_message_payload()
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    events = _parse_sse(resp.text)
    # Bare A2A objects — no JSON-RPC envelope.
    assert all("jsonrpc" not in e for e in events)
    assert events[0]["kind"] == "task"
    assert events[-1]["kind"] == "status-update"
    assert events[-1]["final"] is True


def test_rest_message_stream_alias_validates_body():
    client, _ = _make_client()
    resp = client.post(A2A_MESSAGE_STREAM_PATH, json={"nope": True})
    assert resp.status_code == 422
