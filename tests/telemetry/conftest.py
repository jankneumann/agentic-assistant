"""Pytest fixtures for the telemetry test suite (D11).

Two fixtures:

1. ``reset_telemetry_singleton`` (autouse) — resets
   ``assistant.telemetry.factory._provider`` and the one-shot warning
   tracker before each test. Without this fixture the module-level
   singleton from D1 leaks between tests, which would invalidate
   level-2 ImportError tests that rely on a fresh call to
   ``_init_provider``.

2. ``spy_provider`` (opt-in) — a ``SpyProvider`` subclass of
   ``NoopProvider`` that records every Protocol-method call into an
   in-memory ``calls`` dict for later inspection. Used by tests that
   need to assert "this call site emitted a ``trace_*`` with these
   kwargs".
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def reset_telemetry_singleton() -> None:
    """Clear the factory singleton + warning-tracker between tests.

    Imported lazily so the fixture works even when the factory module
    is not yet importable (TDD: tests for config and protocol come
    before the factory exists).
    """
    try:
        from assistant.telemetry import factory
    except ImportError:
        return
    factory._provider = None
    factory._warned_levels = set()


class SpyProvider:
    """Records every Protocol method call for test assertion.

    Inherits zero-allocation posture for any method not explicitly
    overridden — but here every first-class method is overridden so the
    spy can capture calls. Validation (tool_kind / op enum) still runs
    so spec-required ``ValueError`` paths fire.
    """

    name: str = "spy"

    def __init__(self) -> None:
        self.calls: dict[str, list[dict[str, Any]]] = {
            "trace_llm_call": [],
            "trace_delegation": [],
            "trace_tool_call": [],
            "trace_memory_op": [],
            "start_span": [],
            "flush": [],
            "shutdown": [],
            "setup": [],
        }

    def setup(self, app: Any = None) -> None:
        self.calls["setup"].append({"app": app})

    def trace_llm_call(self, **kwargs: Any) -> None:
        self.calls["trace_llm_call"].append(kwargs)

    def trace_delegation(self, **kwargs: Any) -> None:
        self.calls["trace_delegation"].append(kwargs)

    def trace_tool_call(self, **kwargs: Any) -> None:
        from assistant.telemetry.providers.base import _VALID_TOOL_KINDS

        if kwargs.get("tool_kind") not in _VALID_TOOL_KINDS:
            raise ValueError(
                f"invalid tool_kind={kwargs.get('tool_kind')!r}; "
                f"expected one of {sorted(_VALID_TOOL_KINDS)}"
            )
        self.calls["trace_tool_call"].append(kwargs)

    def trace_memory_op(self, **kwargs: Any) -> None:
        from assistant.telemetry.providers.base import _VALID_OPS

        if kwargs.get("op") not in _VALID_OPS:
            raise ValueError(
                f"invalid op={kwargs.get('op')!r}; "
                f"expected one of {sorted(_VALID_OPS)}"
            )
        self.calls["trace_memory_op"].append(kwargs)

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> Any:
        from contextlib import contextmanager

        self.calls["start_span"].append({"name": name, "attributes": attributes})

        @contextmanager
        def _cm() -> Any:
            yield None

        return _cm()

    def flush(self) -> None:
        self.calls["flush"].append({})

    def shutdown(self) -> None:
        self.calls["shutdown"].append({})


@pytest.fixture
def spy_provider() -> SpyProvider:
    return SpyProvider()
