"""End-to-end smoke tests for the AG-UI bridge (tasks 7.1, 7.2 — automated parity).

The manual operator runbook for these scenarios lives in CLAUDE.md
"Essential Commands" — start the server with ``uv run assistant serve``
then ``curl -N`` against ``/chat``. These automated equivalents drive
the same FastAPI app through TestClient so CI exercises the full SSE
pipeline (request validation, harness streaming, AG-UI emitter,
sse-starlette framing) without needing a live network LLM call.

Two scenarios:

- **text role** (task 7.1): fake harness emits RunStarted → TextDelta
  → RunFinished. Asserts the SSE body contains a well-formed
  lifecycle bracket plus the TEXT_MESSAGE_* events the mapper
  produces from the text deltas.
- **tool-using role** (task 7.2): fake harness emits RunStarted →
  ToolCallStart/Args/End → RunFinished. Asserts the SSE body emits
  TOOL_CALL_* events in the correct order.

These run in the default ``pytest tests/`` sweep because they have no
external dependencies — the FastAPI app is real, but the harness is a
local in-process fake. The only thing they don't cover is the actual
LLM/tool execution path (which is what the manual curl tests are for).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from assistant.harnesses.sdk.events import (
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class _FakeHarness:
    """Minimal SdkHarnessAdapter fake — yields a fixed HarnessEvent sequence."""

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self._thread_id = "smoke-thread"

    @property
    def thread_id(self) -> str:
        return self._thread_id

    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any:
        return object()

    async def astream_invoke(
        self, agent: Any, message: str
    ) -> Any:
        for evt in self._events:
            yield evt


async def _trivial_agent_factory(
    harness: Any,
    pc: Any,
    rc: Any,
    persona_reg: Any,
    http_client: Any = None,
) -> Any:
    return await harness.create_agent(tools=[], extensions=[])


def _make_app(harness: _FakeHarness):
    """Build the real FastAPI app with a fake harness injected."""
    from assistant.web.app import make_app

    with (
        patch("assistant.web.app.create_harness") as mock_factory,
        patch("assistant.web.app.PersonaRegistry") as mock_pr,
        patch("assistant.web.app.RoleRegistry") as mock_rr,
    ):
        mock_factory.return_value = harness
        mock_pr.return_value.load.return_value = MagicMock(
            name="personal", default_role="coder"
        )
        mock_rr.return_value.load.return_value = MagicMock(name="coder")
        return make_app(
            "personal", "coder", "deep_agents",
            _agent_factory=_trivial_agent_factory,
        )


def _parse_sse(body: str) -> list[dict]:
    out: list[dict] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                out.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return out


def test_smoke_text_role_full_lifecycle() -> None:
    run_id = str(uuid4())
    msg_id = str(uuid4())
    events = [
        RunStarted(run_id=run_id, started_at=_now_iso()),
        TextDelta(message_id=msg_id, text="Hello"),
        TextDelta(message_id=msg_id, text=", world!"),
        RunFinished(run_id=run_id, finished_at=_now_iso()),
    ]
    harness = _FakeHarness(events)
    app = _make_app(harness)

    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    resp = client.post("/chat", json={"message": "hello"})

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    # Falls through; client.__enter__ left open intentionally to avoid
    # sse_starlette's module-level AppStatus.should_exit_event racing
    # across the per-test event loops — same pattern as tests/web/test_app.py.

    parsed = _parse_sse(resp.text)
    types = [e.get("type") for e in parsed]
    assert types, f"expected at least one SSE event, got body: {resp.text!r}"
    assert types[0] == "RUN_STARTED", f"first event must be RUN_STARTED, got {types}"
    assert types[-1] == "RUN_FINISHED", f"last event must be RUN_FINISHED, got {types}"
    assert "TEXT_MESSAGE_START" in types
    assert "TEXT_MESSAGE_CONTENT" in types
    assert "TEXT_MESSAGE_END" in types
    assert types.index("TEXT_MESSAGE_START") < types.index("TEXT_MESSAGE_CONTENT")
    assert types.index("TEXT_MESSAGE_CONTENT") < types.index("TEXT_MESSAGE_END")


def test_smoke_tool_using_role_emits_tool_events_in_order() -> None:
    run_id = str(uuid4())
    call_id = str(uuid4())
    events = [
        RunStarted(run_id=run_id, started_at=_now_iso()),
        ToolCallStart(call_id=call_id, tool_name="search"),
        ToolCallArgs(call_id=call_id, args_chunk='{"q":"weather"}'),
        ToolCallEnd(call_id=call_id),
        RunFinished(run_id=run_id, finished_at=_now_iso()),
    ]
    harness = _FakeHarness(events)
    app = _make_app(harness)

    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    resp = client.post("/chat", json={"message": "what is the weather"})

    assert resp.status_code == 200
    parsed = _parse_sse(resp.text)
    types = [e.get("type") for e in parsed]
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert "TOOL_CALL_START" in types
    assert "TOOL_CALL_ARGS" in types
    assert "TOOL_CALL_END" in types
    assert types.index("TOOL_CALL_START") < types.index("TOOL_CALL_ARGS")
    assert types.index("TOOL_CALL_ARGS") < types.index("TOOL_CALL_END")


def test_smoke_health_endpoint() -> None:
    """Operator runbook: /health returns persona/role/harness so an operator
    can confirm the server bound the intended config without sending a chat."""
    harness = _FakeHarness(events=[])
    app = _make_app(harness)
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persona"] == "personal"
    assert body["role"] == "coder"
    assert body["harness"] == "deep_agents"


# ---------------------------------------------------------------------------
# IMPL_REVIEW round-1 regression — codex #1: SSE payloads MUST be camelCase
# ---------------------------------------------------------------------------


def test_sse_payloads_use_ag_ui_camelcase_aliases() -> None:
    """SSE event payloads MUST serialize with AG-UI camelCase aliases.

    Regression for IMPL_REVIEW round-1 codex #1: pre-fix, routes.py called
    ``evt.model_dump_json()`` with no kwargs. Pydantic emitted ``thread_id``
    / ``run_id`` / ``message_id`` (snake_case) plus null upstream fields,
    breaking the ag-ui-events.schema.json contract which requires
    ``threadId`` / ``runId`` / ``messageId`` (camelCase) and
    ``additionalProperties=false``. After the fix the routes use
    ``by_alias=True, exclude_none=True``.
    """
    run_id = str(uuid4())
    msg_id = str(uuid4())
    events = [
        RunStarted(run_id=run_id, started_at=_now_iso()),
        TextDelta(message_id=msg_id, text="Hello"),
        RunFinished(run_id=run_id, finished_at=_now_iso()),
    ]
    harness = _FakeHarness(events)
    app = _make_app(harness)
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 200

    parsed = _parse_sse(resp.text)
    assert parsed, f"expected SSE events; got {resp.text!r}"

    # Find RUN_STARTED and assert camelCase keys are present (and snake_case absent).
    run_started = next(e for e in parsed if e.get("type") == "RUN_STARTED")
    assert "threadId" in run_started, (
        f"RUN_STARTED must use camelCase 'threadId'; got {list(run_started.keys())}"
    )
    assert "runId" in run_started, (
        f"RUN_STARTED must use camelCase 'runId'; got {list(run_started.keys())}"
    )
    assert "thread_id" not in run_started, (
        "snake_case 'thread_id' must not leak into SSE payload"
    )
    assert "run_id" not in run_started, (
        "snake_case 'run_id' must not leak into SSE payload"
    )

    # No null fields anywhere (exclude_none=True).
    for evt in parsed:
        null_keys = [k for k, v in evt.items() if v is None]
        assert not null_keys, (
            f"Event {evt.get('type')} leaks null fields {null_keys} "
            f"— exclude_none=True is required for AG-UI contract conformance"
        )

    # TEXT_MESSAGE_START must carry messageId AND role='assistant'
    # (gemini #1 — role is required by the AG-UI protocol).
    text_start = next(e for e in parsed if e.get("type") == "TEXT_MESSAGE_START")
    assert text_start.get("messageId") == msg_id
    assert text_start.get("role") == "assistant", (
        f"TEXT_MESSAGE_START must include role='assistant'; got {text_start!r}"
    )
