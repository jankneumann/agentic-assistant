"""Minimal OpenAPI 3.x walker.

Produces one :class:`ParsedOperation` per operation in the document,
with intra-document ``$ref`` values resolved in-place (design decision
D10). External ``$ref`` values and cyclic ref chains raise
``ValueError`` so ``discovery.py`` can skip the affected source with a
warning.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")
_SLUG_NON_ALNUM = re.compile(r"[^A-Za-z0-9_]+")
_SLUG_UNDERSCORE_RUN = re.compile(r"_+")


@dataclass
class ParsedOperation:
    """A single OpenAPI operation, ready for tool construction."""

    method: str
    path: str
    operation_id: str
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body_schema: dict[str, Any] | None = None
    summary: str = ""
    description: str = ""


def parse_operations(spec: dict[str, Any]) -> Iterator[ParsedOperation]:
    """Yield a :class:`ParsedOperation` per operation in ``spec``.

    Skips operations whose schema resolution fails with ``ValueError``
    (external ``$ref`` or cyclic chain) and logs a warning naming the
    method + path.
    """
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI document missing 'paths' object")

    for path, path_item in sorted(paths.items()):
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            try:
                yield _parse_operation(spec, method, path, operation)
            except ValueError as exc:
                logger.warning(
                    "skipping operation %s %s: %s", method.upper(), path, exc,
                )


def _parse_operation(
    spec: dict[str, Any],
    method: str,
    path: str,
    operation: dict[str, Any],
) -> ParsedOperation:
    op_id = operation.get("operationId") or _synth_operation_id(method, path)

    parameters_raw = operation.get("parameters") or []
    parameters = [
        _resolve_ref_recursive(spec, p, visited=set())
        for p in parameters_raw
        if isinstance(p, dict)
    ]

    request_body_schema: dict[str, Any] | None = None
    body = operation.get("requestBody")
    if isinstance(body, dict):
        content = body.get("content") or {}
        json_body = content.get("application/json") or {}
        raw_schema = json_body.get("schema")
        if raw_schema is not None:
            request_body_schema = _resolve_ref_recursive(
                spec, raw_schema, visited=set(),
            )

    return ParsedOperation(
        method=method.lower(),
        path=path,
        operation_id=op_id,
        parameters=parameters,
        request_body_schema=request_body_schema,
        summary=operation.get("summary", "") or "",
        description=operation.get("description", "") or "",
    )


def _synth_operation_id(method: str, path: str) -> str:
    """Build a deterministic slug from ``method`` + ``path``.

    Example: ``GET`` + ``/items/{id}/history`` → ``get_items_id_history``.
    """
    slug = f"{method.lower()}_{path}"
    slug = _SLUG_NON_ALNUM.sub("_", slug)
    slug = _SLUG_UNDERSCORE_RUN.sub("_", slug)
    return slug.strip("_")


def _resolve_ref(
    spec: dict[str, Any],
    ref: str,
    visited: set[str],
) -> dict[str, Any]:
    """Resolve a single ``$ref`` string against ``spec``.

    Only intra-document JSON Pointer refs (``#/...``) are supported.
    External refs and cycles raise ``ValueError``.
    """
    if not ref.startswith("#/"):
        raise ValueError(f"external $ref not supported: {ref}")
    if ref in visited:
        raise ValueError(f"cyclic $ref detected: {ref}")
    visited = visited | {ref}

    node: Any = spec
    for segment in ref[2:].split("/"):
        if not isinstance(node, dict) or segment not in node:
            raise ValueError(f"$ref target not found: {ref}")
        node = node[segment]
    if not isinstance(node, dict):
        raise ValueError(f"$ref target is not an object: {ref}")
    # Recursively resolve further refs within the resolved object.
    return _resolve_ref_recursive(spec, node, visited=visited)


def _resolve_ref_recursive(
    spec: dict[str, Any],
    node: Any,
    visited: set[str],
) -> Any:
    """Walk ``node`` replacing every ``$ref`` found with its target."""
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            return _resolve_ref(spec, node["$ref"], visited=visited)
        return {
            key: _resolve_ref_recursive(spec, value, visited=visited)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_resolve_ref_recursive(spec, item, visited=visited) for item in node]
    return node
