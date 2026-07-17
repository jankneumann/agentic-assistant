"""OpenRouter catalog sync + persona-local cache — P20 (deferred from P19).

``assistant models sync-catalog`` fetches the OpenRouter ``/models``
catalog and writes a persona-local, git-ignored cache file
(``<persona_dir>/.cache/models/catalog.json`` — the P13 ``.cache/``
convention). At persona load, :func:`apply_catalog_metadata` fills
``pricing`` / ``context_length`` / ``modalities`` on registry entries
whose ``id`` matches a cached row — ONLY for fields the entry left
empty (declared values always win). Entirely optional and
offline-safe: a missing or malformed cache is a silent no-op, persona
load never touches the network, and a failed sync leaves any existing
cache untouched.

Fetch posture mirrors http_tools D9: redirects refused, 10 MiB
streaming size cap, TLS verification on, bounded timeouts, and the
optional API key (persona-scoped credential ref ``OPENROUTER_API_KEY``)
is never logged.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from assistant.core.capabilities.models import ModelRegistry

logger = logging.getLogger(__name__)

#: Default OpenRouter catalog endpoint.
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

#: CredentialProvider lookup key for the optional OpenRouter API key.
OPENROUTER_KEY_REF = "OPENROUTER_API_KEY"

#: Cache file location relative to the persona directory.
CATALOG_CACHE_RELPATH = Path(".cache") / "models" / "catalog.json"

#: Response size cap (http_tools D9 — 10 MiB, enforced while streaming).
_MAX_CATALOG_BYTES = 10 * 1024 * 1024


class CatalogSyncError(RuntimeError):
    """The catalog fetch failed — network, redirect, size, or shape."""


def _normalize_model(item: dict[str, Any]) -> dict[str, Any]:
    """One OpenRouter ``/models`` row → the cached metadata shape.

    ``pricing`` is stored verbatim (the OpenRouter key names that
    ``compute_cost`` and the P13 budget ledger already consume);
    ``modalities`` is normalized from ``architecture.*_modalities``
    into the template's ``{input: [...], output: [...]}`` shape.
    """
    architecture = item.get("architecture") or {}
    modalities: dict[str, Any] = {}
    if architecture.get("input_modalities"):
        modalities["input"] = list(architecture["input_modalities"])
    if architecture.get("output_modalities"):
        modalities["output"] = list(architecture["output_modalities"])
    return {
        "pricing": dict(item.get("pricing") or {}),
        "context_length": int(item.get("context_length") or 0),
        "modalities": modalities,
    }


async def fetch_catalog(
    url: str = OPENROUTER_MODELS_URL,
    *,
    api_key: str = "",
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch and normalize the OpenRouter catalog.

    Returns ``{model_id: {pricing, context_length, modalities}}``.
    Raises :class:`CatalogSyncError` on any transport failure, refused
    redirect, HTTP error status, oversize response, or unexpected
    payload shape — with a message naming the cause and never the API
    key. Tests inject ``http_client`` (``httpx.MockTransport``-backed).
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    own_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=False,
        verify=True,
    )
    try:
        try:
            async with client.stream("GET", url, headers=headers) as response:
                if response.is_redirect:
                    raise CatalogSyncError(
                        f"catalog fetch refused a redirect (HTTP "
                        f"{response.status_code}) from {url}"
                    )
                if response.status_code >= 400:
                    raise CatalogSyncError(
                        f"catalog fetch failed: HTTP "
                        f"{response.status_code} from {url}"
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(chunk_size=65_536):
                    total += len(chunk)
                    if total > _MAX_CATALOG_BYTES:
                        raise CatalogSyncError(
                            "catalog response exceeds the 10 MiB cap"
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
        except httpx.HTTPError as exc:
            # Covers the no-network case (ConnectError), timeouts, and
            # protocol errors — a clear error, nothing else breaks.
            raise CatalogSyncError(
                f"catalog fetch failed: {type(exc).__name__}: {exc}"
            ) from exc
    finally:
        if own_client:
            await client.aclose()

    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise CatalogSyncError(
            f"catalog response is not valid JSON: {exc}"
        ) from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise CatalogSyncError(
            "catalog response has no 'data' list (unexpected shape)."
        )

    models: dict[str, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not model_id:
            continue
        models[str(model_id)] = _normalize_model(item)
    return models


def catalog_cache_path(persona_dir: Path) -> Path:
    return Path(persona_dir) / CATALOG_CACHE_RELPATH


def write_catalog_cache(
    persona_dir: Path,
    models: dict[str, dict[str, Any]],
    *,
    url: str = OPENROUTER_MODELS_URL,
) -> Path:
    """Write the persona-local catalog cache; returns the file path."""
    path = catalog_cache_path(persona_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "synced_at": datetime.now(UTC).isoformat(),
        "url": url,
        "models": models,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_catalog_cache(persona_dir: Path) -> dict[str, dict[str, Any]]:
    """Load the cached catalog; missing or malformed file returns ``{}``.

    Never raises — persona load must stay offline-deterministic and
    must never fail because of the catalog cache.
    """
    path = catalog_cache_path(persona_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        models = payload.get("models")
        if isinstance(models, dict):
            return {
                str(k): v for k, v in models.items() if isinstance(v, dict)
            }
    except (OSError, ValueError):
        logger.warning(
            "ignoring malformed model catalog cache at %s", path
        )
    return {}


def apply_catalog_metadata(
    registry: ModelRegistry, catalog: dict[str, dict[str, Any]]
) -> list[str]:
    """Fill empty metadata fields from the catalog; declared values win.

    For each registry entry whose ``model_id`` matches a catalog row,
    ``pricing`` / ``context_length`` / ``modalities`` are filled ONLY
    when the entry left them empty. Returns the names of updated
    entries (for logging/tests).
    """
    if not catalog:
        return []
    updated: list[str] = []
    for ref in registry.entries.values():
        meta = catalog.get(ref.model_id)
        if not meta:
            continue
        touched = False
        pricing = meta.get("pricing")
        if not ref.pricing and isinstance(pricing, dict) and pricing:
            ref.pricing = dict(pricing)
            touched = True
        context_length = meta.get("context_length")
        if not ref.context_length and context_length:
            ref.context_length = int(context_length)
            touched = True
        modalities = meta.get("modalities")
        if not ref.modalities and isinstance(modalities, dict) and modalities:
            ref.modalities = dict(modalities)
            touched = True
        if touched:
            updated.append(ref.name)
    return updated
