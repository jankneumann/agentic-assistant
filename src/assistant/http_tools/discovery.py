"""Discovery orchestrator: fetch OpenAPI per source → parse → build tools.

Design decisions D2 (shared async client), D4 (discovery skips on
failure; per-tool raises), D9 (security posture including 10 MiB cap
via streaming + credential redaction), D10 ($ref resolution), D11
(persona auth_header schema).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from assistant.http_tools.auth import resolve_auth_header
from assistant.http_tools.builder import _build_tool, _read_body_with_size_cap
from assistant.http_tools.openapi import parse_operations
from assistant.http_tools.registry import HttpToolRegistry

logger = logging.getLogger(__name__)

_OPENAPI_PATHS = ("/openapi.json", "/help")


async def _fetch_openapi(
    client: httpx.AsyncClient,
    base_url: str,
    auth_headers: dict[str, str],
    source_name: str,
) -> dict[str, Any] | None:
    """Fetch an OpenAPI document from a source, trying ``/openapi.json`` then ``/help``.

    Returns the parsed spec dict, or ``None`` on any failure. All
    failure paths log a WARNING naming the source + status/reason but
    never include the auth_headers values (D9).
    """
    last_status: int | None = None
    for path in _OPENAPI_PATHS:
        url = f"{base_url.rstrip('/')}{path}"
        try:
            async with client.stream("GET", url, headers=auth_headers) as response:
                # 3xx with follow_redirects=False lands here as a normal
                # response; treat as discovery failure.
                if response.is_redirect:
                    logger.warning(
                        "discovery redirect refused for source %r (status %d)",
                        source_name, response.status_code,
                    )
                    last_status = response.status_code
                    continue
                if response.status_code == 404:
                    last_status = 404
                    continue
                if response.status_code >= 400:
                    logger.warning(
                        "discovery failed for source %r: HTTP %d",
                        source_name, response.status_code,
                    )
                    last_status = response.status_code
                    continue
                try:
                    body = await _read_body_with_size_cap(response, source_name)
                except ValueError as exc:
                    logger.warning(
                        "discovery failed for source %r: %s",
                        source_name, exc,
                    )
                    return None
                try:
                    return json.loads(body)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "discovery failed for source %r: invalid JSON (%s)",
                        source_name, exc.msg,
                    )
                    return None
        except httpx.TimeoutException:
            logger.warning("discovery timeout for source %r", source_name)
            return None
        except httpx.HTTPError as exc:
            logger.warning(
                "discovery transport error for source %r: %s",
                source_name, type(exc).__name__,
            )
            return None
    if last_status is not None:
        logger.warning(
            "discovery exhausted paths for source %r (last status %d)",
            source_name, last_status,
        )
    return None


def _is_openapi_3x(spec: dict[str, Any]) -> bool:
    """Return True only for OpenAPI 3.x documents (not Swagger 2.0)."""
    version = spec.get("openapi")
    return isinstance(version, str) and version.startswith("3.")


async def discover_tools(
    tool_sources: dict[str, dict[str, Any]],
    *,
    client: httpx.AsyncClient,
) -> HttpToolRegistry:
    """Discover tools from every configured source into a single registry.

    Per D4, any per-source failure is logged as a WARNING and the source
    is omitted — but the function never raises.

    The caller MUST own the ``httpx.AsyncClient`` lifecycle. The
    returned tools close over ``client`` and will fail with
    ``RuntimeError`` if invoked after the client is closed, so the
    client must live at least as long as the registry is in use.
    Design decision D2.
    """
    registry = HttpToolRegistry()
    if not tool_sources:
        return registry

    for source_name, source_cfg in tool_sources.items():
        await _discover_one(
            registry=registry,
            source_name=source_name,
            source_cfg=source_cfg,
            client=client,
        )

    return registry


async def _discover_one(
    *,
    registry: HttpToolRegistry,
    source_name: str,
    source_cfg: dict[str, Any],
    client: httpx.AsyncClient,
) -> None:
    """Discover tools for a single source; all failures → warning + return."""
    base_url = source_cfg.get("base_url")
    if not base_url:
        logger.warning("skipping source %r: missing base_url", source_name)
        return

    try:
        auth_headers = resolve_auth_header(source_cfg.get("auth_header"))
    except KeyError as exc:
        logger.warning(
            "skipping source %r: missing auth env var %s",
            source_name, exc.args[0] if exc.args else "<unknown>",
        )
        return
    except ValueError as exc:
        logger.warning("skipping source %r: %s", source_name, exc)
        return

    spec = await _fetch_openapi(client, base_url, auth_headers, source_name)
    if spec is None:
        return

    if not _is_openapi_3x(spec):
        version = spec.get("openapi") or (
            "swagger" if "swagger" in spec else "<unknown>"
        )
        logger.warning(
            "skipping source %r: unsupported OpenAPI version %r (expected 3.x)",
            source_name, version,
        )
        return

    try:
        operations = list(parse_operations(spec))
    except ValueError as exc:
        logger.warning("skipping source %r: OpenAPI parse error: %s", source_name, exc)
        return

    # Per-operation $ref/parse failures are logged by openapi.py at the
    # operation level. If every operation was skipped (paths were
    # declared but parse_operations yielded nothing), surface a
    # source-level WARNING so the spec's "failure references the source"
    # contract holds end-to-end.
    if not operations and spec.get("paths"):
        logger.warning(
            "skipping source %r: no operations yielded from %d path(s); "
            "see per-operation warnings above",
            source_name, len(spec.get("paths") or {}),
        )
        return

    for op in operations:
        try:
            tool = _build_tool(
                source_name=source_name,
                base_url=base_url,
                operation=op,
                client=client,
                auth_headers=auth_headers,
            )
        except Exception as exc:
            # A single broken operation shouldn't abort the source.
            logger.warning(
                "skipping operation %s:%s (%s %s): %s",
                source_name, op.operation_id, op.method.upper(), op.path,
                type(exc).__name__,
            )
            continue
        registry.register(source_name, op.operation_id, tool)
