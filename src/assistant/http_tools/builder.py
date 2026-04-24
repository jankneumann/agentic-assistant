"""Builds a :class:`langchain_core.tools.StructuredTool` per OpenAPI operation.

Runtime Pydantic model generation (D1), single shared httpx client
(D2), URL-safe path-parameter encoding, streaming response-size cap
(D9), content-type validation, and description fallback (D6) all live
here.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from assistant.http_tools.openapi import ParsedOperation
from assistant.http_tools.registry import tool_key

logger = logging.getLogger(__name__)

# 10 MiB streaming cap per D9 / spec "HTTP Client Security Posture".
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

_JSON_CONTENT_TYPES = ("application/json", "application/problem+json")

_TYPE_MAP: dict[str, type[Any]] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_schema_to_python_type(schema: dict[str, Any]) -> type[Any] | Any:
    """Map a JSON Schema fragment to a Python type usable by Pydantic.

    Recursive for ``type: object`` — yields a nested Pydantic model so
    the LLM sees structured arg schemas at every level. Fields with
    neither ``type`` nor ``$ref`` become :data:`Any`.
    """
    if not isinstance(schema, dict):
        return Any

    t = schema.get("type")
    if t == "object" and isinstance(schema.get("properties"), dict):
        return _build_nested_model(schema)
    if t == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            inner = _json_schema_to_python_type(items)
            # mypy can't statically prove `inner` is a valid type here —
            # at runtime it always is (class or typing._GenericAlias).
            return list[inner]  # type: ignore[valid-type]
        return list
    if isinstance(t, str):
        return _TYPE_MAP.get(t, Any)
    return Any


def _nested_model_counter() -> Callable[[], int]:
    """Monotonically increasing counter for unique nested-model names."""
    n = 0

    def _next() -> int:
        nonlocal n
        n += 1
        return n

    return _next


_next_nested_id = _nested_model_counter()


def _build_nested_model(schema: dict[str, Any]) -> type[BaseModel]:
    """Create a Pydantic model for a nested ``object``-typed schema."""
    fields: dict[str, Any] = {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    for prop_name, prop_schema in props.items():
        if not isinstance(prop_schema, dict):
            continue
        py_type = _json_schema_to_python_type(prop_schema)
        if prop_name in required:
            fields[prop_name] = (py_type, Field(...))
        else:
            default = prop_schema.get("default", None)
            fields[prop_name] = (py_type | None, Field(default=default))
    return create_model(f"NestedArgs{_next_nested_id()}", **fields)


def _build_args_schema(
    operation: ParsedOperation,
    model_name: str,
) -> type[BaseModel]:
    """Build the top-level Pydantic args schema from path + query + body."""
    fields: dict[str, Any] = {}

    for param in operation.parameters:
        name = param.get("name")
        schema = param.get("schema") or {}
        if not isinstance(name, str):
            continue
        py_type = _json_schema_to_python_type(schema)
        if param.get("required") or param.get("in") == "path":
            # Path params are implicitly required.
            fields[name] = (py_type, Field(..., description=param.get("description", "")))
        else:
            default = schema.get("default", None)
            fields[name] = (py_type | None, Field(default=default, description=param.get("description", "")))

    body = operation.request_body_schema
    if isinstance(body, dict) and body.get("type") == "object":
        body_required = set(body.get("required") or [])
        for prop_name, prop_schema in (body.get("properties") or {}).items():
            if not isinstance(prop_schema, dict):
                continue
            py_type = _json_schema_to_python_type(prop_schema)
            if prop_name in body_required:
                fields[prop_name] = (py_type, Field(...))
            else:
                default = prop_schema.get("default", None)
                fields[prop_name] = (py_type | None, Field(default=default))

    return create_model(model_name, **fields)


def _derive_description(operation: ParsedOperation) -> str:
    """Description fallback per design decision D6."""
    if operation.summary:
        return operation.summary
    if operation.description:
        return operation.description
    return f"HTTP {operation.method.upper()} {operation.path}"


def _path_param_names(operation: ParsedOperation) -> set[str]:
    return {
        p["name"]
        for p in operation.parameters
        if isinstance(p, dict) and p.get("in") == "path" and isinstance(p.get("name"), str)
    }


def _query_param_names(operation: ParsedOperation) -> set[str]:
    return {
        p["name"]
        for p in operation.parameters
        if isinstance(p, dict) and p.get("in") == "query" and isinstance(p.get("name"), str)
    }


def _body_field_names(operation: ParsedOperation) -> set[str]:
    body = operation.request_body_schema
    if isinstance(body, dict) and isinstance(body.get("properties"), dict):
        return set(body["properties"].keys())
    return set()


async def _read_body_with_size_cap(
    response: httpx.Response,
    source_name: str,
) -> bytes:
    """Stream response body enforcing the 10 MiB cap (D9).

    Raises ``ValueError("response exceeds 10MiB")`` as soon as the cap
    is exceeded, without buffering the full body first.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes(chunk_size=65_536):
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds 10MiB")
        chunks.append(chunk)
    return b"".join(chunks)


