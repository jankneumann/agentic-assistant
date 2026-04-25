"""Tests for LangfuseProvider (Task 1.11).

Spec: observability — Langfuse-backed provider:
- "Langfuse implements the full Protocol surface"
- "Per-op mode flushes each call"
- "Shutdown mode batches events"
- Sanitization is applied at emission time (D5).

These tests use a fake Langfuse client (``FakeLangfuseClient``) so
they pass whether or not the optional ``langfuse`` extra is installed.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest


class _FakeObservation:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.ended = False

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)

    def __enter__(self) -> _FakeObservation:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.ended = True


class _FakeLangfuse:
    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.observations: list[tuple[str, dict[str, Any]]] = []
        self.flushed = 0
        self.shut_down = 0

    @contextmanager
    def start_as_current_observation(
        self, **kwargs: Any
    ) -> Iterator[_FakeObservation]:
        obs = _FakeObservation()
        self.observations.append(("observation", kwargs))
        try:
            yield obs
        finally:
            pass

    def flush(self) -> None:
        self.flushed += 1

    def shutdown(self) -> None:
        self.shut_down += 1


@pytest.fixture
def fake_langfuse_module(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, _FakeLangfuse]]:
    """Install a fake ``langfuse`` module before LangfuseProvider imports it.

    Returns the singleton fake client instance the provider will see.
    """
    holder: dict[str, _FakeLangfuse] = {}

    def _factory(**kwargs: Any) -> _FakeLangfuse:
        client = _FakeLangfuse(**kwargs)
        holder["client"] = client
        return client

    fake_mod = types.ModuleType("langfuse")
    fake_mod.Langfuse = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake_mod)

    # Force-clear cached LangfuseProvider import so it re-reads the fake
    # module on next import.
    monkeypatch.delitem(
        sys.modules, "assistant.telemetry.providers.langfuse", raising=False
    )

    yield holder


def test_lazy_import_fails_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec scenario: 'Returns noop when langfuse package is missing'.

    The provider's ``setup()`` MUST raise ImportError when the langfuse
    SDK is unavailable so the factory's level-2 degradation path can
    catch it.
    """
    import builtins

    real_import = builtins.__import__

    def _import(name: str, *a: Any, **kw: Any) -> Any:
        if name == "langfuse":
            raise ImportError("langfuse not installed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _import)
    monkeypatch.delitem(sys.modules, "langfuse", raising=False)
    monkeypatch.delitem(
        sys.modules, "assistant.telemetry.providers.langfuse", raising=False
    )

    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    provider = LangfuseProvider(cfg)
    with pytest.raises(ImportError):
        provider.setup()


def test_setup_with_fake_module_initialises_client(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=0.7,
    )
    provider = LangfuseProvider(cfg)
    provider.setup()
    client = fake_langfuse_module["client"]
    assert client.init_kwargs["public_key"] == "pk-lf-test"
    assert client.init_kwargs["secret_key"] == "sk-lf-test"
    # base_url is the supported v3 keyword for the host argument.
    assert client.init_kwargs["base_url"] == "https://example.test"
    assert client.init_kwargs["environment"] == "ci"
    assert client.init_kwargs["sample_rate"] == 0.7


def test_provider_implements_protocol(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.base import ObservabilityProvider
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()
    assert isinstance(p, ObservabilityProvider)


def test_trace_llm_call_emits_generation(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()
    p.trace_llm_call(
        model="claude",
        persona="personal",
        role="assistant",
        messages=[{"role": "user", "content": "hi"}],
        input_tokens=5,
        output_tokens=10,
        duration_ms=42.0,
    )
    client = fake_langfuse_module["client"]
    assert len(client.observations) == 1
    _kind, kwargs = client.observations[0]
    assert kwargs.get("as_type") == "generation"
    assert kwargs.get("model") == "claude"


def test_trace_tool_call_validates_kind(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()

    with pytest.raises(ValueError, match="tool_kind"):
        p.trace_tool_call(
            tool_name="x",
            tool_kind="database",
            persona="personal",
            role="assistant",
            duration_ms=1.0,
        )


def test_trace_memory_op_validates_op(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()

    with pytest.raises(ValueError, match="op"):
        p.trace_memory_op(
            op="CONTEXT",
            target="foo",
            persona="personal",
            duration_ms=1.0,
        )


def test_metadata_is_sanitised_at_emission(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    """D5 — sanitize_mapping runs before metadata reaches the SDK."""
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()
    p.trace_tool_call(
        tool_name="gmail.search",
        tool_kind="extension",
        persona="personal",
        role="assistant",
        duration_ms=10.0,
        metadata={"detail": "Bearer " + "a" * 40},
    )
    client = fake_langfuse_module["client"]
    _, kwargs = client.observations[0]
    # The metadata blob must contain the redaction marker.
    md = kwargs.get("metadata") or {}
    found = any("Bearer REDACTED" in str(v) for v in md.values())
    assert found, f"Bearer token not redacted in metadata: {md}"


def test_per_op_flush_mode_calls_flush(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="per_op",
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()
    p.trace_llm_call(
        model="claude",
        persona="personal",
        role="assistant",
        messages=None,
        input_tokens=0,
        output_tokens=0,
        duration_ms=1.0,
    )
    client = fake_langfuse_module["client"]
    assert client.flushed == 1


def test_shutdown_mode_does_not_flush_per_op(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()
    for _ in range(10):
        p.trace_llm_call(
            model="claude",
            persona="personal",
            role="assistant",
            messages=None,
            input_tokens=0,
            output_tokens=0,
            duration_ms=1.0,
        )
    client = fake_langfuse_module["client"]
    assert client.flushed == 0


def test_shutdown_drains(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()
    p.shutdown()
    client = fake_langfuse_module["client"]
    assert client.shut_down == 1


# ---------------------------------------------------------------------------
# Resilience: SDK emission failures MUST NOT propagate (req observability.2).
# Iter-2 fix for IMPL_REVIEW round 1 finding C.
# ---------------------------------------------------------------------------


class _RaisingFakeLangfuse(_FakeLangfuse):
    """A fake whose ``start_as_current_observation`` always raises.

    Stands in for an SDK whose backend is unreachable, whose auth has
    rotated, or whose payload is malformed — every observation enter
    raises a transport-shaped exception. The provider MUST swallow it
    so the application is not crashed by telemetry.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.flush_should_raise = False

    @contextmanager
    def start_as_current_observation(
        self, **kwargs: Any
    ) -> Iterator[Any]:
        raise RuntimeError("simulated SDK transport failure")
        yield  # pragma: no cover — unreachable

    def flush(self) -> None:
        if self.flush_should_raise:
            raise RuntimeError("simulated SDK flush failure")
        super().flush()


@pytest.fixture
def raising_langfuse_module(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, _RaisingFakeLangfuse]]:
    """Install a fake ``langfuse`` module whose SDK calls raise."""
    holder: dict[str, _RaisingFakeLangfuse] = {}

    def _factory(**kwargs: Any) -> _RaisingFakeLangfuse:
        client = _RaisingFakeLangfuse(**kwargs)
        holder["client"] = client
        return client

    fake_mod = types.ModuleType("langfuse")
    fake_mod.Langfuse = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake_mod)
    monkeypatch.delitem(
        sys.modules, "assistant.telemetry.providers.langfuse", raising=False
    )
    yield holder


def _make_provider_with_raising_sdk(
    raising_langfuse_module: dict[str, _RaisingFakeLangfuse],
    flush_mode: str = "shutdown",
) -> Any:
    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    cfg = TelemetryConfig(
        enabled=True,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://example.test",
        environment="ci",
        flush_mode=flush_mode,
        sample_rate=1.0,
    )
    p = LangfuseProvider(cfg)
    p.setup()
    return p


def test_trace_llm_call_swallows_sdk_emission_exceptions(
    raising_langfuse_module: dict[str, _RaisingFakeLangfuse],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per req observability.2 the application MUST NEVER crash due to
    telemetry. SDK emission failures are logged at WARNING and
    swallowed; callers see ``None`` returned as if emission succeeded.
    """
    p = _make_provider_with_raising_sdk(raising_langfuse_module)

    with caplog.at_level("WARNING", logger="assistant.telemetry"):
        result = p.trace_llm_call(
            model="anthropic:claude-sonnet-4-20250514",
            persona="personal",
            role="assistant",
            messages=None,
            input_tokens=10,
            output_tokens=20,
            duration_ms=1.5,
        )
    assert result is None
    assert any(
        "Langfuse emission for span 'llm_call' failed" in rec.message
        for rec in caplog.records
    )


def test_trace_delegation_swallows_sdk_emission_exceptions(
    raising_langfuse_module: dict[str, _RaisingFakeLangfuse],
    caplog: pytest.LogCaptureFixture,
) -> None:
    p = _make_provider_with_raising_sdk(raising_langfuse_module)

    with caplog.at_level("WARNING", logger="assistant.telemetry"):
        p.trace_delegation(
            parent_role="assistant",
            sub_role="researcher",
            task="find X",
            persona="personal",
            duration_ms=1.0,
            outcome="success",
        )
    assert any(
        "Langfuse emission for span 'delegation' failed" in rec.message
        for rec in caplog.records
    )


def test_trace_tool_call_swallows_sdk_emission_exceptions(
    raising_langfuse_module: dict[str, _RaisingFakeLangfuse],
    caplog: pytest.LogCaptureFixture,
) -> None:
    p = _make_provider_with_raising_sdk(raising_langfuse_module)

    with caplog.at_level("WARNING", logger="assistant.telemetry"):
        p.trace_tool_call(
            tool_name="gmail.search",
            tool_kind="extension",
            persona="personal",
            role="assistant",
            duration_ms=1.0,
        )
    assert any(
        "Langfuse emission for span 'tool:gmail.search' failed" in rec.message
        for rec in caplog.records
    )


def test_trace_memory_op_swallows_sdk_emission_exceptions(
    raising_langfuse_module: dict[str, _RaisingFakeLangfuse],
    caplog: pytest.LogCaptureFixture,
) -> None:
    p = _make_provider_with_raising_sdk(raising_langfuse_module)

    with caplog.at_level("WARNING", logger="assistant.telemetry"):
        p.trace_memory_op(
            op="search",
            target="recent decisions",
            persona="personal",
            duration_ms=1.0,
        )
    assert any(
        "Langfuse emission for span 'memory:search' failed" in rec.message
        for rec in caplog.records
    )


def test_flush_swallows_sdk_exceptions(
    raising_langfuse_module: dict[str, _RaisingFakeLangfuse],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Top-level ``flush()`` is also wrapped — a transport failure on
    drain MUST NOT propagate from the provider.
    """
    p = _make_provider_with_raising_sdk(raising_langfuse_module)
    raising_langfuse_module["client"].flush_should_raise = True

    with caplog.at_level("WARNING", logger="assistant.telemetry"):
        p.flush()  # MUST NOT raise
    assert any(
        "Langfuse flush failed" in rec.message for rec in caplog.records
    )


def test_per_op_flush_failure_does_not_propagate(
    raising_langfuse_module: dict[str, _RaisingFakeLangfuse],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per-op mode flushes after each ``trace_*`` call. Even if flush
    fails inside ``_emit_observation`` the trace method MUST return
    cleanly — the same try/except covers the flush path.
    """
    # Use a fake whose enter succeeds (so we reach the flush branch) but
    # whose flush raises. We do this via a subclass of _FakeLangfuse.
    class _FlushRaising(_FakeLangfuse):
        def flush(self) -> None:
            raise RuntimeError("simulated flush failure")

    holder: dict[str, _FlushRaising] = {}

    def _factory(**kwargs: Any) -> _FlushRaising:
        c = _FlushRaising(**kwargs)
        holder["client"] = c
        return c

    fake_mod = types.ModuleType("langfuse")
    fake_mod.Langfuse = _factory  # type: ignore[attr-defined]
    sys.modules["langfuse"] = fake_mod
    sys.modules.pop("assistant.telemetry.providers.langfuse", None)

    try:
        from assistant.telemetry.config import TelemetryConfig
        from assistant.telemetry.providers.langfuse import LangfuseProvider

        cfg = TelemetryConfig(
            enabled=True,
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="https://example.test",
            environment="ci",
            flush_mode="per_op",
            sample_rate=1.0,
        )
        p = LangfuseProvider(cfg)
        p.setup()

        with caplog.at_level("WARNING", logger="assistant.telemetry"):
            p.trace_llm_call(
                model="m",
                persona="personal",
                role="assistant",
                messages=None,
                input_tokens=1,
                output_tokens=2,
                duration_ms=1.0,
            )
        assert any(
            "Langfuse emission for span 'llm_call' failed" in rec.message
            for rec in caplog.records
        )
    finally:
        sys.modules.pop("langfuse", None)


# ---------------------------------------------------------------------------
# Cleanup: dead module-level __getattr__ removed.
# Iter-2 fix for IMPL_REVIEW round 1 finding I.
# ---------------------------------------------------------------------------


def test_module_level_getattr_was_removed(
    fake_langfuse_module: dict[str, _FakeLangfuse],
) -> None:
    """The dead module-level ``__getattr__`` (raised AttributeError, the
    Python default for missing module attributes) was removed in iter-2.
    Looking up a missing attribute MUST still raise AttributeError but
    via the language default rather than via custom code.
    """
    import importlib

    # Reload to ensure we get the post-removal version.
    import assistant.telemetry.providers.langfuse as lf_mod

    importlib.reload(lf_mod)

    assert not hasattr(lf_mod, "__getattr__")
    # Build the attribute name dynamically so neither mypy nor ruff
    # complain about a literal access to a missing attribute — what we
    # care about is the runtime AttributeError behaviour.
    missing_name = "this_attribute_does_not_exist_" + "iter2"
    with pytest.raises(AttributeError):
        getattr(lf_mod, missing_name)
