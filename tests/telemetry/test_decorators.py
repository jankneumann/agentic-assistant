"""Tests for ``@traced_harness`` and ``@traced_delegation`` (wp-hooks).

TDD scaffolding: these tests assert the public contract of the two
decorators in ``src/assistant/telemetry/decorators.py`` (created by
tasks 2.2 and 2.5).

The decorators MUST:

- Emit exactly one ``trace_*`` call per invocation.
- Measure ``duration_ms`` around the awaited call.
- On exception, emit the span with ``metadata={"error": <type>}``
  before re-raising the original exception.
- Be safe under the noop provider (no allocation, no I/O).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from assistant.telemetry import factory
from assistant.telemetry.context import set_assistant_ctx


@pytest.fixture(autouse=True)
def _reset_ctx() -> None:
    """Each test starts with no persona/role bound to the ContextVar."""
    set_assistant_ctx(None, None)


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    """Replace the factory singleton with the spy for the test duration."""
    monkeypatch.setattr(factory, "_provider", spy)


# ---------------------------------------------------------------------------
# @traced_harness
# ---------------------------------------------------------------------------


class _FakeHarness:
    """Minimal harness shim exposing ``persona`` + ``role`` like the real one."""

    def __init__(self, persona_name: str, role_name: str, model: str) -> None:
        # Mimic the attribute shape of ``HarnessAdapter.persona``/``role``.
        self.persona = type("P", (), {"name": persona_name})()
        self.role = type("R", (), {"name": role_name})()
        self.persona.harnesses = {"deep_agents": {"model": model}}


@pytest.mark.asyncio
async def test_traced_harness_emits_trace_llm_call_on_success(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            await asyncio.sleep(0)
            return "ok"

    h = H("personal", "assistant", "anthropic:claude-sonnet-4-20250514")
    result = await h.invoke(object(), "hello")

    assert result == "ok"
    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 1
    call = calls[0]
    assert call["persona"] == "personal"
    assert call["role"] == "assistant"
    assert call["model"] == "anthropic:claude-sonnet-4-20250514"
    assert isinstance(call["duration_ms"], float)
    assert call["duration_ms"] >= 0.0


@pytest.mark.asyncio
async def test_traced_harness_emits_once_on_exception_then_reraises(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            raise RuntimeError("model unavailable")

    h = H("personal", "assistant", "x:y")
    with pytest.raises(RuntimeError, match="model unavailable"):
        await h.invoke(object(), "hello")

    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 1
    assert calls[0]["metadata"] == {"error": "RuntimeError"}


@pytest.mark.asyncio
async def test_traced_harness_emits_for_not_implemented_stubs(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """MSAgentFrameworkHarness stub raises ``NotImplementedError``."""
    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            raise NotImplementedError("stubbed")

    h = H("personal", "assistant", "x:y")
    with pytest.raises(NotImplementedError):
        await h.invoke(object(), "hello")

    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 1
    assert calls[0]["metadata"] == {"error": "NotImplementedError"}


@pytest.mark.asyncio
async def test_traced_harness_under_noop_provider_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No spy: the default noop provider yields no errors and no I/O."""
    from assistant.telemetry.decorators import traced_harness
    from assistant.telemetry.providers.noop import NoopProvider

    monkeypatch.setattr(factory, "_provider", NoopProvider())

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            return "fine"

    h = H("personal", "assistant", "x:y")
    out = await h.invoke(object(), "hi")
    assert out == "fine"


@pytest.mark.asyncio
async def test_traced_harness_uses_assistant_ctx_when_persona_attr_missing(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """If self has no persona/role attrs, fall back to assistant_ctx."""
    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)
    set_assistant_ctx("personal", "assistant")

    class H:
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            return "ok"

    out = await H().invoke(object(), "hello")
    assert out == "ok"
    call = spy_provider.calls["trace_llm_call"][0]
    assert call["persona"] == "personal"
    assert call["role"] == "assistant"