def _build_tool(
    *,
    source_name: str,
    base_url: str,
    operation: ParsedOperation,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> StructuredTool:
    """Wrap an OpenAPI operation as a LangChain StructuredTool.

    See spec "Tool Builder Generates Typed StructuredTool" for the
    full behavior contract.
    """
    op_id = operation.operation_id
    name = tool_key(source_name, op_id)
    args_schema = _build_args_schema(operation, model_name=f"ArgsFor_{op_id}")
    description = _derive_description(operation)
    method = operation.method.upper()

    path_params = _path_param_names(operation)
    query_params = _query_param_names(operation)
    body_params = _body_field_names(operation)

    async def _coroutine(**kwargs: Any) -> Any:
        # Substitute path parameters with URL-safe encoding.
        path_formatted = operation.path
        for pname in path_params:
            raw = kwargs.get(pname)
            if raw is None:
                raise ValueError(f"missing path parameter: {pname}")
            encoded = urllib.parse.quote(str(raw), safe="")
            path_formatted = path_formatted.replace(
                "{" + pname + "}", encoded,
            )

        url = f"{base_url.rstrip('/')}{path_formatted}"
        query = {k: v for k, v in kwargs.items() if k in query_params and v is not None}
        body = {k: v for k, v in kwargs.items() if k in body_params and v is not None}

        request_kwargs: dict[str, Any] = {
            "headers": auth_headers,
            "params": query or None,
        }
        if method in ("POST", "PUT", "PATCH") and body:
            request_kwargs["json"] = body

        async with client.stream(method, url, **request_kwargs) as response:
            # 3xx, 4xx, 5xx all raise per spec + D9 (redirects refused
            # at client level; any 3xx reaching here is already
            # misconfigured).
            response.raise_for_status()

            # Empty-body 204 → None.
            if response.status_code == 204:
                return None
            content_length = response.headers.get("Content-Length")
            if content_length == "0":
                return None

            # Content-Type gate: only JSON variants accepted.
            content_type = (
                response.headers.get("Content-Type", "")
                .split(";")[0]
                .strip()
                .lower()
            )
            if content_type and content_type not in _JSON_CONTENT_TYPES:
                raise ValueError(
                    f"non-JSON content-type from {name}: {content_type}",
                )

            raw = await _read_body_with_size_cap(response, name)
            if not raw:
                return None
            return json.loads(raw)

    # LangChain's StructuredTool.from_function stores the coroutine
    # and calls it with **validated_model.model_dump().
    tool = StructuredTool.from_function(
        coroutine=_async_wrapper(_coroutine),
        name=name,
        description=description,
        args_schema=args_schema,
    )
    return tool


def _async_wrapper(
    fn: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Pass-through wrapper that lets LangChain inspect the coroutine.

    Exists so tests can verify the coroutine is an ``async def`` even
    though it was constructed via closures above.
    """
    return fn
