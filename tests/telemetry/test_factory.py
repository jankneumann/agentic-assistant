"""Tests for the factory: get_observability_provider() (Task 1.14).

Spec: observability — Graceful Degradation Across Three Levels
(spec.md:45-72) and "Default configuration yields noop"
(spec.md:235-238).

The autouse ``reset_telemetry_singleton`` fixture in
``conftest.py`` clears ``_provider`` and ``_warned_levels`` before
every test so the singleton from D1 doesn't leak between cases.
"""

from __future__ import annotations

import builtins
import logging
import sys
import types
from typing import Any

import pytest


def test_disabled_returns_noop_without_importing_langfuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec scenario: 'Returns noop when LANGFUSE_ENABLED is false'.

    Telemetry must NOT attempt to import langfuse when disabled — the
    cheapest possible path.
    """
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)

    real_import = builtins.__import__
    saw_langfuse_import = {"value": False}

    def _import(name: str, *a: Any, **kw: Any) -> Any:
        if name == "langfuse" or name.startswith("langfuse."):
            saw_langfuse_import["value"] = True
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _import)

    from assistant.telemetry.factory import get_observability_provider

    provider = get_observability_provider()
    assert provider.name == "noop"
    assert saw_langfuse_import["value"] is False


def test_singleton_caches_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    from assistant.telemetry.factory import get_observability_provider

    p1 = get_observability_provider()
    p2 = get_observability_provider()
    assert p1 is p2


def test_returns_noop_on_import_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec scenario: 'Returns noop when langfuse package is missing'."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    real_import = builtins.__import__

    def _import(name: str, *a: Any, **kw: Any) -> Any:
        if name == "langfuse":
            raise ImportError("not installed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _import)
    monkeypatch.delitem(sys.modules, "langfuse", raising=False)
    monkeypatch.delitem(
        sys.modules, "assistant.telemetry.providers.langfuse", raising=False
    )

    from assistant.telemetry.factory import get_observability_provider

    with caplog.at_level(logging.WARNING, logger="assistant.telemetry"):
        provider = get_observability_provider()
    assert provider.name == "noop"
    assert any(
        "langfuse" in rec.message.lower() and "import" in rec.message.lower()
        for rec in caplog.records
    )


def test_returns_noop_on_runtime_init_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec scenario: 'Returns noop when provider init raises'.

    The factory MUST swallow the exception and return a noop, never
    propagating to the caller.
    """
    # Install a fake langfuse module whose constructor blows up.
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    fake_mod = types.ModuleType("langfuse")

    def _boom(**kwargs: Any) -> Any:
        raise RuntimeError("backend unreachable")

    fake_mod.Langfuse = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake_mod)
    monkeypatch.delitem(
        sys.modules, "assistant.telemetry.providers.langfuse", raising=False
    )

    from assistant.telemetry.factory import get_observability_provider

    with caplog.at_level(logging.WARNING, logger="assistant.telemetry"):
        provider = get_observability_provider()
    assert provider.name == "noop"
    assert any("backend unreachable" in rec.message or "init" in rec.message.lower()
               for rec in caplog.records)


def test_one_warning_per_process(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec: warning MUST NOT repeat on subsequent calls."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    real_import = builtins.__import__

    def _import(name: str, *a: Any, **kw: Any) -> Any:
        if name == "langfuse":
            raise ImportError("not installed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _import)
    monkeypatch.delitem(sys.modules, "langfuse", raising=False)
    monkeypatch.delitem(
        sys.modules, "assistant.telemetry.providers.langfuse", raising=False
    )

    from assistant.telemetry.factory import get_observability_provider

    with caplog.at_level(logging.WARNING, logger="assistant.telemetry"):
        get_observability_provider()
        first_count = len(
            [r for r in caplog.records if r.levelno == logging.WARNING]
        )
        get_observability_provider()
        second_count = len(
            [r for r in caplog.records if r.levelno == logging.WARNING]
        )
    # Subsequent calls should not emit the warning again.
    assert second_count == first_count


def test_factory_emits_empty_creds_warning_when_enabled_with_blank(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Iter-2 fix H — empty-but-present credential warning is emitted
    by the factory (not by config.from_env), routed through
    ``_warn_once`` so the rest of the degradation warnings dedup with
    it. The warning identifies the empty env var name(s) so users can
    distinguish this case from the fully-unset disabled case.
    """
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from assistant.telemetry.factory import get_observability_provider

    with caplog.at_level(logging.WARNING, logger="assistant.telemetry"):
        provider = get_observability_provider()

    assert provider.name == "noop"
    msg_blob = "\n".join(rec.message for rec in caplog.records)
    assert "empty" in msg_blob.lower()
    assert "LANGFUSE_PUBLIC_KEY" in msg_blob
    assert "LANGFUSE_SECRET_KEY" in msg_blob


def test_factory_empty_creds_warning_dedups_across_calls(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The empty-creds warning routes through ``_warn_once`` so a
    second ``get_observability_provider()`` call does NOT re-emit it.
    """
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-real")

    from assistant.telemetry import factory as fmod
    from assistant.telemetry.factory import get_observability_provider

    with caplog.at_level(logging.WARNING, logger="assistant.telemetry"):
        get_observability_provider()
        first = sum(
            1 for r in caplog.records if "empty" in r.message.lower()
        )
        # Reset only the singleton so init runs again — _warned_levels
        # MUST persist for the dedup to take effect.
        fmod._provider = None
        get_observability_provider()
        second = sum(
            1 for r in caplog.records if "empty" in r.message.lower()
        )
    assert first == 1
    assert second == 1  # MUST NOT re-emit


def test_factory_no_empty_creds_warning_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When LANGFUSE_ENABLED is false, set-but-blank creds MUST NOT
    trigger the empty-creds warning — the user did not signal intent.
    """
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from assistant.telemetry.factory import get_observability_provider

    with caplog.at_level(logging.WARNING, logger="assistant.telemetry"):
        provider = get_observability_provider()

    assert provider.name == "noop"
    assert not any(
        "empty" in rec.message.lower() for rec in caplog.records
    )


def test_atexit_registered_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory MUST register atexit.register(provider.shutdown) exactly once."""
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)

    registered: list[Any] = []

    def _register(fn: Any) -> Any:
        registered.append(fn)
        return fn

    import atexit

    monkeypatch.setattr(atexit, "register", _register)

    from assistant.telemetry.factory import get_observability_provider

    p = get_observability_provider()
    # Calling again must NOT register a second handler (singleton path).
    get_observability_provider()
    matching = [fn for fn in registered if fn == p.shutdown]
    assert len(matching) == 1


def test_factory_returns_langfuse_when_fully_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://example.test")

    captured: dict[str, Any] = {}

    fake_mod = types.ModuleType("langfuse")

    def _factory(**kwargs: Any) -> Any:
        captured.update(kwargs)

        class _Client:
            def flush(self) -> None: ...
            def shutdown(self) -> None: ...

        return _Client()

    fake_mod.Langfuse = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake_mod)
    monkeypatch.delitem(
        sys.modules, "assistant.telemetry.providers.langfuse", raising=False
    )

    from assistant.telemetry.factory import get_observability_provider

    provider = get_observability_provider()
    assert provider.name == "langfuse"
    assert captured["public_key"] == "pk-lf-test"
