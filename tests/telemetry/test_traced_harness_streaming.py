"""Tests for @traced_harness async-generator support (harness-ag-ui-bridge task 2.3).

TDD: these tests are written BEFORE the implementation in
``src/assistant/telemetry/decorators.py``. The tests will fail until
task 2.4 extends @traced_harness to dispatch on coroutine vs async-generator.

Spec scenarios:
  - "Deep Agents astream_invoke is traced on success"
  - "Deep Agents astream_invoke is traced on exception"
  - "MSAF astream_invoke applies @traced_harness" (success path)
  - "MSAF astream_invoke is traced on exception"

Design reference: design.md D9 — @traced_harness dispatches on the wrapped
function's kind (coroutine vs async-generator). For async generators:
  - Emit trace_llm_call exactly ONCE after exhaustion (success).
  - Emit trace_llm_call exactly ONCE when exception escapes (failure), with
    metadata={"streaming": True, "error": "<ClassName>"}.
  - Always include metadata={"streaming": True} on the async-generator path.
  - Re-raise the original exception after recording the span.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest

from assistant.harnesses.sdk.events import HarnessEvent, RunFinished, RunStarted
from assistant.telemetry import factory
from assistant.telemetry.context import set_assistant_ctx
from assistant.telemetry.decorators import traced_harness

# Cast traced_harness to Any so mypy accepts it on async generator methods
# during the RED phase (task 2.3). The cast is inert at runtime and becomes
# permanently valid once task 2.4 updates the decorator's type signature to
# accept both coroutines and async generators.
_traced: Any = cast(Any, traced_harness)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_ctx() -> None:
    """Each test starts with no persona/role bound to the ContextVar."""
    set_assistant_ctx(None, None)


class _FakeStreamHarness:
    """Minimal harness shim for async-generator tests."""

    def __init__(self, persona_name: str, role_name: str, model: str) -> None:
        self.persona = type("P", (), {"name": persona_name, "harnesses": {}})()
        self.role = type("R", (), {"name": role_name})()
        self.persona.harnesses = {"deep_agents": {"model": model}}
        self._active_model = model


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


# ---------------------------------------------------------------------------
# Scenario: Deep Agents astream_invoke is traced on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traced_harness_async_gen_emits_trace_on_success(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """@traced_harness on async generator emits exactly one trace_llm_call on success."""
    _install_spy(monkeypatch, spy_provider)

    class H(_FakeStreamHarness):
        @_traced
        async def astream_invoke(
            self, agent: Any, message: str
        ) -> AsyncIterator[HarnessEvent]:
            yield RunStarted(run_id="r-1", started_at="2026-05-16T09:00:00Z")
            await asyncio.sleep(0)
            yield RunFinished(run_id="r-1", finished_at="2026-05-16T09:00:01Z")

    h = H("personal", "assistant", "anthropic:claude-sonnet-4-20250514")
    events = [ev async for ev in h.astream_invoke(object(), "hello")]

    assert len(events) == 2
    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 1, f"Expected 1 trace call; got {len(calls)}"
    call = calls[0]
    assert call["persona"] == "personal"
    assert call["role"] == "assistant"
    assert call["model"] == "anthropic:claude-sonnet-4-20250514"
    assert isinstance(call["duration_ms"], float)
    assert call["duration_ms"] >= 0.0
    # metadata MUST include streaming=True on the async-generator path
    assert call.get("metadata") == {"streaming": True} or (
        isinstance(call.get("metadata"), dict) and call["metadata"].get("streaming") is True
    ), f"Expected metadata to include streaming=True; got {call.get('metadata')!r}"


@pytest.mark.asyncio
async def test_traced_harness_async_gen_emits_trace_exactly_once(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """@traced_harness must emit exactly one trace per invocation, not one per event."""
    _install_spy(monkeypatch, spy_provider)

    class H(_FakeStreamHarness):
        @_traced
        async def astream_invoke(
            self, agent: Any, message: str
        ) -> AsyncIterator[HarnessEvent]:
            for _ in range(5):
                yield RunStarted(run_id="r-1", started_at="2026-05-16T09:00:00Z")
            yield RunFinished(run_id="r-1", finished_at="2026-05-16T09:00:01Z")

    h = H("p", "r", "m")
    events = [ev async for ev in h.astream_invoke(object(), "hi")]
    assert len(events) == 6
    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 1, f"Expected exactly 1 trace; got {len(calls)}: {calls}"


# ---------------------------------------------------------------------------
# Scenario: Deep Agents astream_invoke is traced on exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traced_harness_async_gen_emits_trace_on_exception(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """@traced_harness on async generator emits trace with error metadata on exception."""
    _install_spy(monkeypatch, spy_provider)

    class H(_FakeStreamHarness):
        @_traced
        async def astream_invoke(
            self, agent: Any, message: str
        ) -> AsyncIterator[HarnessEvent]:
            yield RunStarted(run_id="r-1", started_at="2026-05-16T09:00:00Z")
            yield RunFinished(
                run_id="r-1",
                finished_at="2026-05-16T09:00:01Z",
                error="RuntimeError",
            )
            raise RuntimeError("quota exceeded")

    h = H("personal", "assistant", "anthropic:claude-sonnet-4-20250514")
    events = []
    with pytest.raises(RuntimeError, match="quota exceeded"):
        async for ev in h.astream_invoke(object(), "hi"):
            events.append(ev)

    # The two lifecycle events must have been yielded before the exception
    assert len(events) == 2
    assert isinstance(events[0], RunStarted)
    assert isinstance(events[1], RunFinished)

    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 1, f"Expected 1 trace call on exception; got {len(calls)}"
    call = calls[0]
    assert isinstance(call.get("metadata"), dict), (
        f"metadata must be a dict; got {call.get('metadata')!r}"
    )
    assert call["metadata"].get("streaming") is True, (
        f"metadata must include streaming=True; got {call['metadata']!r}"
    )
    assert call["metadata"].get("error") == "RuntimeError", (
        f"metadata must include error='RuntimeError'; got {call['metadata']!r}"
    )


@pytest.mark.asyncio
async def test_traced_harness_async_gen_reraises_exception(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """@traced_harness must re-raise the original exception unchanged."""
    _install_spy(monkeypatch, spy_provider)

    original = RuntimeError("original error")

    class H(_FakeStreamHarness):
        @_traced
        async def astream_invoke(
            self, agent: Any, message: str
        ) -> AsyncIterator[HarnessEvent]:
            yield RunStarted(run_id="r-1", started_at="2026-05-16T09:00:00Z")
            raise original

    h = H("p", "r", "m")
    with pytest.raises(RuntimeError) as exc_info:
        async for _ in h.astream_invoke(object(), "hi"):
            pass

    assert exc_info.value is original, (
        "The re-raised exception must be the exact original exception object"
    )


# ---------------------------------------------------------------------------
# Existing coroutine path must remain unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traced_harness_coroutine_path_still_works(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """@traced_harness on a regular coroutine (invoke) must still work as before."""
    _install_spy(monkeypatch, spy_provider)

    class H(_FakeStreamHarness):
        @_traced
        async def invoke(self, agent: Any, message: str) -> str:
            await asyncio.sleep(0)
            return "response"

    h = H("personal", "assistant", "anthropic:claude-sonnet-4-20250514")
    result = await h.invoke(object(), "hello")
    assert result == "response"

    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 1
    call = calls[0]
    # Coroutine path should NOT set streaming=True in metadata
    meta = call.get("metadata")
    assert meta is None or (isinstance(meta, dict) and "streaming" not in meta), (
        f"Coroutine path must not set streaming=True; got metadata={meta!r}"
    )


@pytest.mark.asyncio
async def test_traced_harness_single_decorator_works_on_both_shapes(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """The same @traced_harness decorator must wrap both coroutines and async generators."""
    _install_spy(monkeypatch, spy_provider)

    class H(_FakeStreamHarness):
        @_traced
        async def invoke(self, agent: Any, message: str) -> str:
            return "result"

        @_traced
        async def astream_invoke(
            self, agent: Any, message: str
        ) -> AsyncIterator[HarnessEvent]:
            yield RunStarted(run_id="r-1", started_at="2026-05-16T09:00:00Z")
            yield RunFinished(run_id="r-1", finished_at="2026-05-16T09:00:01Z")

    h = H("p", "r", "m")

    # Both should work without error
    result = await h.invoke(object(), "msg")
    assert result == "result"
    events = [ev async for ev in h.astream_invoke(object(), "msg")]
    assert len(events) == 2

    # Each call emits exactly one trace
    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 2, f"Expected 2 total traces (one per call); got {len(calls)}"


# ---------------------------------------------------------------------------
# IMPL_REVIEW round-1 regression tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_traced_harness_aclose_finalizes_inner_generator(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Closing the outer wrapper MUST finalize the inner harness generator.

    Regression for IMPL_REVIEW round-1 codex #3: pre-fix, the wrapper
    iterated ``fn(...)`` without aclose, so the inner generator was
    orphaned on client disconnect. After the fix, ``aclosing(gen)``
    inside the wrapper guarantees the inner's ``finally`` block fires
    when the outer wrapper is closed.
    """
    _install_spy(monkeypatch, spy_provider)
    inner_finalized = {"flag": False}

    class H(_FakeStreamHarness):
        @_traced
        async def astream_invoke(
            self, agent: Any, message: str
        ) -> AsyncIterator[HarnessEvent]:
            try:
                yield RunStarted(run_id="r-1", started_at="2026-05-16T09:00:00Z")
                # Yield many events so we can break the consumer mid-stream.
                for _i in range(100):
                    yield RunStarted(
                        run_id=f"r-{_i + 2}",
                        started_at="2026-05-16T09:00:01Z",
                    )
            finally:
                inner_finalized["flag"] = True

    h = H("p", "r", "m")
    from contextlib import aclosing

    async with aclosing(h.astream_invoke(object(), "msg")) as gen:
        seen = 0
        async for _evt in gen:
            seen += 1
            if seen >= 2:
                break
    # The async-with exit calls aclose() on the wrapper, which (with the
    # codex #3 fix) calls aclose() on the inner gen, which fires the
    # inner's finally block.
    assert inner_finalized["flag"], (
        "inner generator's finally did not run — wrapper aclose() did not "
        "propagate to the inner gen (codex #3 regression)"
    )