@pytest.mark.asyncio
async def test_traced_harness_captures_tokens_via_usage_callback(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Iter-2 round-2 fix (claude #1 + gemini #2): tokens are captured
    via LangChain Core's ``get_usage_metadata_callback`` context manager
    rather than a ``self._last_usage`` instance attribute. The decorator
    must read ``cb.usage_metadata`` and forward the per-model token
    counts to ``trace_llm_call`` (req observability.3).
    """
    from langchain_core.language_models.fake_chat_models import (
        GenericFakeChatModel,
    )
    from langchain_core.messages import AIMessage

    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            ai = AIMessage(
                content="hello",
                usage_metadata={
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                },
                response_metadata={"model_name": "fake-callback-test"},
            )
            llm = GenericFakeChatModel(messages=iter([ai]))
            await llm.ainvoke("hi")
            return "ok"

    h = H("personal", "assistant", "x:y")
    await h.invoke(object(), "go")

    call = spy_provider.calls["trace_llm_call"][0]
    assert call["input_tokens"] == 100
    assert call["output_tokens"] == 50


@pytest.mark.asyncio
async def test_traced_harness_emits_zero_tokens_when_no_llm_fires(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """When the awaited body does not invoke any LLM, the decorator
    records ``(0, 0)`` rather than ``None`` — req observability.3's
    MUST-include contract is satisfied without inventing values.
    """
    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            return "ok"

    h = H("personal", "assistant", "x:y")
    await h.invoke(object(), "hi")

    call = spy_provider.calls["trace_llm_call"][0]
    assert call["input_tokens"] == 0
    assert call["output_tokens"] == 0
    # Both must be int — never None — so consumers can do arithmetic.
    assert isinstance(call["input_tokens"], int)
    assert isinstance(call["output_tokens"], int)


@pytest.mark.asyncio
async def test_traced_harness_emits_zero_tokens_on_exception_path(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """The exception path also records concrete int tokens (0/0 when
    no LLM fired before the failure), not ``None``.
    """
    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            raise RuntimeError("boom")

    h = H("personal", "assistant", "x:y")
    with pytest.raises(RuntimeError):
        await h.invoke(object(), "hi")

    call = spy_provider.calls["trace_llm_call"][0]
    assert isinstance(call["input_tokens"], int)
    assert isinstance(call["output_tokens"], int)
    assert call["input_tokens"] == 0
    assert call["output_tokens"] == 0


@pytest.mark.asyncio
async def test_traced_harness_does_not_accumulate_tokens_across_invocations(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Iter-2 round-2 regression test (claude #1): once a checkpointer
    -backed agent re-uses the same harness instance across turns, the
    second invocation's emitted tokens MUST reflect ONLY the second
    body's LLM calls — not the sum across both turns. This is the
    failure mode the previous ``_extract_usage`` walk-all-messages
    approach would hit; the callback context manager is bounded to the
    current ``with`` block so prior-turn AIMessages are out of scope.
    """
    from langchain_core.language_models.fake_chat_models import (
        GenericFakeChatModel,
    )
    from langchain_core.messages import AIMessage

    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            tokens = (10, 20) if message == "first" else (3, 5)
            ai = AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": tokens[0],
                    "output_tokens": tokens[1],
                    "total_tokens": tokens[0] + tokens[1],
                },
                response_metadata={"model_name": "fake-multi-turn"},
            )
            llm = GenericFakeChatModel(messages=iter([ai]))
            await llm.ainvoke(message)
            return "ok"

    h = H("personal", "assistant", "x:y")
    await h.invoke(object(), "first")
    await h.invoke(object(), "second")

    calls = spy_provider.calls["trace_llm_call"]
    # Each turn reports its own tokens, never the running total.
    assert calls[0]["input_tokens"] == 10
    assert calls[0]["output_tokens"] == 20
    assert calls[1]["input_tokens"] == 3
    assert calls[1]["output_tokens"] == 5


