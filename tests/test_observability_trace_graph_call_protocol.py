"""Protocol-shape tests for ``ObservabilityProvider.trace_graph_call``.

Concrete provider impls (NoopProvider + LangfuseProvider) and their
attribute behavior land in wp-foundation-impls. This file covers ONLY
the Protocol-side requirements:

- the method is declared on ``ObservabilityProvider``
- it has the kwargs the modified spec mandates
- ``_VALID_TOOL_KINDS`` accepts ``"graph"`` (so callers may use
  ``trace_tool_call(tool_kind="graph", ...)`` without a validator
  rejection)
"""

from __future__ import annotations

import inspect

import pytest

from assistant.telemetry.providers.base import (
    _VALID_GRAPH_METHODS,
    _VALID_TOOL_KINDS,
    ObservabilityProvider,
)


def test_trace_graph_call_is_declared_on_protocol() -> None:
    """The Protocol MUST declare ``trace_graph_call``.

    Spec scenario: observability MODIFIED / Observability Provider
    Contract.
    """
    assert hasattr(ObservabilityProvider, "trace_graph_call"), (
        "ObservabilityProvider Protocol missing trace_graph_call method"
    )


def test_trace_graph_call_required_kwargs() -> None:
    """``trace_graph_call`` MUST expose the spec-mandated kwargs.

    The MODIFIED requirement says the method takes:
    ``extension_name, method, path, status_code, duration_ms,
    breaker_key, request_id=None, retry_attempt=0,
    bytes_streamed=None, error=None, metadata=None``.

    All MUST be keyword-only.
    """
    sig = inspect.signature(ObservabilityProvider.trace_graph_call)
    params = sig.parameters

    required = {
        "extension_name",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "breaker_key",
        "request_id",
        "retry_attempt",
        "bytes_streamed",
        "error",
        "metadata",
    }
    actual = set(params) - {"self"}
    missing = required - actual
    assert not missing, f"trace_graph_call missing kwargs: {sorted(missing)}"

    # Every spec-mandated parameter MUST be keyword-only — positional
    # arg ordering would be an undocumented ABI promise.
    for name in required:
        param = params[name]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"trace_graph_call.{name} MUST be keyword-only "
            f"(got kind={param.kind!r})"
        )


def test_optional_kwargs_have_documented_defaults() -> None:
    """Optional kwargs MUST default per spec to keep call sites brief."""
    sig = inspect.signature(ObservabilityProvider.trace_graph_call)
    expected_defaults = {
        "request_id": None,
        "retry_attempt": 0,
        "bytes_streamed": None,
        "error": None,
        "metadata": None,
    }
    for name, default in expected_defaults.items():
        assert sig.parameters[name].default == default, (
            f"trace_graph_call.{name} default MUST be {default!r}"
        )


# ── Validator widening ───────────────────────────────────────────────


def test_tool_kind_validator_accepts_graph() -> None:
    """``_VALID_TOOL_KINDS`` MUST accept ``"graph"`` per the modified spec.

    The trace_tool_call ``tool_kind`` set widened from {extension, http}
    to {extension, http, graph} so callers may use trace_tool_call as a
    lower-fidelity alternative to trace_graph_call without tripping the
    validator.
    """
    assert "graph" in _VALID_TOOL_KINDS
    assert "extension" in _VALID_TOOL_KINDS
    assert "http" in _VALID_TOOL_KINDS


@pytest.mark.parametrize("verb", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_graph_method_validator_accepts_each_verb(verb: str) -> None:
    """``_VALID_GRAPH_METHODS`` MUST accept the five HTTP verbs the spec lists."""
    assert verb in _VALID_GRAPH_METHODS


def test_graph_method_validator_rejects_oddities() -> None:
    """Methods MS Graph never emits MUST NOT silently slip through."""
    assert "OPTIONS" not in _VALID_GRAPH_METHODS
    assert "TRACE" not in _VALID_GRAPH_METHODS
    assert "HEAD" not in _VALID_GRAPH_METHODS
