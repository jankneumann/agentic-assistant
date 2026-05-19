"""Tests for FastAPI web app - Section 5 tasks 5.1-5.8 (incl 5.3b, 5.3c, 5.4b, 5.4c, 5.7b).

Spec scenarios: web-server
Contracts: contracts/openapi/v1.yaml, contracts/events/ag-ui-events.schema.json
Design decisions: D2, D3, D4, D6, D7, D8, D13
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from assistant.harnesses.sdk.events import (
    RunFinished,
    RunStarted,
    TextDelta,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


def _make_run_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _run_started() -> RunStarted:
    import datetime
    return RunStarted(
        run_id=_make_run_id(),
        started_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )


def _run_finished(run_id: str, error: str | None = None) -> RunFinished:
    import datetime
    return RunFinished(
        run_id=run_id,
        finished_at=datetime.datetime.now(datetime.UTC).isoformat(),
        error=error,
    )


def _text_delta(msg_id: str, text: str) -> TextDelta:
    return TextDelta(message_id=msg_id, text=text)


class _FakeHarness:
    """Minimal SdkHarnessAdapter-compatible stub for web tests."""

    def __init__(
        self,
        events: list[Any] | None = None,
        thread_id: str = "thread-test-001",
        raise_after: Exception | None = None,
    ) -> None:
        self._events = events or []
        self._thread_id = thread_id
        self._raise_after = raise_after
        self.astream_invoke_call_count = 0

    @property
    def thread_id(self) -> str:
        return self._thread_id

    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any:
        # Tests don't exercise the agent's behavior — return a sentinel
        # that astream_invoke ignores.
        return object()

    async def astream_invoke(
        self, agent: Any, message: str
    ) -> AsyncIterator[Any]:
        self.astream_invoke_call_count += 1
        for evt in self._events:
            yield evt
        if self._raise_after is not None:
            raise self._raise_after


def _make_simple_harness(thread_id: str = "thread-test-001") -> _FakeHarness:
    """Harness that yields a minimal RunStarted → RunFinished stream."""
    rs = _run_started()
    rf = _run_finished(rs.run_id)
    return _FakeHarness(events=[rs, rf], thread_id=thread_id)


def _make_text_harness(thread_id: str = "thread-test-001") -> _FakeHarness:
    """Harness that yields RunStarted, then 2 TextDelta events, then RunFinished."""
    rs = _run_started()
    td1 = _text_delta("msg-001", "Hello")
    td2 = _text_delta("msg-001", " world")
    rf = _run_finished(rs.run_id)
    return _FakeHarness(events=[rs, td1, td2, rf], thread_id=thread_id)


def _make_error_harness() -> _FakeHarness:
    """Two-phase D8 harness: yields terminal RunFinished(error=…) then re-raises."""
    rs = _run_started()
    rf = _run_finished(rs.run_id, error="RuntimeError")
    harness = _FakeHarness(
        events=[rs, rf],
        raise_after=RuntimeError("quota exceeded"),
    )
    return harness


async def _trivial_agent_factory(harness: Any, pc: Any, rc: Any, persona_reg: Any) -> Any:
    """Test-only agent factory: bypasses tool discovery / capability resolution
    and just calls ``harness.create_agent([], [])`` on the fake.

    Production code uses the default factory in ``assistant.web.app``.
    """
    return await harness.create_agent(tools=[], extensions=[])


def _make_app_with_harness(harness: Any, harness_name: str = "deep_agents"):
    """Build a make_app() result but inject a pre-built harness and a trivial
    agent factory instead of constructing them via the production pipeline.
    Used to avoid persona/role plumbing in unit tests.

    The patches remain active only during construction (factory call site).
    The returned app has the harness pre-wired via the lifespan closure and
    the trivial agent factory injected. Callers must use TestClient as a
    context manager so the lifespan fires.
    """
    from assistant.web.app import make_app

    with (
        patch("assistant.web.app.create_harness") as mock_factory,
        patch("assistant.web.app.PersonaRegistry") as mock_pr,
        patch("assistant.web.app.RoleRegistry") as mock_rr,
    ):
        mock_factory.return_value = harness
        mock_pr.return_value.load.return_value = MagicMock(
            name="personal", default_role="assistant"
        )
        mock_rr.return_value.load.return_value = MagicMock(name="assistant")
        app = make_app(
            "personal", "assistant", harness_name,
            _agent_factory=_trivial_agent_factory,
        )

    return app


def _client(app) -> TestClient:
    """Return a TestClient that has run the lifespan (entered as context manager)."""
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    return client


# ---------------------------------------------------------------------------
# 5.1 — /chat content-type
# ---------------------------------------------------------------------------


def test_chat_returns_text_event_stream():
    """POST /chat must respond with text/event-stream content-type."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# 5.2 — /chat body lifecycle bracketing