@pytest.mark.asyncio
async def test_traced_harness_isolates_tokens_across_concurrent_invocations(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Iter-2 round-2 regression test (gemini #2): under
    ``asyncio.gather`` the previous ``self._last_usage`` instance
    attribute would race because all tasks shared the same harness
    object. With ``get_usage_metadata_callback`` each awaited body runs
    inside its own callback (PEP 567 ContextVar) so each emitted span
    sees ONLY its own token counts. This test spawns three concurrent
    invocations on the same harness with distinct token amounts and
    asserts the emitted spans pair them correctly (multiset equality).
    """
    import asyncio

    from langchain_core.language_models.fake_chat_models import (
        GenericFakeChatModel,
    )
    from langchain_core.messages import AIMessage

    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            # Token amount encoded in ``message`` so each task is distinct.
            tok = int(message)
            ai = AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": tok,
                    "output_tokens": tok * 2,
                    "total_tokens": tok * 3,
                },
                response_metadata={"model_name": f"fake-concurrent-{tok}"},
            )
            # Yield the loop so tasks interleave before reading the cb.
            await asyncio.sleep(0)
            llm = GenericFakeChatModel(messages=iter([ai]))
            await llm.ainvoke(message)
            return "ok"

    h = H("personal", "assistant", "x:y")
    await asyncio.gather(*(h.invoke(object(), str(i)) for i in (7, 11, 13)))

    calls = spy_provider.calls["trace_llm_call"]
    assert len(calls) == 3
    pairs = sorted((c["input_tokens"], c["output_tokens"]) for c in calls)
    # Each task's (in, out) MUST appear exactly once — no race-induced
    # duplication or zero-leakage.
    assert pairs == [(7, 14), (11, 22), (13, 26)]


def test_sum_usage_metadata_aggregates_across_model_entries() -> None:
    """``_sum_usage_metadata`` walks every model key in ``cb.usage_metadata``
    and sums input/output tokens — covers the deepagents fan-out case
    where planner and executor sub-models each emit their own entry.
    """
    from assistant.telemetry.decorators import _sum_usage_metadata

    cb_data = {
        "claude-sonnet-4": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        "gpt-4o-mini": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
    }
    assert _sum_usage_metadata(cb_data) == (15, 27)


def test_sum_usage_metadata_returns_zeros_for_empty_dict() -> None:
    """Empty dict (no LLM call fired in the awaited block) yields (0, 0)."""
    from assistant.telemetry.decorators import _sum_usage_metadata

    assert _sum_usage_metadata({}) == (0, 0)


def test_sum_usage_metadata_handles_missing_token_keys() -> None:
    """Robust against entries that omit ``input_tokens`` / ``output_tokens``
    (e.g. SDKs that surface only ``total_tokens``)."""
    from assistant.telemetry.decorators import _sum_usage_metadata

    cb_data: dict[str, Any] = {
        "model-a": {"total_tokens": 99},
        "model-b": {"input_tokens": 4, "output_tokens": 6},
    }
    assert _sum_usage_metadata(cb_data) == (4, 6)


# ---------------------------------------------------------------------------
# @traced_delegation
# ---------------------------------------------------------------------------


class _FakeSpawner:
    """Minimal DelegationSpawner shim with the attributes the decorator reads."""

    def __init__(self, persona_name: str, parent_role_name: str) -> None:
        self.persona = type("P", (), {"name": persona_name})()
        self.parent_role = type("R", (), {"name": parent_role_name})()


@pytest.mark.asyncio
async def test_traced_delegation_emits_success(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.decorators import traced_delegation

    _install_spy(monkeypatch, spy_provider)

    class S(_FakeSpawner):
        @traced_delegation
        async def delegate(self, sub_role_name: str, task: str) -> str:
            return "result"

    s = S("personal", "assistant")
    out = await s.delegate("researcher", "find X")
    assert out == "result"
    calls = spy_provider.calls["trace_delegation"]
    assert len(calls) == 1
    call = calls[0]
    assert call["parent_role"] == "assistant"
    assert call["sub_role"] == "researcher"
    assert call["task"] == "find X"
    assert call["persona"] == "personal"
    assert call["outcome"] == "success"
    assert isinstance(call["duration_ms"], float)


@pytest.mark.asyncio
async def test_traced_delegation_emits_error_outcome_then_reraises(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.decorators import traced_delegation

    _install_spy(monkeypatch, spy_provider)

    class S(_FakeSpawner):
        @traced_delegation
        async def delegate(self, sub_role_name: str, task: str) -> str:
            raise ValueError("unknown role")

    s = S("personal", "assistant")
    with pytest.raises(ValueError, match="unknown role"):
        await s.delegate("nope", "x")

    calls = spy_provider.calls["trace_delegation"]
    assert len(calls) == 1
    assert calls[0]["outcome"] == "error"
    assert calls[0]["metadata"] == {"error": "ValueError"}


@pytest.mark.asyncio
async def test_traced_delegation_hashes_long_task(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Tasks longer than 256 chars become ``sha256:<16-char hex>``."""
    import re

    from assistant.telemetry.decorators import traced_delegation

    _install_spy(monkeypatch, spy_provider)

    class S(_FakeSpawner):
        @traced_delegation
        async def delegate(self, sub_role_name: str, task: str) -> str:
            return "ok"

    long_task = "x" * 1000
    s = S("personal", "assistant")
    await s.delegate("researcher", long_task)

    call = spy_provider.calls["trace_delegation"][0]
    assert re.match(r"^sha256:[0-9a-f]{16}$", call["task"]) is not None
    # No fragment of the original task remains.
    assert "x" * 100 not in call["task"]


@pytest.mark.asyncio
async def test_traced_delegation_passes_through_short_task(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.decorators import traced_delegation

    _install_spy(monkeypatch, spy_provider)

    class S(_FakeSpawner):
        @traced_delegation
        async def delegate(self, sub_role_name: str, task: str) -> str:
            return "ok"

    s = S("personal", "assistant")
    boundary_task = "y" * 256  # exactly 256 chars: passes through unchanged
    await s.delegate("researcher", boundary_task)
    assert spy_provider.calls["trace_delegation"][0]["task"] == boundary_task


@pytest.mark.asyncio
async def test_traced_delegation_pushes_sub_role_for_subagent(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """During the awaited call the ContextVar reflects the sub-role."""
    from assistant.telemetry.context import get_assistant_ctx
    from assistant.telemetry.decorators import traced_delegation

    _install_spy(monkeypatch, spy_provider)
    set_assistant_ctx("personal", "assistant")

    observed: list[tuple[str | None, str | None]] = []

    class S(_FakeSpawner):
        @traced_delegation
        async def delegate(self, sub_role_name: str, task: str) -> str:
            observed.append(get_assistant_ctx())
            return "ok"

    s = S("personal", "assistant")
    await s.delegate("researcher", "go")

    # During the awaited body, role is the sub-role.
    assert observed == [("personal", "researcher")]
    # After exit, the parent context is restored.
    assert get_assistant_ctx() == ("personal", "assistant")


@pytest.mark.asyncio
async def test_concurrent_delegations_isolate_sub_roles(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """asyncio.gather over distinct Tasks: each sees its own sub-role.

    Per spec scenario "Concurrent delegations each see their own sub-role"
    + req observability.11 / PEP 567 task-local semantics.
    """
    from assistant.telemetry.context import get_assistant_ctx
    from assistant.telemetry.decorators import traced_delegation

    _install_spy(monkeypatch, spy_provider)
    set_assistant_ctx("personal", "assistant")

    seen: dict[str, tuple[str | None, str | None]] = {}

    class S(_FakeSpawner):
        @traced_delegation
        async def delegate(self, sub_role_name: str, task: str) -> str:
            # await ensures the two coroutines genuinely interleave.
            await asyncio.sleep(0)
            seen[sub_role_name] = get_assistant_ctx()
            await asyncio.sleep(0)
            return f"done:{sub_role_name}"

    s = S("personal", "assistant")

    async def _wrap(role: str, task: str) -> str:
        # PEP 567: spawning in distinct Tasks keeps ContextVar mutations
        # isolated. asyncio.gather handles this by default.
        return await s.delegate(role, task)

    results = await asyncio.gather(
        _wrap("researcher", "find X"),
        _wrap("writer", "draft Y"),
    )
    assert sorted(results) == ["done:researcher", "done:writer"]
    assert seen["researcher"] == ("personal", "researcher")
    assert seen["writer"] == ("personal", "writer")
    # Parent context restored.
    assert get_assistant_ctx() == ("personal", "assistant")
