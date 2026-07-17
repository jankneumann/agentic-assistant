"""Tests for the OpenRouter catalog sync + persona-local cache (P20).

Covers the model-provider delta "OpenRouter Catalog Cache" and the
cli-interface delta "CLI models Command Group": D9-postured fetch
(httpx.MockTransport — no network), cache round-trip, empty-only
merge semantics, persona-load integration, and the CLI subcommands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from click.testing import CliRunner

import assistant.cli as cli_mod
from assistant.core.capabilities import catalog as catalog_mod
from assistant.core.capabilities.catalog import (
    CatalogSyncError,
    apply_catalog_metadata,
    catalog_cache_path,
    fetch_catalog,
    load_catalog_cache,
    write_catalog_cache,
)
from assistant.core.capabilities.models import parse_model_registry
from assistant.core.persona import PersonaRegistry

_CATALOG_PAYLOAD: dict[str, Any] = {
    "data": [
        {
            "id": "anthropic/claude-sonnet-4",
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "context_length": 200000,
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
        },
        {
            "id": "meta-llama/llama-3.1-8b-instruct",
            "pricing": {"prompt": "0.00000002", "completion": "0.00000003"},
            "context_length": 131072,
        },
    ]
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── fetch_catalog ────────────────────────────────────────────────────


async def test_fetch_normalizes_openrouter_rows() -> None:
    async with _client(
        lambda request: httpx.Response(200, json=_CATALOG_PAYLOAD)
    ) as client:
        models = await fetch_catalog(
            "https://example.test/models", http_client=client
        )
    assert set(models) == {
        "anthropic/claude-sonnet-4",
        "meta-llama/llama-3.1-8b-instruct",
    }
    sonnet = models["anthropic/claude-sonnet-4"]
    assert sonnet["pricing"] == {
        "prompt": "0.000003",
        "completion": "0.000015",
    }
    assert sonnet["context_length"] == 200000
    assert sonnet["modalities"] == {
        "input": ["text", "image"],
        "output": ["text"],
    }
    # Row without architecture → empty modalities, never invented.
    assert models["meta-llama/llama-3.1-8b-instruct"]["modalities"] == {}


async def test_fetch_sends_bearer_only_when_key_present() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    async with _client(handler) as client:
        await fetch_catalog("https://x.test/m", api_key="sk-or-123", http_client=client)
        await fetch_catalog("https://x.test/m", http_client=client)
    assert seen[0].headers["Authorization"] == "Bearer sk-or-123"
    assert "Authorization" not in seen[1].headers


async def test_fetch_refuses_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.test/"})

    async with _client(handler) as client:
        with pytest.raises(CatalogSyncError, match="redirect"):
            await fetch_catalog("https://x.test/m", http_client=client)


async def test_fetch_maps_http_error_status() -> None:
    async with _client(lambda request: httpx.Response(503)) as client:
        with pytest.raises(CatalogSyncError, match="HTTP 503"):
            await fetch_catalog("https://x.test/m", http_client=client)


async def test_fetch_maps_transport_error_to_clear_message() -> None:
    """The no-network case: a clear error naming the transport failure."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    async with _client(handler) as client:
        with pytest.raises(CatalogSyncError, match="ConnectError"):
            await fetch_catalog("https://x.test/m", http_client=client)


async def test_fetch_enforces_size_cap() -> None:
    big = b'{"data": [' + b" " * (10 * 1024 * 1024) + b"]}"

    async with _client(
        lambda request: httpx.Response(200, content=big)
    ) as client:
        with pytest.raises(CatalogSyncError, match="10 MiB"):
            await fetch_catalog("https://x.test/m", http_client=client)


async def test_fetch_rejects_unexpected_shape() -> None:
    async with _client(
        lambda request: httpx.Response(200, json={"models": []})
    ) as client:
        with pytest.raises(CatalogSyncError, match="'data'"):
            await fetch_catalog("https://x.test/m", http_client=client)


# ── cache round-trip ─────────────────────────────────────────────────


def test_cache_round_trip(tmp_path: Path) -> None:
    models = {"some/model": {"pricing": {"prompt": "0.1"}, "context_length": 8}}
    path = write_catalog_cache(tmp_path, models, url="https://x.test/m")
    assert path == catalog_cache_path(tmp_path)
    assert path == tmp_path / ".cache" / "models" / "catalog.json"
    assert load_catalog_cache(tmp_path) == models
    payload = json.loads(path.read_text())
    assert payload["url"] == "https://x.test/m"
    assert "synced_at" in payload


def test_load_missing_cache_returns_empty(tmp_path: Path) -> None:
    assert load_catalog_cache(tmp_path) == {}


def test_load_malformed_cache_degrades_to_empty(tmp_path: Path) -> None:
    path = catalog_cache_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert load_catalog_cache(tmp_path) == {}


# ── merge semantics ──────────────────────────────────────────────────


def _registry(**entry: Any):
    spec = {"dialect": "anthropic", "id": "anthropic/claude-sonnet-4"}
    spec.update(entry)
    return parse_model_registry({"entries": {"sonnet": spec}})


_CACHED_META = {
    "anthropic/claude-sonnet-4": {
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "context_length": 200000,
        "modalities": {"input": ["text"], "output": ["text"]},
    }
}


def test_merge_fills_empty_fields_from_catalog() -> None:
    registry = _registry()
    assert apply_catalog_metadata(registry, _CACHED_META) == ["sonnet"]
    ref = registry.entries["sonnet"]
    assert ref.pricing == _CACHED_META["anthropic/claude-sonnet-4"]["pricing"]
    assert ref.context_length == 200000
    assert ref.modalities == {"input": ["text"], "output": ["text"]}


