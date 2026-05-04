"""Tests for extension-registry spec.

Covers all 6 scenarios across 3 requirements in
``openspec/changes/bootstrap-vertical-slice/specs/extension-registry/spec.md``.
Each scenario is parameterized across all 7 stub modules.
"""

from __future__ import annotations

import asyncio
from importlib import import_module

import pytest

from assistant.extensions.base import Extension

STUB_NAMES = [
    "ms_graph",
    "teams",
    "sharepoint",
    "outlook",
    "gmail",
    "gcal",
    "gdrive",
]


@pytest.mark.parametrize("name", STUB_NAMES)
def test_stub_implementation_satisfies_protocol(name: str) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    instance = mod.create_extension({})
    assert isinstance(instance, Extension)


@pytest.mark.parametrize("name", STUB_NAMES)
def test_each_stub_exports_create_extension(name: str) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    assert callable(mod.create_extension)


@pytest.mark.parametrize("name", STUB_NAMES)
def test_stubs_return_empty_tool_lists(name: str) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    instance = mod.create_extension({})
    assert instance.as_langchain_tools() == []
    assert instance.as_ms_agent_tools() == []


@pytest.mark.parametrize("name", STUB_NAMES)
def test_stub_health_check_returns_unknown_health_status(name: str) -> None:
    # Updated for P9 error-resilience: the Extension protocol now returns
    # HealthStatus instead of bool. Stubs return the standard "unknown"
    # status until their real backend probes ship in P5/P14.
    from assistant.core.resilience import HealthState, HealthStatus

    mod = import_module(f"assistant.extensions.{name}")
    instance = mod.create_extension({})
    status = asyncio.run(instance.health_check())
    assert isinstance(status, HealthStatus)
    assert status.state is HealthState.UNKNOWN
    assert status.reason == "extension is a stub"


@pytest.mark.parametrize("name", STUB_NAMES)
def test_scopes_are_stored_on_instance(name: str) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    instance = mod.create_extension({"scopes": ["s1", "s2"]})
    assert instance.scopes == ["s1", "s2"]


@pytest.mark.parametrize("name", STUB_NAMES)
def test_missing_scopes_default_to_empty_list(name: str) -> None:
    mod = import_module(f"assistant.extensions.{name}")
    instance = mod.create_extension({})
    assert instance.scopes == []


def test_instance_name_matches_module(monkeypatch) -> None:
    """Each stub's name attribute should match its module name so the CLI
    can log ``Extensions loaded: gmail, gcal, ...`` correctly."""
    for name in STUB_NAMES:
        mod = import_module(f"assistant.extensions.{name}")
        instance = mod.create_extension({})
        assert instance.name == name