# ---------------------------------------------------------------------------


def test_chat_body_contains_run_started_and_run_finished():
    """SSE body must contain RUN_STARTED and RUN_FINISHED events."""
    harness = _make_text_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    types = [e.get("type") for e in events]
    assert "RUN_STARTED" in types
    assert "RUN_FINISHED" in types


def _parse_sse_events(body: str) -> list[dict]:
    """Parse 'data: {...}\n\n' lines into list of dicts."""
    result = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                result.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return result


# ---------------------------------------------------------------------------
# 5.3 — Request validation (422 + RFC 7807)
# ---------------------------------------------------------------------------


def test_missing_message_field_returns_422_problem_json():
    """Malformed body (missing required 'message') → 422 application/problem+json."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={})
    assert resp.status_code == 422
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["type"] == "about:blank"
    assert body["title"] == "Unprocessable Entity"
    assert body["status"] == 422
    assert "detail" in body


def test_non_json_body_returns_422_problem_json():
    """Non-JSON body → 422 application/problem+json."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post(
        "/chat",
        content=b"this is not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert "application/problem+json" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# 5.3b — Message maxLength 32768
# ---------------------------------------------------------------------------


def test_oversize_message_returns_422():
    """Message > 32768 chars → 422 application/problem+json; harness never called."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "x" * 32769})
    assert resp.status_code == 422
    assert "application/problem+json" in resp.headers["content-type"]
    assert harness.astream_invoke_call_count == 0


def test_exactly_max_length_message_is_accepted():
    """Message of exactly 32768 chars must not be rejected."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "x" * 32768})
    assert resp.status_code == 200


def test_empty_message_returns_422():
    """Empty string message (minLength=1) → 422."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 5.4 — Two-phase D8 RUN_ERROR path
# ---------------------------------------------------------------------------


def test_harness_error_emits_run_error_not_run_finished():
    """Two-phase D8: harness yields RunFinished(error=…) then re-raises.
    Response stream must contain exactly one RUN_ERROR; no RUN_FINISHED.
    """
    harness = _make_error_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "trigger error"})
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    types = [e.get("type") for e in events]
    assert types.count("RUN_ERROR") == 1
    assert "RUN_FINISHED" not in types

    run_error = next(e for e in events if e.get("type") == "RUN_ERROR")
    assert run_error["message"] == "RuntimeError"
    assert run_error["code"] == "RuntimeError"


def test_harness_error_no_events_after_run_error():
    """No events emitted after the terminal RUN_ERROR."""
    harness = _make_error_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "trigger error"})
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    run_error_idx = next(
        i for i, e in enumerate(events) if e.get("type") == "RUN_ERROR"
    )
    assert run_error_idx == len(events) - 1, "No events must follow RUN_ERROR"


# ---------------------------------------------------------------------------
# 5.4b — Client disconnect
# ---------------------------------------------------------------------------


def test_client_disconnect_does_not_raise():
    """SSE generator must not raise when the client disconnects early.
    We test this by reading only the first event then closing.
    """
    harness = _make_text_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    # Open a streaming request and close after reading partial data.
    with client.stream("POST", "/chat", json={"message": "hello"}) as response:
        assert response.status_code == 200
        # Read first chunk only.
        for _chunk in response.iter_text():
            break
    # If we reach here without exception, the disconnect was handled cleanly.


# ---------------------------------------------------------------------------
# 5.4c — Empty harness response (lifecycle-only events)
# ---------------------------------------------------------------------------


def test_empty_harness_response_lifecycle_only():
    """Harness yields only RunStarted + RunFinished — stream is well-formed."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "ping"})
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    types = [e.get("type") for e in events]
    # Exactly RUN_STARTED and RUN_FINISHED; nothing in between required.
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"