def test_merge_declared_values_win() -> None:
    registry = _registry(
        pricing={"prompt": "0.000001", "completion": "0.000002"},
        context_length=100,
    )
    apply_catalog_metadata(registry, _CACHED_META)
    ref = registry.entries["sonnet"]
    assert ref.pricing == {"prompt": "0.000001", "completion": "0.000002"}
    assert ref.context_length == 100
    # modalities was empty → still filled from the catalog
    assert ref.modalities == {"input": ["text"], "output": ["text"]}


def test_merge_ignores_entries_without_catalog_row() -> None:
    registry = _registry(id="unlisted/model")
    assert apply_catalog_metadata(registry, _CACHED_META) == []
    assert registry.entries["sonnet"].pricing == {}


def test_merge_with_empty_catalog_is_noop() -> None:
    registry = _registry()
    assert apply_catalog_metadata(registry, {}) == []


# ── persona-load integration ─────────────────────────────────────────


def _write_persona(tmp_path: Path, name: str = "cataloged") -> Path:
    persona_dir = tmp_path / name
    persona_dir.mkdir(parents=True)
    (persona_dir / "persona.yaml").write_text(
        "name: " + name + "\n"
        "models:\n"
        "  entries:\n"
        "    sonnet:\n"
        "      dialect: anthropic\n"
        "      id: anthropic/claude-sonnet-4\n"
        "  bindings:\n"
        "    default: sonnet\n"
    )
    return persona_dir


def test_persona_load_inherits_cached_pricing(tmp_path: Path) -> None:
    persona_dir = _write_persona(tmp_path)
    write_catalog_cache(persona_dir, _CACHED_META)
    pc = PersonaRegistry(tmp_path).load("cataloged")
    ref = pc.models.entries["sonnet"]
    assert ref.pricing == _CACHED_META["anthropic/claude-sonnet-4"]["pricing"]
    assert ref.context_length == 200000


def test_persona_load_without_cache_keeps_declared_shape(tmp_path: Path) -> None:
    _write_persona(tmp_path)
    pc = PersonaRegistry(tmp_path).load("cataloged")
    assert pc.models.entries["sonnet"].pricing == {}


# ── CLI: assistant models ────────────────────────────────────────────


@pytest.fixture()
def cli_personas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A temp personas root the CLI's PersonaRegistry() picks up."""
    persona_dir = _write_persona(tmp_path, name="cliper")
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(tmp_path))
    return persona_dir


def test_models_group_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["models", "--help"])
    assert result.exit_code == 0
    assert "sync-catalog" in result.output
    assert "check-health" in result.output


def test_sync_catalog_writes_persona_cache(
    cli_personas: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch(url: str, *, api_key: str = "", http_client=None):
        assert url == "https://x.test/m"
        return {"anthropic/claude-sonnet-4": {"pricing": {"prompt": "0.1"}}}

    monkeypatch.setattr(catalog_mod, "fetch_catalog", fake_fetch)
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["models", "sync-catalog", "-p", "cliper", "--url", "https://x.test/m"],
    )
    assert result.exit_code == 0, result.output
    cache = catalog_cache_path(cli_personas)
    assert cache.is_file()
    assert "anthropic/claude-sonnet-4" in cache.read_text()
    assert str(cache) in result.output


def test_sync_catalog_without_network_errors_clearly(
    cli_personas: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch(url: str, *, api_key: str = "", http_client=None):
        raise CatalogSyncError("catalog fetch failed: ConnectError: down")

    monkeypatch.setattr(catalog_mod, "fetch_catalog", fake_fetch)
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["models", "sync-catalog", "-p", "cliper"]
    )
    assert result.exit_code == 1
    assert "ConnectError" in result.output
    assert not catalog_cache_path(cli_personas).exists()


def test_check_health_no_declaring_entries_exits_zero(
    cli_personas: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["models", "check-health", "-p", "cliper"]
    )
    assert result.exit_code == 0
    assert "declare health" in result.output


def _write_health_persona(tmp_path: Path) -> Path:
    persona_dir = tmp_path / "healthy"
    persona_dir.mkdir(parents=True)
    (persona_dir / "persona.yaml").write_text(
        "name: healthy\n"
        "models:\n"
        "  entries:\n"
        "    gx10-chat:\n"
        "      dialect: openai-compatible\n"
        "      endpoint: http://gx10.local:8000/v1\n"
        "      health: {path: /models}\n"
        "    gx10-embed:\n"
        "      dialect: openai-compatible\n"
        "      endpoint: http://gx10.local:8001/v1\n"
        "      health: {path: /models}\n"
    )
    return persona_dir


def test_check_health_reports_verdicts_and_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_health_persona(tmp_path)
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(tmp_path))

    from assistant.core.capabilities import health as health_mod

    async def fake_refresh(self, refs, *, http_client=None):
        return {"gx10-chat": True, "gx10-embed": False}

    monkeypatch.setattr(
        health_mod.EndpointHealthMonitor, "refresh", fake_refresh
    )
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["models", "check-health", "-p", "healthy"]
    )
    assert result.exit_code == 1
    assert "gx10-chat: healthy" in result.output
    assert "gx10-embed: UNHEALTHY" in result.output


def test_check_health_all_healthy_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_health_persona(tmp_path)
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(tmp_path))

    from assistant.core.capabilities import health as health_mod

    async def fake_refresh(self, refs, *, http_client=None):
        return {ref.name: True for ref in refs}

    monkeypatch.setattr(
        health_mod.EndpointHealthMonitor, "refresh", fake_refresh
    )
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["models", "check-health", "-p", "healthy"]
    )
    assert result.exit_code == 0, result.output
