"""Advisory perf check for NoopProvider zero-allocation posture.

Spec scenario: "Noop methods have O(1) allocation behavior"
(spec.md:240-244). Categorised as **advisory** — 3-run median MUST
stay within 4 KB tolerance over 10k iterations on typical CI runners,
but a single outlier run MUST NOT fail the CI job.

This file is separate from ``test_noop.py`` so it can be tagged /
skipped independently if a future CI runner proves to be too noisy
for the tracemalloc check.
"""

from __future__ import annotations

import statistics
import tracemalloc


def test_noop_trace_llm_call_zero_allocation() -> None:
    from assistant.telemetry.providers.noop import NoopProvider

    p = NoopProvider()

    def _measure() -> int:
        tracemalloc.start()
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
    assert median < 4096, (
        f"trace_llm_call median allocation over 10k calls is "
        f"{median} bytes (>4 KB tolerance); runs={runs}"
    )


def test_noop_trace_tool_call_zero_allocation_for_valid_kind() -> None:
    """Validation check on tool_kind is allocation-free for the happy path."""
    from assistant.telemetry.providers.noop import NoopProvider

    p = NoopProvider()

    def _measure() -> int:
        tracemalloc.start()
        for _ in range(10_000):
            p.trace_tool_call(
                tool_name="t",
                tool_kind="extension",
                persona="p",
                role="r",
                duration_ms=0.0,
            )
        snap = tracemalloc.take_snapshot()
        tracemalloc.stop()
        return sum(s.size for s in snap.statistics("filename"))

    runs = [_measure() for _ in range(3)]
    median = statistics.median(runs)
    assert median < 4096, (
        f"trace_tool_call median allocation over 10k calls is "
        f"{median} bytes (>4 KB tolerance); runs={runs}"
    )
