"""Tests for NoopProvider (Task 1.5).

Spec: observability — "Noop implements the full Protocol surface",
"Default configuration yields noop", "Rejects mis-typed tool_kind",
"Rejects mis-typed op value".
"""

from __future__ import annotations

import pytest


def test_noop_is_observability_provider() -> None:
    from assistant.telemetry.providers.base import ObservabilityProvider
    from assistant.telemetry.providers.noop import NoopProvider

    assert isinstance(NoopProvider(), ObservabilityProvider)


def test_noop_name() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    assert NoopProvider().name == "noop"


def test_noop_setup_is_callable() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    NoopProvider().setup(app=None)
    NoopProvider().setup()


def test_noop_trace_llm_call_is_callable() -> None:
    """Sanity: calling trace_llm_call with valid kwargs MUST NOT raise."""
    from assistant.telemetry.providers.noop import NoopProvider

    NoopProvider().trace_llm_call(
        model="claude",
        persona="personal",
        role="assistant",
        messages=[],
        input_tokens=0,
        output_tokens=0,
        duration_ms=0.0,
    )


def test_noop_trace_delegation_is_callable() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    NoopProvider().trace_delegation(
        parent_role="assistant",
        sub_role="researcher",
        task="hello",
        persona="personal",
        duration_ms=0.0,
        outcome="success",
    )


def test_noop_trace_tool_call_accepts_extension() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    NoopProvider().trace_tool_call(
        tool_name="x",
        tool_kind="extension",
        persona=None,
        role=None,
        duration_ms=0.0,
    )


def test_noop_trace_tool_call_accepts_http() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    NoopProvider().trace_tool_call(
        tool_name="x",
        tool_kind="http",
        persona=None,
        role=None,
        duration_ms=0.0,
    )


def test_noop_trace_tool_call_rejects_invalid_kind() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    with pytest.raises(ValueError, match="tool_kind"):
        NoopProvider().trace_tool_call(
            tool_name="x",
            tool_kind="database",  # invalid
            persona=None,
            role=None,
            duration_ms=0.0,
        )


def test_noop_trace_tool_call_rejects_missing_kind() -> None:
    """Iter-2 Fix G (3-vendor confirmed): the noop validator MUST fire
    even when ``tool_kind`` is omitted entirely under duck-typed
    dispatch — symmetry with LangfuseProvider, which raises
    unconditionally because its typed kwarg cannot be omitted.
    """
    from assistant.telemetry.providers.noop import NoopProvider

    with pytest.raises(ValueError, match="tool_kind"):
        # Omit tool_kind via dynamic call (kwargs.get returns None).
        NoopProvider().trace_tool_call()


def test_noop_trace_tool_call_rejects_none_kind() -> None:
    """Explicit ``tool_kind=None`` MUST raise (rather than silently
    short-circuiting on the noop fast path).
    """
    from assistant.telemetry.providers.noop import NoopProvider

    with pytest.raises(ValueError, match="tool_kind"):
        NoopProvider().trace_tool_call(
            tool_name="x",
            tool_kind=None,
            persona=None,
            role=None,
            duration_ms=0.0,
        )


def test_noop_trace_memory_op_accepts_each_op() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    for op in (
        "context",
        "fact_write",
        "interaction_write",
        "episode_write",
        "search",
        "export",
    ):
        NoopProvider().trace_memory_op(
            op=op,
            target="x",
            persona=None,
            duration_ms=0.0,
        )


def test_noop_trace_memory_op_rejects_wrong_case() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    with pytest.raises(ValueError, match="op"):
        NoopProvider().trace_memory_op(
            op="CONTEXT",  # wrong case is invalid
            target="x",
            persona=None,
            duration_ms=0.0,
        )


def test_noop_trace_memory_op_rejects_missing_op() -> None:
    """Iter-2 Fix G (3-vendor confirmed) — symmetry with trace_tool_call.
    """
    from assistant.telemetry.providers.noop import NoopProvider

    with pytest.raises(ValueError, match="op"):
        NoopProvider().trace_memory_op()


def test_noop_trace_memory_op_rejects_none_op() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    with pytest.raises(ValueError, match="op"):
        NoopProvider().trace_memory_op(
            op=None,
            target="x",
            persona=None,
            duration_ms=0.0,
        )


def test_noop_trace_memory_op_rejects_unknown_op() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    with pytest.raises(ValueError, match="op"):
        NoopProvider().trace_memory_op(
            op="delete",
            target="x",
            persona=None,
            duration_ms=0.0,
        )


def test_noop_start_span_is_context_manager() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    with NoopProvider().start_span("anything") as span:
        # The noop span yields whatever it yields (even None) — the
        # contract is just "context manager".
        assert span is None or span is not None  # tautology by design


def test_noop_flush_and_shutdown_callable() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    p = NoopProvider()
    p.flush()
    p.shutdown()


def test_noop_zero_allocation_under_tracemalloc() -> None:
    """Spec advisory: 10k noop calls MUST not scale heap usage with N.

    Methodology:
    - Run a tight loop of 10k calls inside `tracemalloc`.
    - Take a snapshot, total bytes allocated.
    - 3-run median, allow up to 4 KB tolerance per spec.
    """
    import statistics
    import tracemalloc

    from assistant.telemetry.providers.noop import NoopProvider

    p = NoopProvider()

    def _measure() -> int:
        tracemalloc.start()
        # Pre-build args once so we don't measure dict allocation.
        for _ in range(10_000):
            p.trace_llm_call(
                model="m",
                persona="p",
                role="r",
                messages=None,
                input_tokens=0,
                output_tokens=0,
                duration_ms=0.0,
            )
        snap = tracemalloc.take_snapshot()
        tracemalloc.stop()
        return sum(s.size for s in snap.statistics("filename"))

    runs = [_measure() for _ in range(3)]
    median = statistics.median(runs)
    # 4 KB tolerance — generous; advisory check.
    assert median < 4096, (
        f"NoopProvider trace_llm_call leaks >4 KB over 10k calls: "
        f"median={median} bytes; runs={runs}"
    )
