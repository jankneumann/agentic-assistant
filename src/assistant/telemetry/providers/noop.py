"""NoopProvider — zero-allocation default provider.

Design D7. Every Protocol method body is a single ``return`` (no
``pass``, no metadata-dict construction, no logging at info level or
above). The methods accept ``**kwargs`` so keyword-only callers don't
raise; the kwargs dict itself is created by Python's call machinery,
not by us. ``trace_tool_call`` and ``trace_memory_op`` validate their
enum argument against module-level frozensets (O(1), allocation-free)
*before* the early return so spec scenario "Rejects mis-typed
tool_kind" / "Rejects mis-typed op value" are honoured even on the
noop path.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from assistant.telemetry.providers.base import _validate_op, _validate_tool_kind


class NoopProvider:
    """The default no-op provider. Cheap, branchless, allocation-free."""

    name: str = "noop"

    def setup(self, app: Any = None) -> None:
        return None

    def trace_llm_call(self, **kwargs: Any) -> None:
        return None

    def trace_delegation(self, **kwargs: Any) -> None:
        return None

    def trace_tool_call(self, **kwargs: Any) -> None:
        # Validation MUST run before the zero-allocation early return
        # (D7 + spec scenario "Rejects mis-typed tool_kind"). The check
        # is unconditional — passing ``tool_kind=None`` (or omitting the
        # required kwarg via duck-typed dispatch) raises ValueError so
        # the noop and Langfuse providers behave symmetrically. Iter-2
        # fix for IMPL_REVIEW round 1 finding G (3-vendor confirmed).
        _validate_tool_kind(kwargs.get("tool_kind"))
        return None

    def trace_memory_op(self, **kwargs: Any) -> None:
        # Same symmetry fix as trace_tool_call above (req observability.1
        # Protocol Contract — "Rejects mis-typed op value", including
        # the ``op is None`` case under duck-typed dispatch).
        _validate_op(kwargs.get("op"))
        return None

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        # No-allocation context manager: yields None and does nothing.
        yield None

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None