# ---------------------------------------------------------------------------
# 5.5 — Lifespan single-harness construction
# ---------------------------------------------------------------------------


def test_lifespan_constructs_harness_once():
    """make_app() builds one harness; app.state.harness is set after startup."""
    from assistant.web.app import make_app

    call_count = 0

    def counting_factory(persona, role, harness_name):
        nonlocal call_count
        call_count += 1
        return _make_simple_harness()

    with (
        patch("assistant.web.app.create_harness", side_effect=counting_factory),
        patch("assistant.web.app.PersonaRegistry") as mock_pr,
        patch("assistant.web.app.RoleRegistry") as mock_rr,
    ):
        mock_pr.return_value.load.return_value = MagicMock(
            name="personal", default_role="assistant"
        )
        mock_rr.return_value.load.return_value = MagicMock(name="assistant")
        app = make_app(
            "personal", "assistant", "deep_agents",
            _agent_factory=_trivial_agent_factory,
        )

    client = _client(app)
    # Make two requests; factory called once.
    client.get("/health")
    client.get("/health")
    assert call_count == 1


# ---------------------------------------------------------------------------
# 5.6 — Shared harness instance across requests
# ---------------------------------------------------------------------------


def test_all_requests_share_same_harness_instance():
    """All /chat requests use the exact same harness object (D3/D4)."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)

    # Two chat requests.
    client.post("/chat", json={"message": "first"})
    client.post("/chat", json={"message": "second"})
    # Both calls go to the same harness.
    assert harness.astream_invoke_call_count == 2


# ---------------------------------------------------------------------------
# 5.7 — Lifespan rejects host harnesses
# ---------------------------------------------------------------------------


def test_lifespan_rejects_host_harness():
    """make_app() must raise ValueError when the resolved harness is a HostHarnessAdapter."""
    from assistant.harnesses.host.claude_code import ClaudeCodeHarness
    from assistant.web.app import make_app

    with (
        patch("assistant.web.app.create_harness") as mock_factory,
        patch("assistant.web.app.PersonaRegistry") as mock_pr,
        patch("assistant.web.app.RoleRegistry") as mock_rr,
    ):
        pc = MagicMock(name="personal", default_role="assistant")
        rc = MagicMock(name="assistant")
        mock_pr.return_value.load.return_value = pc
        mock_rr.return_value.load.return_value = rc
        mock_factory.return_value = ClaudeCodeHarness(pc, rc)

        with pytest.raises((ValueError, RuntimeError)):
            app = make_app("personal", "assistant", "claude_code")
            # Force lifespan to run by creating a TestClient
            with TestClient(app):
                pass


# ---------------------------------------------------------------------------
# 5.7b — Lifespan rejects persona with disabled/missing harness config
# ---------------------------------------------------------------------------


def test_lifespan_rejects_disabled_harness():
    """make_app() must reject when factory raises ValueError (harness disabled)."""
    from assistant.web.app import make_app

    with (
        patch("assistant.web.app.create_harness") as mock_factory,
        patch("assistant.web.app.PersonaRegistry") as mock_pr,
        patch("assistant.web.app.RoleRegistry") as mock_rr,
    ):
        mock_pr.return_value.load.return_value = MagicMock(
            name="personal", default_role="assistant"
        )
        mock_rr.return_value.load.return_value = MagicMock(name="assistant")
        mock_factory.side_effect = ValueError("Harness 'ms_agent_framework' is not enabled")

        with pytest.raises((ValueError, RuntimeError)):
            app = make_app("personal", "assistant", "ms_agent_framework")
            with TestClient(app):
                pass


# ---------------------------------------------------------------------------
# 5.8 — /health endpoint
# ---------------------------------------------------------------------------


def test_health_returns_200_with_identity():
    """GET /health returns 200 JSON with persona, role, harness."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness, harness_name="deep_agents")
    client = _client(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persona"] == "personal"
    assert body["role"] == "assistant"
    assert body["harness"] == "deep_agents"


def test_health_does_not_invoke_harness():
    """GET /health must not call astream_invoke."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    client.get("/health")
    assert harness.astream_invoke_call_count == 0


# ---------------------------------------------------------------------------
# 5.9 — Robustness fixes (IMPL_ITERATE round 1)
# ---------------------------------------------------------------------------


def test_chat_sets_no_buffering_headers():
    """SSE response MUST include Cache-Control: no-cache + X-Accel-Buffering: no
    so reverse proxies (nginx, Caddy) don't buffer the stream and break
    real-time delivery for non-loopback deployments."""
    harness = _make_simple_harness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"


def test_misbehaving_harness_raw_raise_yields_run_error():
    """When the harness raises WITHOUT first yielding Phase-1 terminal
    RunFinished(error=...), the route MUST synthesize a terminal RUN_ERROR
    so SSE consumers always see a final event (D8 contract robustness)."""

    class _RawRaiseHarness:
        _thread_id = "thread-raw"
        astream_invoke_call_count = 0

        @property
        def thread_id(self) -> str:
            return self._thread_id

        async def create_agent(self, tools, extensions):
            return object()

        async def astream_invoke(self, agent, message):
            self.astream_invoke_call_count += 1
            yield _run_started()
            # Skip terminal event entirely — raise raw.
            raise RuntimeError("upstream failure")

    harness = _RawRaiseHarness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    resp = client.post("/chat", json={"message": "trigger"})
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    types = [e.get("type") for e in events]
    # Stream must end with RUN_ERROR even though the harness misbehaved.
    assert types[-1] == "RUN_ERROR"
    run_error = events[-1]
    # Class-name redaction (D8): no message body, no traceback.
    assert run_error["message"] == "RuntimeError"
    assert run_error["code"] == "RuntimeError"


def test_agent_is_passed_to_astream_invoke():
    """The route MUST call ``harness.astream_invoke(agent, message)`` with the
    agent that was constructed by the lifespan factory — not call
    ``astream_invoke(message)`` and lose the agent argument (regression guard
    for the IMPL_ITERATE critical bug fix)."""

    captured_args: dict[str, Any] = {}

    class _SignatureRecordingHarness:
        _thread_id = "thread-record"
        astream_invoke_call_count = 0

        @property
        def thread_id(self) -> str:
            return self._thread_id

        async def create_agent(self, tools, extensions):
            return {"sentinel": "agent-from-create_agent"}

        async def astream_invoke(self, agent, message):
            self.astream_invoke_call_count += 1
            captured_args["agent"] = agent
            captured_args["message"] = message
            yield _run_started()
            yield _run_finished("00000000-0000-0000-0000-000000000000")

    harness = _SignatureRecordingHarness()
    app = _make_app_with_harness(harness)
    client = _client(app)
    client.post("/chat", json={"message": "hello"})
    assert captured_args["message"] == "hello"
    assert captured_args["agent"] == {"sentinel": "agent-from-create_agent"}