@pytest.mark.asyncio
async def test_traced_harness_generator_exit_recorded_as_cancelled(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """GeneratorExit MUST be recorded as cancelled=True, not as an error.

    Regression for IMPL_REVIEW round-1 gemini #6: pre-fix, the wrapper
    branched on ``except BaseException`` and labelled every termination
    (including normal client disconnect) as ``error: GeneratorExit``.
    After the fix, GeneratorExit is recorded with
    ``metadata={"streaming": True, "cancelled": True}`` so dashboards
    can distinguish "shut down cleanly" from "crashed".
    """
    _install_spy(monkeypatch, spy_provider)

    class H(_FakeStreamHarness):
        @_traced
        async def astream_invoke(
            self, agent: Any, message: str
        ) -> AsyncIterator[HarnessEvent]:
            for i in range(50):
                yield RunStarted(
                    run_id=f"r-{i}",
                    started_at="2026-05-16T09:00:00Z",
                )

    h = H("p", "r", "m")
    from contextlib import aclosing

    async with aclosing(h.astream_invoke(object(), "msg")) as gen:
        async for _evt in gen:
            break  # Consume one, then aclose via context-manager exit.

    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 1, f"Expected 1 trace; got {len(calls)}"
    metadata = calls[0].get("metadata") or {}
    assert metadata.get("cancelled") is True, (
        f"GeneratorExit must be recorded as cancelled=True; got metadata={metadata!r}"
    )
    assert "error" not in metadata, (
        f"GeneratorExit must NOT be labelled as error; got metadata={metadata!r}"
    )
