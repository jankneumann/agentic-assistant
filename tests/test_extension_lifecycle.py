"""Tests for the P10 ``extension-lifecycle`` change.

Covers:

- extension-registry / "Extension Protocol" (hook-less extensions
  still satisfy the Protocol and load unchanged)
- extension-registry / "Extension Lifecycle Hooks" (ExtensionBase
  no-op defaults, stub hooks, MS extension shutdown + refresh wiring)
- persona-registry / "Extension Initialization and Shutdown Lifecycle"
  (initialize order, failure isolation, sync/async boundary, shutdown
  reverse order + idempotence + failure containment, atexit
  registration)
- graph-client / "Proactive Credential Refresh Method"
"""

from __future__ import annotations

import atexit
import textwrap
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from assistant.core.persona import PersonaConfig, PersonaRegistry
from assistant.extensions.base import Extension, ExtensionBase
from tests.mocks.graph_client import MockGraphClient

# Module-level event ledger the synthetic private extensions append to
# (same cross-module hook pattern as
# tests/test_persona_registry_factory_contract.py).
_events: list[str] = []


def _record(event: str) -> None:
    _events.append(event)


@pytest.fixture(autouse=True)
def _clear_events() -> None:
    _events.clear()


_EXT_TEMPLATE = """
def create_extension(config, *, persona=None):
    from tests.test_extension_lifecycle import _record

    class _Ext:
        name = {name!r}

        def tool_specs(self):
            return []

        async def health_check(self):
            from assistant.core.resilience import (
                default_health_status_for_unimplemented,
            )
            return default_health_status_for_unimplemented(self.name)

{extra_methods}
    return _Ext()
"""

_ASYNC_HOOKS = """
        async def initialize(self):
            _record("init:" + self.name)

        async def shutdown(self):
            _record("shutdown:" + self.name)
"""

_FAILING_INIT = """
        async def initialize(self):
            _record("init-attempt:" + self.name)
            raise RuntimeError("boom during initialize")

        async def shutdown(self):
            _record("shutdown:" + self.name)
"""

_SYNC_INIT = """
        def initialize(self):
            _record("sync-init:" + self.name)
"""

_FAILING_SHUTDOWN = """
        async def initialize(self):
            _record("init:" + self.name)

        async def shutdown(self):
            _record("shutdown-attempt:" + self.name)
            raise RuntimeError("boom during shutdown")
"""

_NO_HOOKS = ""


def _make_persona(
    tmp_path: Path,
    persona_name: str,
    ext_sources: dict[str, str],
) -> PersonaConfig:
    """Build a PersonaConfig whose extensions load from a tmp dir.

    ``ext_sources`` maps module name → extra method block rendered
    into the private extension template.
    """
    extensions_dir = tmp_path / "extensions"
    extensions_dir.mkdir(parents=True, exist_ok=True)
    for mod_name, extra in ext_sources.items():
        (extensions_dir / f"{mod_name}.py").write_text(
            textwrap.dedent(
                _EXT_TEMPLATE.format(name=mod_name, extra_methods=extra)
            )
        )
    # P13 security-hardening: write an integrity manifest so lifecycle
    # tests exercise the verified-load path without UNVERIFIED warnings.
    from assistant.core.extension_integrity import generate_manifest

    generate_manifest(extensions_dir)
    return PersonaConfig(
        name=persona_name,
        display_name=persona_name,
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={},
        tool_sources={},
        extensions=[
            {"name": mod, "module": mod, "config": {}} for mod in ext_sources
        ],
        extensions_dir=extensions_dir,
    )


# ── persona-registry: initialize called post-load, in order ──────────


def test_initialize_called_in_declaration_order(tmp_path: Path) -> None:
    persona = _make_persona(
        tmp_path,
        "lc_order",
        {"ext_a": _ASYNC_HOOKS, "ext_b": _ASYNC_HOOKS},
    )
    registry = PersonaRegistry(tmp_path / "personas")
    loaded = registry.load_extensions(persona)

    assert [e.name for e in loaded] == ["ext_a", "ext_b"]
    assert _events == ["init:ext_a", "init:ext_b"]


