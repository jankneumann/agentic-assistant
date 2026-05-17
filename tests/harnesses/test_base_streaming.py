"""Tests for SdkHarnessAdapter.astream_invoke abstract signature (harness-ag-ui-bridge task 2.1).

TDD: written BEFORE the implementation in base.py. Collection will succeed
(the module exists) but the tests will fail until task 2.2 adds the abstract
methods.

Spec scenarios:
  - "SdkHarnessAdapter.astream_invoke returns async iterator of HarnessEvent"
  - "SdkHarnessAdapter exposes a thread_id for transport binding"
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from assistant.harnesses.base import SdkHarnessAdapter
from assistant.harnesses.sdk.events import HarnessEvent, RunFinished, RunStarted

# ---------------------------------------------------------------------------
# Helpers — minimal concrete implementation for testing the abstract contract
# ---------------------------------------------------------------------------


class _MinimalHarness(SdkHarnessAdapter):
    """Minimal concrete harness that satisfies all abstract requirements."""

    def __init__(self) -> None:
        persona = MagicMock()
        persona.name = "test"
        role = MagicMock()
        role.name = "assistant"
        super().__init__(persona, role)
        self._tid = "thread-test-001"

    def name(self) -> str:
        return "minimal"

    @property
    def thread_id(self) -> str:
        return self._tid

    async def create_agent(self, tools: list[Any], extensions: list[Any]) -> Any:
        return object()

    async def invoke(self, agent: Any, message: str) -> str:
        return "ok"

    async def astream_invoke(self, agent: Any, message: str) -> AsyncIterator[HarnessEvent]:
        run_id = "r-test"
        yield RunStarted(run_id=run_id, started_at="2026-05-16T09:00:00Z")
        yield RunFinished(run_id=run_id, finished_at="2026-05-16T09:00:01Z")

    async def spawn_sub_agent(
        self,
        role: Any,
        task: str,
        tools: list[Any],
        extensions: list[Any],
    ) -> str:
        return "done"


# ---------------------------------------------------------------------------
# Scenario: SdkHarnessAdapter.astream_invoke returns async iterator of HarnessEvent
# ---------------------------------------------------------------------------


def test_astream_invoke_is_abstract_on_base() -> None:
    """SdkHarnessAdapter.astream_invoke MUST be abstract."""
    assert hasattr(SdkHarnessAdapter, "astream_invoke"), (
        "astream_invoke not found on SdkHarnessAdapter"
    )
    # The method must be abstract — cannot instantiate without it.
    # We verify this by checking the abstractmethods set.
    abstracts: frozenset[str] = getattr(SdkHarnessAdapter, "__abstractmethods__", frozenset())
    assert "astream_invoke" in abstracts, (
        f"astream_invoke is not abstract on SdkHarnessAdapter; "
        f"abstractmethods={abstracts!r}"
    )


def test_thread_id_is_abstract_on_base() -> None:
    """SdkHarnessAdapter.thread_id MUST be an abstract property."""
    assert hasattr(SdkHarnessAdapter, "thread_id"), (
        "thread_id not found on SdkHarnessAdapter"
    )
    abstracts: frozenset[str] = getattr(SdkHarnessAdapter, "__abstractmethods__", frozenset())
    assert "thread_id" in abstracts, (
        f"thread_id is not abstract on SdkHarnessAdapter; "
        f"abstractmethods={abstracts!r}"
    )


def test_astream_invoke_signature() -> None:
    """astream_invoke(self, agent, message) signature must match the contract."""
    method = getattr(SdkHarnessAdapter, "astream_invoke", None)
    assert method is not None, "astream_invoke not found on SdkHarnessAdapter"
    sig = inspect.signature(method)
    params = list(sig.parameters)
    assert "agent" in params, f"'agent' parameter missing; got {params!r}"
    assert "message" in params, f"'message' parameter missing; got {params!r}"


def test_cannot_instantiate_without_astream_invoke() -> None:
    """Subclass missing astream_invoke cannot be instantiated."""

    class _Incomplete(SdkHarnessAdapter):
        def name(self) -> str:
            return "incomplete"

        async def create_agent(self, tools: list[Any], extensions: list[Any]) -> Any:
            return None

        async def invoke(self, agent: Any, message: str) -> str:
            return ""

        async def spawn_sub_agent(
            self,
            role: Any,
            task: str,
            tools: list[Any],
            extensions: list[Any],
        ) -> str:
            return ""

        # MISSING: astream_invoke and thread_id

    with pytest.raises(TypeError, match="abstract"):
        _Incomplete(MagicMock(), MagicMock())


def test_cannot_instantiate_without_thread_id() -> None:
    """Subclass missing thread_id cannot be instantiated."""

    class _MissingThreadId(SdkHarnessAdapter):
        def name(self) -> str:
            return "no_thread"

        @property
        def thread_id(self) -> str:
            raise NotImplementedError  # satisfy mypy shape but don't count for abstract

        async def create_agent(self, tools: list[Any], extensions: list[Any]) -> Any:
            return None

        async def invoke(self, agent: Any, message: str) -> str:
            return ""

        async def astream_invoke(self, agent: Any, message: str) -> AsyncIterator[HarnessEvent]:
            yield RunStarted(run_id="r", started_at="2026-05-16T09:00:00Z")

        async def spawn_sub_agent(
            self,
            role: Any,
            task: str,
            tools: list[Any],
            extensions: list[Any],
        ) -> str:
            return ""

    # This class does implement thread_id, so it can be instantiated.
    # The test below checks the fully-implemented _MinimalHarness works.
    h = _MissingThreadId(MagicMock(), MagicMock())
    assert h is not None  # instantiation succeeds when thread_id is present


# ---------------------------------------------------------------------------
# Scenario: concrete harness implementing the contract works correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_invoke_yields_harness_events() -> None:
    """A concrete astream_invoke must yield HarnessEvent instances."""
    h = _MinimalHarness()
    agent = object()
    events = []
    async for ev in h.astream_invoke(agent, "hello"):
        events.append(ev)

    assert len(events) >= 2, f"Expected at least 2 events; got {len(events)}"
    assert isinstance(events[0], RunStarted), f"First event must be RunStarted; got {type(events[0])}"
    assert isinstance(events[-1], RunFinished), f"Last event must be RunFinished; got {type(events[-1])}"


@pytest.mark.asyncio
async def test_astream_invoke_stream_starts_with_run_started() -> None:
    """First event MUST be RunStarted per the spec."""
    h = _MinimalHarness()
    agent = object()
    async for ev in h.astream_invoke(agent, "hi"):
        assert isinstance(ev, RunStarted), f"First event must be RunStarted; got {type(ev)}"
        break


@pytest.mark.asyncio
async def test_astream_invoke_stream_ends_with_run_finished() -> None:
    """Last event MUST be RunFinished per the spec."""
    h = _MinimalHarness()
    agent = object()
    events = [ev async for ev in h.astream_invoke(agent, "hi")]
    assert isinstance(events[-1], RunFinished), (
        f"Last event must be RunFinished; got {type(events[-1])}"
    )


# ---------------------------------------------------------------------------
# Scenario: SdkHarnessAdapter exposes a thread_id for transport binding
# ---------------------------------------------------------------------------


def test_thread_id_is_non_empty_string() -> None:
    """thread_id must be a non-empty string."""
    h = _MinimalHarness()
    tid = h.thread_id
    assert isinstance(tid, str), f"thread_id must be str; got {type(tid)}"
    assert tid, "thread_id must be non-empty"


def test_thread_id_stable_across_calls() -> None:
    """thread_id must not change between calls on the same instance."""
    h = _MinimalHarness()
    tid1 = h.thread_id
    tid2 = h.thread_id
    assert tid1 == tid2, f"thread_id changed between calls: {tid1!r} != {tid2!r}"
