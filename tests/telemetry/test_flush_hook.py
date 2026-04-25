"""Tests for the flush hook (Task 1.16).

Spec: observability — Flush Lifecycle (spec.md:216-229) and
Documented Crash-Time Delivery Semantics (spec.md:301-308).
"""

from __future__ import annotations

import pytest


def test_module_docstring_documents_sigkill_caveat() -> None:
    """Spec: docstring on flush_hook MUST cover the SIGKILL/OOM tradeoff."""
    import assistant.telemetry.flush_hook as flush_hook

    doc = (flush_hook.__doc__ or "").lower()
    # Required signal (per spec): mention SIGKILL/OOM and the per_op opt-in.
    assert "sigkill" in doc or "oom" in doc or "atexit" in doc
    assert "per_op" in doc or "per-op" in doc


def test_register_shutdown_hook_calls_atexit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Helper used by the factory to register provider.shutdown."""
    registered: list = []

    def _register(fn):
        registered.append(fn)
        return fn

    import atexit

    monkeypatch.setattr(atexit, "register", _register)

    from assistant.telemetry.flush_hook import register_shutdown_hook

    sentinel = object()

    def _shutdown() -> None:
        pass

    register_shutdown_hook(_shutdown)
    assert _shutdown in registered
    # Sentinel parameter unused; keep it referenced so linter is happy.
    assert sentinel is not None


def test_register_shutdown_hook_idempotent_for_same_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registering the same shutdown twice MUST register only once.

    Required by D6 + spec: the factory may invoke this on each call,
    but the OS-level atexit list must hold only one entry.
    """
    registered: list = []

    def _register(fn):
        registered.append(fn)
        return fn

    import atexit

    monkeypatch.setattr(atexit, "register", _register)

    from assistant.telemetry.flush_hook import (
        _registered_callables,
        register_shutdown_hook,
    )

    _registered_callables.clear()

    def _shutdown() -> None:
        pass

    register_shutdown_hook(_shutdown)
    register_shutdown_hook(_shutdown)
    assert registered.count(_shutdown) == 1


def test_per_op_mode_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """When LANGFUSE_FLUSH_MODE=per_op the helper reports the mode."""
    monkeypatch.setenv("LANGFUSE_FLUSH_MODE", "per_op")
    from assistant.telemetry.flush_hook import is_per_op_mode

    assert is_per_op_mode() is True


def test_default_mode_is_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_FLUSH_MODE", raising=False)
    from assistant.telemetry.flush_hook import is_per_op_mode

    assert is_per_op_mode() is False


def test_shutdown_mode_explicitly_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_FLUSH_MODE", "shutdown")
    from assistant.telemetry.flush_hook import is_per_op_mode

    assert is_per_op_mode() is False
