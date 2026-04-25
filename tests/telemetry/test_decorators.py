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
async def test_traced_harness_emits_token_counts_from_last_usage(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """When the harness body stashes ``self._last_usage``, the decorator
    forwards those token counts to ``trace_llm_call``. Iter-2 fix for
    IMPL_REVIEW round 1 finding A — the spec (req observability.3)
    requires ``input_tokens`` / ``output_tokens`` on the trace call.
    """
    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            self._last_usage = (123, 456)
            return "ok"

    h = H("personal", "assistant", "x:y")
    await h.invoke(object(), "hi")

    call = spy_provider.calls["trace_llm_call"][0]
    assert call["input_tokens"] == 123
    assert call["output_tokens"] == 456


@pytest.mark.asyncio
async def test_traced_harness_emits_zero_tokens_when_usage_not_recorded(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """When the harness body does not set ``_last_usage``, the decorator
    records ``(0, 0)`` rather than ``None`` — this satisfies req
    observability.3's MUST-include contract without inventing values.
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
    nothing was stashed), not ``None``.
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
async def test_traced_harness_clears_last_usage_after_consume(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Each invocation reads + clears ``_last_usage`` so a subsequent
    invoke that fails to record fresh usage does not see stale values.
    """
    from assistant.telemetry.decorators import traced_harness

    _install_spy(monkeypatch, spy_provider)

    class H(_FakeHarness):
        recorded_first_call = False

        @traced_harness
        async def invoke(self, agent: Any, message: str) -> str:
            if not self.recorded_first_call:
                self._last_usage = (10, 20)
                self.recorded_first_call = True
            # Second invocation does NOT set _last_usage.
            return "ok"

    h = H("personal", "assistant", "x:y")
    await h.invoke(object(), "first")
    await h.invoke(object(), "second")

    calls = spy_provider.calls["trace_llm_call"]
    assert calls[0]["input_tokens"] == 10
    assert calls[0]["output_tokens"] == 20
    # Stale stash MUST not leak into the second call.
    assert calls[1]["input_tokens"] == 0
    assert calls[1]["output_tokens"] == 0


def test_extract_usage_handles_langchain_core_usage_metadata() -> None:
    """``_extract_usage`` reads the modern ``usage_metadata`` attribute
    that LangChain Core 0.3+ puts on ``AIMessage``.
    """
    from assistant.harnesses.sdk.deep_agents import _extract_usage

    msg = type("Msg", (), {})()
    msg.usage_metadata = {"input_tokens": 7, "output_tokens": 11}
    in_tok, out_tok = _extract_usage([msg])
    assert (in_tok, out_tok) == (7, 11)


def test_extract_usage_handles_legacy_response_metadata_token_usage() -> None:
    """Older LangChain releases stash usage under
    ``response_metadata.token_usage`` with OpenAI-style keys.
    """
    from assistant.harnesses.sdk.deep_agents import _extract_usage

    msg = type("Msg", (), {})()
    msg.response_metadata = {
        "token_usage": {"prompt_tokens": 13, "completion_tokens": 17}
    }
    in_tok, out_tok = _extract_usage([msg])
    assert (in_tok, out_tok) == (13, 17)


def test_extract_usage_sums_across_multiple_messages() -> None:
    """When a result contains multiple assistant messages (e.g. tool-use
    iterations), token counts MUST be summed.
    """
    from assistant.harnesses.sdk.deep_agents import _extract_usage

    m1 = type("Msg", (), {})()
    m1.usage_metadata = {"input_tokens": 5, "output_tokens": 6}
    m2 = type("Msg", (), {})()
    m2.usage_metadata = {"input_tokens": 7, "output_tokens": 8}
    in_tok, out_tok = _extract_usage([m1, m2])
    assert (in_tok, out_tok) == (12, 14)


def test_extract_usage_returns_zeros_when_no_usage_present() -> None:
    """Messages with neither modern nor legacy usage metadata yield
    ``(0, 0)`` — never ``None``.
    """
    from assistant.harnesses.sdk.deep_agents import _extract_usage

    msg = type("Msg", (), {})()
    in_tok, out_tok = _extract_usage([msg])
    assert (in_tok, out_tok) == (0, 0)


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
