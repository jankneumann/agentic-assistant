"""Tests for endpoint health checks (P20 local-inference-node).

Covers the model-provider delta requirements "Endpoint Health
Configuration" and "Health-Filtered Resolution": ``health:`` parsing +
validation, the TTL-cached ``EndpointHealthMonitor`` (httpx
MockTransport — no network), skip-unhealthy resolution with cloud
fallback, optimistic UNKNOWN handling, and the fail-closed guarantee
for privacy-tagged requests.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from assistant.core.capabilities.health import (
    DEFAULT_HEALTH_PATH,
    DEFAULT_HEALTH_TIMEOUT,
    DEFAULT_HEALTH_TTL,
    EndpointHealth,
    EndpointHealthMonitor,
    HealthStatus,
    _reset_default_health_monitor,
    default_health_monitor,
    parse_endpoint_health,
    probe_url,
)
from assistant.core.capabilities.models import (
    ModelRef,
    ModelRegistryError,
    ModelRequest,
    ModelResolutionError,
    RegistryModelProvider,
    parse_model_registry,
)


@pytest.fixture(autouse=True)
def _isolate_default_monitor():
    _reset_default_health_monitor()
    yield
    _reset_default_health_monitor()


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _registry_raw() -> dict[str, Any]:
    return {
        "entries": {
            "gx10-chat": {
                "dialect": "openai-compatible",
                "id": "llama-3.1-8b-instruct",
                "endpoint": "http://gx10.local:8000/v1",
                "tags": ["cheap", "local-only", "private-data-ok"],
                "health": {"path": "/models", "timeout": 2.0, "ttl": 60},
                "fallbacks": ["sonnet"],
            },
            "sonnet": {
                "dialect": "anthropic",
                "id": "claude-sonnet-4-20250514",
                "tags": ["coding"],
            },
        },
        "bindings": {"scheduler": "gx10-chat"},
    }


# ── health: config parsing ───────────────────────────────────────────


def test_parse_health_defaults() -> None:
    health = parse_endpoint_health({})
    assert health == EndpointHealth(
        path=DEFAULT_HEALTH_PATH,
        timeout=DEFAULT_HEALTH_TIMEOUT,
        ttl=DEFAULT_HEALTH_TTL,
    )


def test_parse_health_custom_values() -> None:
    health = parse_endpoint_health({"path": "/v1/models", "timeout": 5, "ttl": 120})
    assert health.path == "/v1/models"
    assert health.timeout == 5.0
    assert health.ttl == 120.0


def test_parse_health_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match=r"unknown keys.*'probe'"):
        parse_endpoint_health({"probe": "/x"})


def test_parse_health_rejects_relative_path() -> None:
    with pytest.raises(ValueError, match="starting with '/'"):
        parse_endpoint_health({"path": "models"})


@pytest.mark.parametrize("key", ["timeout", "ttl"])
def test_parse_health_rejects_non_positive_numbers(key: str) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        parse_endpoint_health({key: 0})


def test_registry_entry_carries_parsed_health() -> None:
    registry = parse_model_registry(_registry_raw())
    ref = registry.entries["gx10-chat"]
    assert ref.health == EndpointHealth(path="/models", timeout=2.0, ttl=60.0)
    assert registry.entries["sonnet"].health is None


def test_health_on_endpoint_less_entry_fails_load() -> None:
    raw = _registry_raw()
    raw["entries"]["sonnet"]["health"] = {}
    with pytest.raises(ModelRegistryError, match=r"'sonnet'.*requires a non-empty endpoint"):
        parse_model_registry(raw)


def test_invalid_health_block_names_the_entry() -> None:
    raw = _registry_raw()
    raw["entries"]["gx10-chat"]["health"] = {"ttl": -1}
    with pytest.raises(ModelRegistryError, match=r"'gx10-chat'.*must be positive"):
        parse_model_registry(raw)


# ── EndpointHealthMonitor ────────────────────────────────────────────


def _gx10_ref(**overrides: Any) -> ModelRef:
    kwargs: dict[str, Any] = {
        "name": "gx10-chat",
        "dialect": "openai-compatible",
        "endpoint": "http://gx10.local:8000/v1",
        "health": EndpointHealth(),
    }
    kwargs.update(overrides)
    return ModelRef(**kwargs)


def test_status_exempt_without_health_config() -> None:
    monitor = EndpointHealthMonitor()
    ref = ModelRef(name="sonnet", dialect="anthropic")
    assert monitor.status(ref) is HealthStatus.HEALTHY


def test_status_unknown_before_first_probe() -> None:
    monitor = EndpointHealthMonitor()
    assert monitor.status(_gx10_ref()) is HealthStatus.UNKNOWN


def test_status_reflects_recorded_verdicts_and_ttl_decay() -> None:
    clock = _FakeClock()
    monitor = EndpointHealthMonitor(clock=clock)
    ref = _gx10_ref()

    monitor.record(ref.name, False)
    assert monitor.status(ref) is HealthStatus.UNHEALTHY

    clock.now += ref.health.ttl + 1  # type: ignore[union-attr]
    assert monitor.status(ref) is HealthStatus.UNKNOWN

    monitor.record(ref.name, True)
    assert monitor.status(ref) is HealthStatus.HEALTHY


def test_probe_url_joins_endpoint_and_path() -> None:
    ref = _gx10_ref(endpoint="http://gx10.local:8000/v1/")
    assert probe_url(ref) == "http://gx10.local:8000/v1/models"


async def test_probe_records_healthy_on_2xx() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        monitor = EndpointHealthMonitor()
        ref = _gx10_ref()
        assert await monitor.probe(ref, http_client=client) is True
    assert monitor.status(ref) is HealthStatus.HEALTHY
    assert str(seen[0].url) == "http://gx10.local:8000/v1/models"


@pytest.mark.parametrize("status_code", [302, 500, 503])
async def test_probe_records_unhealthy_on_non_2xx(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, headers={"location": "http://x/"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        monitor = EndpointHealthMonitor()
        ref = _gx10_ref()
        assert await monitor.probe(ref, http_client=client) is False
    assert monitor.status(ref) is HealthStatus.UNHEALTHY


async def test_probe_records_unhealthy_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        monitor = EndpointHealthMonitor()
        ref = _gx10_ref()
        assert await monitor.probe(ref, http_client=client) is False
    assert monitor.status(ref) is HealthStatus.UNHEALTHY


async def test_refresh_skips_entries_without_health_config() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    refs = [
        _gx10_ref(),
        ModelRef(name="sonnet", dialect="anthropic"),
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        monitor = EndpointHealthMonitor()
        verdicts = await monitor.refresh(refs, http_client=client)
    assert verdicts == {"gx10-chat": True}
    assert calls == ["http://gx10.local:8000/v1/models"]


async def test_refresh_without_health_entries_is_zero_network() -> None:
    monitor = EndpointHealthMonitor()
    refs = [ModelRef(name="sonnet", dialect="anthropic")]
    assert await monitor.refresh(refs) == {}


# ── Health-filtered resolution ───────────────────────────────────────


def _provider(monitor: EndpointHealthMonitor | None = None) -> RegistryModelProvider:
    registry = parse_model_registry(_registry_raw())
    return RegistryModelProvider(registry, health_monitor=monitor)


def test_unknown_health_state_stays_eligible_without_probing() -> None:
    """Never-probed health entries resolve normally — and no probe runs."""
    monitor = EndpointHealthMonitor()

    async def _boom(*args: Any, **kwargs: Any) -> bool:  # pragma: no cover
        raise AssertionError("resolve must not probe")

    monitor.probe = _boom  # type: ignore[method-assign]
    chain = _provider(monitor).resolve(ModelRequest(consumer="scheduler"))
    assert [r.name for r in chain] == ["gx10-chat", "sonnet"]


def test_unhealthy_entry_skipped_in_favor_of_cloud_fallback() -> None:
    monitor = EndpointHealthMonitor()
    monitor.record("gx10-chat", False)
    chain = _provider(monitor).resolve(ModelRequest(consumer="scheduler"))
    assert [r.name for r in chain] == ["sonnet"]


def test_stale_unhealthy_verdict_expires_back_to_eligible() -> None:
    clock = _FakeClock()
    monitor = EndpointHealthMonitor(clock=clock)
    monitor.record("gx10-chat", False)
    clock.now += 61
    chain = _provider(monitor).resolve(ModelRequest(consumer="scheduler"))
    assert chain[0].name == "gx10-chat"


def test_privacy_tagged_request_fails_closed_when_local_node_down() -> None:
    monitor = EndpointHealthMonitor()
    monitor.record("gx10-chat", False)
    with pytest.raises(ModelResolutionError, match=r"gx10-chat.*unhealthy|unhealthy.*gx10-chat"):
        _provider(monitor).resolve(
            ModelRequest(
                consumer="scheduler", required_tags=["private-data-ok"]
            )
        )


def test_fail_closed_never_returns_untagged_cloud_entry() -> None:
    monitor = EndpointHealthMonitor()
    monitor.record("gx10-chat", False)
    with pytest.raises(ModelResolutionError):
        _provider(monitor).resolve(
            ModelRequest(required_tags=["local-only"])
        )


def test_unhealthy_skip_applies_on_tag_resolution_path() -> None:
    """The unbound (tag-resolution) path filters health too."""
    monitor = EndpointHealthMonitor()
    monitor.record("gx10-chat", False)
    chain = _provider(monitor).resolve(
        ModelRequest(consumer="unbound-consumer")
    )
    assert [r.name for r in chain] == ["sonnet"]


def test_provider_defaults_to_shared_monitor() -> None:
    default_health_monitor().record("gx10-chat", False)
    chain = _provider().resolve(ModelRequest(consumer="scheduler"))
    assert [r.name for r in chain] == ["sonnet"]
