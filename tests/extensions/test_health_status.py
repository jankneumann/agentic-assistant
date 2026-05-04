"""Tests for the widened Extension.health_check() protocol returning
HealthStatus, and the runtime conformance guard installed by the persona
registry.

Spec coverage: extension-registry.ExtensionHealthCheckReturnsHealthStatus.{1,2,3,4},
extension-registry.StubImplementations.StubHealthCheckReturnsUNKNOWN.
"""

from __future__ import annotations

import asyncio
import typing
from typing import Any

import pytest

from assistant.core.persona import _install_health_check_conformance_guard
from assistant.core.resilience import (
    CircuitBreaker,
    HealthState,
    HealthStatus,
    health_status_from_breaker,
)
from assistant.extensions.base import Extension
from assistant.extensions.gcal import create_extension as create_gcal
from assistant.extensions.gdrive import create_extension as create_gdrive
from assistant.extensions.gmail import create_extension as create_gmail
from assistant.extensions.ms_graph import create_extension as create_ms_graph
from assistant.extensions.outlook import create_extension as create_outlook
from assistant.extensions.sharepoint import create_extension as create_sharepoint
from assistant.extensions.teams import create_extension as create_teams

ALL_STUBS = [
    ("ms_graph", create_ms_graph),
    ("teams", create_teams),
    ("sharepoint", create_sharepoint),
    ("outlook", create_outlook),
    ("gmail", create_gmail),
    ("gcal", create_gcal),
    ("gdrive", create_gdrive),
]


@pytest.mark.parametrize(("name", "factory"), ALL_STUBS)
def test_stub_returns_unknown_health_status(
    name: str, factory: Any,
) -> None:
    # Spec: extension-registry.ExtensionHealthCheckReturnsHealthStatus.2
    # Spec: extension-registry.StubImplementations.StubHealthCheckReturnsUNKNOWN
    ext = factory({})

    async def _drive() -> HealthStatus:
        return await ext.health_check()

    status = asyncio.run(_drive())
    assert isinstance(status, HealthStatus)
    assert status.state is HealthState.UNKNOWN
    assert status.reason == "extension is a stub"


def test_protocol_return_type_is_health_status() -> None:
    # Spec: extension-registry.ExtensionHealthCheckReturnsHealthStatus.1
    hints = typing.get_type_hints(Extension.health_check)
    assert hints["return"] is HealthStatus


def test_extension_can_derive_health_status_from_breaker() -> None:
    # Spec: extension-registry.ExtensionHealthCheckReturnsHealthStatus.3
    breaker = CircuitBreaker(key="extension:gmail")
    status = health_status_from_breaker(breaker, key="extension:gmail")
    assert status.breaker_key == "extension:gmail"
    assert status.state is HealthState.OK


def test_runtime_conformance_check_rejects_bool() -> None:
    # Spec: extension-registry.ExtensionHealthCheckReturnsHealthStatus.4
    class LegacyExtension:
        name = "legacy-private"

        def as_langchain_tools(self) -> list[Any]:
            return []

        def as_ms_agent_tools(self) -> list[Any]:
            return []

        async def health_check(self) -> bool:
            return True  # legacy out-of-tree extension that was not migrated

    ext = LegacyExtension()
    _install_health_check_conformance_guard(ext)

    async def _probe() -> Any:
        return await ext.health_check()

    with pytest.raises(TypeError) as exc_info:
        asyncio.run(_probe())
    msg = str(exc_info.value)
    assert "legacy-private" in msg
    assert "HealthStatus" in msg
    assert "default_health_status_for_unimplemented" in msg
    assert "docs/gotchas.md" in msg


def test_runtime_conformance_guard_self_removes_after_success() -> None:
    """After a successful probe the guard unwraps so subsequent calls have
    no overhead."""

    class ConformingExtension:
        name = "conforming"

        def as_langchain_tools(self) -> list[Any]:
            return []

        def as_ms_agent_tools(self) -> list[Any]:
            return []

        async def health_check(self) -> HealthStatus:
            from assistant.core.resilience import default_health_status_for_unimplemented
            return default_health_status_for_unimplemented(self.name)

    ext = ConformingExtension()
    original_method = ext.health_check
    _install_health_check_conformance_guard(ext)
    # After install, the method has been replaced with the guard wrapper.
    assert ext.health_check is not original_method

    async def _probe() -> Any:
        return await ext.health_check()

    asyncio.run(_probe())
    # After first successful probe the guard self-removes; the underlying
    # bound method is back in place. We compare bound methods by their
    # __func__ / __self__ tuple since equality semantics on bound methods
    # already compare these.
    assert ext.health_check.__func__ is ConformingExtension.health_check  # type: ignore[attr-defined]
