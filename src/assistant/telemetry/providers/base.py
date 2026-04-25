"""ObservabilityProvider Protocol — the contract every provider implements.

Spec: observability — Observability Provider Contract (spec.md:5-43).

All concrete providers (``noop``, ``langfuse``, and any future
adapter) MUST satisfy this Protocol. The Protocol is decorated with
``@runtime_checkable`` so ``isinstance(obj, ObservabilityProvider)``
works at runtime — used by the test suite to verify compliance.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol, runtime_checkable

# Module-level frozensets give zero-allocation O(1) membership checks
# for enum validation in NoopProvider's hot path (D7).
_VALID_TOOL_KINDS: frozenset[str] = frozenset({"extension", "http"})
_VALID_OPS: frozenset[str] = frozenset(
    {
        "context",
        "fact_write",
        "interaction_write",
        "episode_write",
        "search",
        "export",
    }
)


def _validate_tool_kind(tool_kind: Any) -> None:
    """Raise ``ValueError`` if ``tool_kind`` is not one of the allowed values.

    Per spec scenario "Rejects mis-typed tool_kind": validation MUST
    fire before any span is emitted. The parameter is typed ``Any``
    (not ``str``) because this is an entry-point validator; duck-typed
    dispatch — including ``None`` from a ``kwargs.get("tool_kind")``
    on a NoopProvider call without the required arg — MUST also raise
    rather than silently passing the type check.
    """
    if tool_kind not in _VALID_TOOL_KINDS:
        raise ValueError(
            f"invalid tool_kind={tool_kind!r}; "
            f"expected one of {sorted(_VALID_TOOL_KINDS)}"
        )


def _validate_op(op: Any) -> None:
    """Raise ``ValueError`` if ``op`` is not one of the allowed values.

    Per spec scenario "Rejects mis-typed op value": case mismatch is
    explicitly rejected too — ``op="CONTEXT"`` MUST fail. Same
    ``Any``-typed entry-point rationale as :func:`_validate_tool_kind`.
    """
    if op not in _VALID_OPS:
        raise ValueError(
            f"invalid op={op!r}; expected one of {sorted(_VALID_OPS)}"
        )


@runtime_checkable
class ObservabilityProvider(Protocol):
    """Protocol every concrete telemetry provider implements.

    Nine members total: ``name`` property, ``setup`` lifecycle, four
    first-class ``trace_*`` methods, ``start_span`` escape hatch, plus
    ``flush`` / ``shutdown``.
    """

    name: str

    def setup(self, app: Any = None) -> None:
        """Provider initialisation; called once at app startup."""
        ...

    def trace_llm_call(
        self,
        *,
        model: str,
        persona: str | None,
        role: str | None,
        messages: list[dict[str, Any]] | None,
        input_tokens: int | None,
        output_tokens: int | None,
        duration_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a harness invocation as an LLM call (one span per call)."""
        ...

    def trace_delegation(
        self,
        *,
        parent_role: str | None,
        sub_role: str,
        task: str,
        persona: str | None,
        duration_ms: float,
        outcome: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a delegation hop. ``outcome`` is ``"success"`` or ``"error"``."""
        ...

    def trace_tool_call(
        self,
        *,
        tool_name: str,
        tool_kind: str,
        persona: str | None,
        role: str | None,
        duration_ms: float,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a StructuredTool invocation. ``tool_kind`` ∈ {extension, http}."""
        ...

    def trace_memory_op(
        self,
        *,
        op: str,
        target: str | None,
        persona: str | None,
        duration_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a MemoryManager method call. ``op`` ∈ the fixed enum."""
        ...

    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> AbstractContextManager[Any]:
        """Open an arbitrary named span; escape hatch for non-first-class ops."""
        ...

    def flush(self) -> None:
        """Trigger an immediate send of buffered events."""
        ...

    def shutdown(self) -> None:
        """Drain buffers + release resources during process exit."""
        ...
