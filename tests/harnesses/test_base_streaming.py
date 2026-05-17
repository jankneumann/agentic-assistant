"""Tests for SdkHarnessAdapter.astream_invoke contract (harness-ag-ui-bridge task 2.1).

TDD: written BEFORE the implementation in base.py. These tests will fail
until task 2.2 adds astream_invoke and thread_id to SdkHarnessAdapter.

Design note: astream_invoke and thread_id are added as overridable methods
on SdkHarnessAdapter that raise NotImplementedError on the base.  Concrete
harnesses (DeepAgentsHarness, MSAgentFrameworkHarness) add their
implementations in downstream work packages (wp-deep-agents-stream,
wp-msaf-stream). The base-class stubs are NON-abstract so existing concrete
harness tests remain green while the abstract contract is enforced at
runtime.

The tests here verify:
  1. The methods exist on the base class.
  2. The base-class defaults raise NotImplementedError.
  3. A fully-implemented concrete subclass (_MinimalHarness) satisfies the
     async-iterator / thread_id contract.

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
# Helpers — minimal concrete implementation for testing the full contract
# ---------------------------------------------------------------------------


class _MinimalHarness(SdkHarnessAdapter):
    """Minimal concrete harness that satisfies all abstract + streaming requirements."""

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


def test_astream_invoke_exists_on_base() -> None:
    """SdkHarnessAdapter MUST expose astream_invoke."""
    assert hasattr(SdkHarnessAdapter, "astream_invoke"), (
        "astream_invoke not found on SdkHarnessAdapter"
    )


def test_astream_invoke_base_raises_not_implemented() -> None:
    """The base-class astream_invoke MUST raise NotImplementedError."""
    # We cannot instantiate SdkHarnessAdapter directly (it has other abstract
    # methods), so we test via a partial stub that DOESN'T override
    # astream_invoke.  The partial stub overrides only the other abstract
    # methods so instantiation succeeds.

    class _StubNoStream(SdkHarnessAdapter):
        def name(self) -> str:
            return "stub"

        @property
        def thread_id(self) -> str:
            return "stub-thread"

        async def create_agent(self, tools: list[Any], extensions: list[Any]) -> Any:
            return None

        async def invoke(self, agent: Any, message: str) -> str:
            return ""

        async def spawn_sub_agent(
            self, role: Any, task: str, tools: list[Any], extensions: list[Any]
        ) -> str:
            return ""
        # astream_invoke NOT overridden — base raises NotImplementedError

    h = _StubNoStream(MagicMock(), MagicMock())
    with pytest.raises(NotImplementedError):
        h.astream_invoke(object(), "hello")


def test_thread_id_exists_on_base() -> None:
    """SdkHarnessAdapter MUST expose thread_id."""
    assert hasattr(SdkHarnessAdapter, "thread_id"), (
        "thread_id not found on SdkHarnessAdapter"
    )


def test_thread_id_base_raises_not_implemented() -> None:
    """The base-class thread_id MUST raise NotImplementedError."""

    class _StubNoThreadId(SdkHarnessAdapter):
        def name(self) -> str:
            return "stub"

        async def create_agent(self, tools: list[Any], extensions: list[Any]) -> Any:
            return None

        async def invoke(self, agent: Any, message: str) -> str:
            return ""

        async def spawn_sub_agent(
            self, role: Any, task: str, tools: list[Any], extensions: list[Any]
        ) -> str:
            return ""
        # thread_id NOT overridden — base raises NotImplementedError

    h = _StubNoThreadId(MagicMock(), MagicMock())
    with pytest.raises(NotImplementedError):
        _ = h.thread_id


def test_astream_invoke_signature() -> None:
    """astream_invoke(self, agent, message) signature must match the contract."""
    method = getattr(SdkHarnessAdapter, "astream_invoke", None)
    assert method is not None, "astream_invoke not found on SdkHarnessAdapter"
    sig = inspect.signature(method)
    params = list(sig.parameters)
    assert "agent" in params, f"'agent' parameter missing; got {params!r}"
    assert "message" in params, f"'message' parameter missing; got {params!r}"


def test_minimal_harness_instantiates() -> None:
    """A subclass implementing all methods can be instantiated."""
    h = _MinimalHarness()
    assert h is not None


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
    assert isinstance(events[0], RunStarted), (
        f"First event must be RunStarted; got {type(events[0])}"
    )
    assert isinstance(events[-1], RunFinished), (
        f"Last event must be RunFinished; got {type(events[-1])}"
    )


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
