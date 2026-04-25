"""Tests for the ObservabilityProvider Protocol (Task 1.3).

Spec: observability — Observability Provider Contract (spec.md:5-43).
"""

from __future__ import annotations

import pytest


def test_protocol_is_runtime_checkable() -> None:
    from assistant.telemetry.providers.base import ObservabilityProvider

    # Protocol's runtime_checkable mechanic surfaces _is_runtime_protocol
    # on the class.
    assert getattr(ObservabilityProvider, "_is_runtime_protocol", False)


def test_protocol_declares_required_methods() -> None:
    from assistant.telemetry.providers.base import ObservabilityProvider

    expected = {
        "name",
        "setup",
        "trace_llm_call",
        "trace_delegation",
        "trace_tool_call",
        "trace_memory_op",
        "start_span",
        "flush",
        "shutdown",
    }
    members = set(ObservabilityProvider.__protocol_attrs__)  # type: ignore[attr-defined]
    missing = expected - members
    assert not missing, f"Protocol is missing required members: {sorted(missing)}"


def test_valid_tool_kinds_set() -> None:
    from assistant.telemetry.providers.base import _VALID_TOOL_KINDS

    assert _VALID_TOOL_KINDS == frozenset({"extension", "http"})


def test_valid_ops_set() -> None:
    from assistant.telemetry.providers.base import _VALID_OPS

    assert _VALID_OPS == frozenset(
        {
            "context",
            "fact_write",
            "interaction_write",
            "episode_write",
            "search",
            "export",
        }
    )


def test_invalid_tool_kind_raises_via_helper() -> None:
    """Helper used by both providers to validate ``tool_kind`` (D7)."""
    from assistant.telemetry.providers.base import _validate_tool_kind

    _validate_tool_kind("extension")
    _validate_tool_kind("http")
    with pytest.raises(ValueError, match="tool_kind"):
        _validate_tool_kind("database")


def test_invalid_op_raises_via_helper() -> None:
    from assistant.telemetry.providers.base import _validate_op

    _validate_op("context")
    _validate_op("fact_write")
    with pytest.raises(ValueError, match="op"):
        _validate_op("CONTEXT")  # wrong case is invalid per spec
    with pytest.raises(ValueError, match="op"):
        _validate_op("delete")  # not in the set


def test_isinstance_with_compliant_object() -> None:
    """A duck-typed object with all 9 attributes IS-A ObservabilityProvider."""
    from assistant.telemetry.providers.base import ObservabilityProvider

    class Compliant:
        name = "compliant"

        def setup(self, app: object = None) -> None:
            return None

        def trace_llm_call(self, **kw: object) -> None:
            return None

        def trace_delegation(self, **kw: object) -> None:
            return None

        def trace_tool_call(self, **kw: object) -> None:
            return None

        def trace_memory_op(self, **kw: object) -> None:
            return None

        def start_span(
            self, name: str, attributes: dict[str, object] | None = None
        ) -> object:
            from contextlib import nullcontext

            return nullcontext()

        def flush(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    assert isinstance(Compliant(), ObservabilityProvider)


def test_isinstance_with_partial_object_is_false() -> None:
    from assistant.telemetry.providers.base import ObservabilityProvider

    class Partial:
        name = "partial"

        def setup(self, app: object = None) -> None:
            return None

        # Missing the trace_* methods + start_span + flush + shutdown.

    assert not isinstance(Partial(), ObservabilityProvider)