def test_failing_initialize_disables_only_that_extension(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    persona = _make_persona(
        tmp_path,
        "lc_fail",
        {"ext_a": _FAILING_INIT, "ext_b": _ASYNC_HOOKS},
    )
    registry = PersonaRegistry(tmp_path / "personas")
    with caplog.at_level("WARNING"):
        loaded = registry.load_extensions(persona)

    # Persona load did not raise; only the sibling survived.
    assert [e.name for e in loaded] == ["ext_b"]
    # WARNING names the failing extension.
    assert any(
        "ext_a" in rec.message and "initialize" in rec.message
        for rec in caplog.records
    )
    # Best-effort shutdown of the partially-initialized instance ran.
    assert "shutdown:ext_a" in _events
    assert "init:ext_b" in _events


def test_extension_without_hooks_loads_unchanged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Structural (hook-less) private extensions keep loading — and
    still satisfy the runtime-checkable Protocol."""
    persona = _make_persona(tmp_path, "lc_nohooks", {"ext_plain": _NO_HOOKS})
    registry = PersonaRegistry(tmp_path / "personas")
    with caplog.at_level("WARNING"):
        loaded = registry.load_extensions(persona)

    assert len(loaded) == 1
    assert loaded[0].name == "ext_plain"
    assert isinstance(loaded[0], Extension)
    assert not caplog.records  # no warnings about missing hooks


def test_sync_initialize_hook_is_tolerated(tmp_path: Path) -> None:
    """An out-of-tree extension with a *sync* initialize() still works
    (design D2 tolerant invocation)."""
    persona = _make_persona(tmp_path, "lc_sync", {"ext_s": _SYNC_INIT})
    registry = PersonaRegistry(tmp_path / "personas")
    loaded = registry.load_extensions(persona)

    assert [e.name for e in loaded] == ["ext_s"]
    assert _events == ["sync-init:ext_s"]


# ── persona-registry: sync/async boundary ────────────────────────────


async def test_sync_load_extensions_rejects_running_loop(
    tmp_path: Path,
) -> None:
    persona = _make_persona(tmp_path, "lc_loop", {"ext_a": _ASYNC_HOOKS})
    registry = PersonaRegistry(tmp_path / "personas")
    with pytest.raises(RuntimeError, match="load_extensions_async"):
        registry.load_extensions(persona)


async def test_load_extensions_async_inside_loop(tmp_path: Path) -> None:
    persona = _make_persona(tmp_path, "lc_async", {"ext_a": _ASYNC_HOOKS})
    registry = PersonaRegistry(tmp_path / "personas")
    loaded = await registry.load_extensions_async(persona)

    assert [e.name for e in loaded] == ["ext_a"]
    assert _events == ["init:ext_a"]


# ── persona-registry: shutdown handling ──────────────────────────────


async def test_shutdown_runs_in_reverse_order_and_is_idempotent(
    tmp_path: Path,
) -> None:
    persona = _make_persona(
        tmp_path,
        "lc_shutdown",
        {"ext_a": _ASYNC_HOOKS, "ext_b": _ASYNC_HOOKS},
    )
    registry = PersonaRegistry(tmp_path / "personas")
    await registry.load_extensions_async(persona)

    _events.clear()
    await registry.shutdown_extensions()
    assert _events == ["shutdown:ext_b", "shutdown:ext_a"]

    # Second call: active list already drained — no hook runs again.
    _events.clear()
    await registry.shutdown_extensions()
    assert _events == []


async def test_shutdown_failure_is_contained(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    persona = _make_persona(
        tmp_path,
        "lc_shutfail",
        {"ext_a": _ASYNC_HOOKS, "ext_b": _FAILING_SHUTDOWN},
    )
    registry = PersonaRegistry(tmp_path / "personas")
    await registry.load_extensions_async(persona)

    _events.clear()
    with caplog.at_level("WARNING"):
        await registry.shutdown_extensions()

    # b (reverse order first) failed; a still shut down.
    assert _events == ["shutdown-attempt:ext_b", "shutdown:ext_a"]
    assert any(
        "ext_b" in rec.message and "shutdown" in rec.message
        for rec in caplog.records
    )


def test_atexit_handler_registered_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered: list[Any] = []
    monkeypatch.setattr(atexit, "register", registered.append)

    persona_a = _make_persona(tmp_path / "p1", "lc_atexit1", {"ext_a": _ASYNC_HOOKS})
    persona_b = _make_persona(tmp_path / "p2", "lc_atexit2", {"ext_b": _ASYNC_HOOKS})
    registry = PersonaRegistry(tmp_path / "personas")

    registry.load_extensions(persona_a)
    registry.load_extensions(persona_b)

    assert registered == [registry._atexit_shutdown]


def test_atexit_bridge_drains_active_extensions(tmp_path: Path) -> None:
    persona = _make_persona(tmp_path, "lc_bridge", {"ext_a": _ASYNC_HOOKS})
    registry = PersonaRegistry(tmp_path / "personas")
    registry.load_extensions(persona)

    _events.clear()
    registry._atexit_shutdown()
    assert _events == ["shutdown:ext_a"]
    # Drained: a second bridge call is a no-op.
    _events.clear()
    registry._atexit_shutdown()
    assert _events == []


# ── extension-registry: ExtensionBase + stub hooks ───────────────────


async def test_extension_base_defaults_are_noop() -> None:
    base = ExtensionBase()
    # The defaults are awaitable no-ops (return None; mypy enforces
    # the -> None annotation, so just awaiting is the full check).
    await base.initialize()
    await base.shutdown()
    await base.refresh_credentials()


@pytest.mark.parametrize("name", ["gmail", "gcal", "gdrive"])
async def test_stub_extensions_carry_noop_hooks(name: str) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    ext = mod.create_extension({})
    assert isinstance(ext, ExtensionBase)
    await ext.initialize()
    await ext.shutdown()
    await ext.refresh_credentials()


# ── extension-registry: MS extension lifecycle wiring ────────────────

_MS_MODULES = ["ms_graph", "outlook", "teams", "sharepoint"]


@pytest.mark.parametrize("name", _MS_MODULES)
async def test_ms_extension_shutdown_closes_client(name: str) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    client = MockGraphClient()
    ext = mod.create_extension({}, client=client)

    await ext.shutdown()

    assert client.closed is True
    assert ("aclose", (), {}) in client.calls


@pytest.mark.parametrize("name", _MS_MODULES)
async def test_ms_extension_refresh_delegates_to_client(name: str) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    client = MockGraphClient()
    refreshed: list[bool] = []

    async def _refresh() -> None:
        refreshed.append(True)

    client.refresh_credentials = _refresh  # type: ignore[attr-defined]
    ext = mod.create_extension({}, client=client)

    await ext.refresh_credentials()
    assert refreshed == [True]


@pytest.mark.parametrize("name", _MS_MODULES)
async def test_ms_extension_refresh_tolerates_client_without_method(
    name: str,
) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    client = MockGraphClient()
    assert not hasattr(client, "refresh_credentials")
    ext = mod.create_extension({}, client=client)

    # MUST NOT raise (extension-registry / "MS extension
    # refresh_credentials tolerates a client without the method").
    await ext.refresh_credentials()


@pytest.mark.parametrize("name", _MS_MODULES)
async def test_ms_extension_initialize_is_noop(name: str) -> None:
    """No eager token acquisition at persona load (design D7)."""
    mod = import_module(f"assistant.extensions.{name}")
    client = MockGraphClient()
    ext = mod.create_extension({}, client=client)

    await ext.initialize()
    assert client.calls == []


# ── graph-client: proactive refresh method ───────────────────────────


class _RecordingStrategy:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool]] = []

    async def acquire_token(
        self, scopes: list[str], *, force_refresh: bool = False
    ) -> str:
        self.calls.append((list(scopes), force_refresh))
        return "tok-123"


async def test_graph_client_refresh_credentials_forces_refresh() -> None:
    from assistant.core.graph_client import GraphClient

    strategy = _RecordingStrategy()
    client = GraphClient(
        extension_name="lifecycle_test",
        strategy=strategy,
        scopes=["S1"],
    )
    try:
        await client.refresh_credentials()
    finally:
        await client.aclose()

    assert strategy.calls == [(["S1"], True)]


# ── protocol compatibility guard ─────────────────────────────────────


def test_hookless_class_still_satisfies_protocol() -> None:
    """Adding lifecycle hooks to the required Protocol surface would
    break this — the runtime_checkable isinstance must keep passing
    for structural implementations without hooks (design D1)."""

    class _Legacy:
        name = "legacy"

        def tool_specs(self) -> list[Any]:
            return []

        async def health_check(self) -> Any:
            return None

    assert isinstance(_Legacy(), Extension)
    assert not hasattr(_Legacy(), "initialize")
