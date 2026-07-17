"""Shared fakes for the A2A test suite (fixture-only, no persona data)."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.sdk.events import (
    RunFinished,
    RunStarted,
    TextDelta,
)


def make_run_started(run_id: str | None = None) -> RunStarted:
    return RunStarted(
        run_id=run_id or str(uuid.uuid4()),
        started_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )


def make_run_finished(run_id: str, error: str | None = None) -> RunFinished:
    return RunFinished(
        run_id=run_id,
        finished_at=datetime.datetime.now(datetime.UTC).isoformat(),
        error=error,
    )


def make_text_delta(message_id: str, text: str) -> TextDelta:
    return TextDelta(message_id=message_id, text=text)


def simple_events() -> list[Any]:
    rs = make_run_started()
    return [rs, make_run_finished(rs.run_id)]


def text_events(*chunks: str, message_id: str = "msg-1") -> list[Any]:
    rs = make_run_started()
    deltas = [make_text_delta(message_id, c) for c in chunks]
    return [rs, *deltas, make_run_finished(rs.run_id)]


def error_events(error: str = "RuntimeError") -> list[Any]:
    rs = make_run_started()
    return [rs, make_run_finished(rs.run_id, error=error)]


class FakeHarness:
    """SdkHarnessAdapter-shaped stub: fixed event script per invocation."""

    def __init__(
        self,
        events: list[Any] | None = None,
        thread_id: str | None = None,
        raise_after: Exception | None = None,
    ) -> None:
        self._events = events if events is not None else simple_events()
        self._thread_id = thread_id or f"thread-{uuid.uuid4()}"
        self._raise_after = raise_after
        self.invocations: list[str] = []

    @property
    def thread_id(self) -> str:
        return self._thread_id

    async def create_agent(self, tools: list, extensions: list) -> Any:
        return {"agent-for": self._thread_id}

    async def invoke(self, agent: Any, message: str) -> str:
        """Blocking variant (consumed by the MCP ask tools): returns the
        concatenation of the scripted TextDelta texts."""
        self.invocations.append(message)
        return "".join(
            e.text for e in self._events if isinstance(e, TextDelta)
        )

    async def astream_invoke(
        self, agent: Any, message: str
    ) -> AsyncIterator[Any]:
        self.invocations.append(message)
        for evt in self._events:
            yield evt
        if self._raise_after is not None:
            raise self._raise_after


def make_session_factory(harness_events: list[Any] | None = None):
    """Session factory producing a fresh FakeHarness (unique thread_id)
    per call; returns (factory, created) where ``created`` collects the
    harnesses for assertions."""
    created: list[FakeHarness] = []

    async def _factory():
        harness = FakeHarness(events=list(harness_events or simple_events()))
        agent = await harness.create_agent([], [])
        created.append(harness)
        return harness, agent

    return _factory, created


def fixture_persona(name: str = "fixture") -> PersonaConfig:
    return PersonaConfig(
        name=name,
        display_name="Fixture Persona",
        database_url="",
        graphiti_url="",
        auth_provider="none",
        auth_config={},
        harnesses={"deep_agents": {"enabled": True}},
        tool_sources={},
        extensions=[],
        extensions_dir=Path("."),
        default_role="coder",
    )


def fixture_roles() -> list[RoleConfig]:
    return [
        RoleConfig(
            name="coder",
            display_name="Coder",
            description="Code analysis and implementation",
            prompt="",
        ),
        RoleConfig(
            name="researcher",
            display_name="Researcher",
            description="Deep research and synthesis",
            prompt="",
        ),
    ]


def user_message_payload(
    text: str = "hello",
    *,
    context_id: str | None = None,
    task_id: str | None = None,
) -> dict:
    msg: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": str(uuid.uuid4()),
    }
    if context_id is not None:
        msg["contextId"] = context_id
    if task_id is not None:
        msg["taskId"] = task_id
    return {"message": msg}


def rpc_envelope(method: str, params: dict, req_id: str = "req-1") -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
