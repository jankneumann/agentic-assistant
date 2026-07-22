"""Generic fixture-backed tool simulator (P27 ``eval-simulation-loop``).

Serves OpenAPI-described mock tool endpoints from a directory of
recorded fixtures so a *simulation persona* (a persona whose
``tool_sources`` base URLs point at this server) can run the real
agent stack against deterministic canned responses.

Layout of a fixtures root (see ``evaluation/simulation/sources/``)::

    sources/
      content_analyzer/          # one directory per simulated source
        routes.yaml              # manifest: operations + response files
        responses/*.json         # canned JSON payloads
      coding_tools/
        routes.yaml
        ...

A root containing ``routes.yaml`` directly is treated as a single
source named after the directory. Every source is mounted at
``/<source_name>`` on the root app and exposes its own
``/openapi.json`` (FastAPI-generated, with explicit ``operationId``s),
so :func:`assistant.http_tools.discovery.discover_tools` consumes it
unchanged with ``base_url = http://host:port/<source_name>``.

Response files MAY carry leading ``//``-prefixed sentinel comment
lines (the ``tests/fixtures/graph_responses/`` convention,
``FIXTURE_GRAPH_RESPONSE_v1``); they are stripped before JSON parsing
so the existing test corpora work as seed corpora directly.

Design: openspec/changes/eval-simulation-loop/design.md (D1-D3).
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "routes.yaml"

_ALLOWED_METHODS = ("get", "post", "put", "patch", "delete")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class SimParameter:
    """A declared query parameter for a simulated operation.

    Parameters surface in the generated OpenAPI document (so the
    http_tools builder gives the tool an args schema) but never affect
    the canned response.
    """

    name: str
    description: str = ""
    required: bool = False


@dataclass(frozen=True)
class SimRoute:
    """One simulated operation: method + path → canned JSON response."""

    operation_id: str
    method: str
    path: str
    response_file: str
    status_code: int = 200
    summary: str = ""
    description: str = ""
    parameters: tuple[SimParameter, ...] = ()


@dataclass(frozen=True)
class SimSource:
    """A simulated tool source: a manifest plus its response corpus."""

    name: str
    title: str
    version: str
    base_dir: Path
    routes: tuple[SimRoute, ...] = field(default_factory=tuple)


def env_var_for_source(source_name: str) -> str:
    """Convention: the env var a simulation persona reads for a source's base URL.

    Mirrors the persona-registry ``base_url_env`` indirection —
    ``evaluation/simulation/personas/sim/persona.yaml`` declares
    ``base_url_env: SIM_<SOURCE>_URL`` per source, and ``assistant
    simulate`` prints matching ``export`` lines.
    """
    return f"SIM_{source_name.upper()}_URL"


def load_response_json(path: Path) -> Any:
    """Load a canned JSON response, stripping leading ``//`` comment lines.

    The graph-response fixture corpus marks every file with a first-line
    sentinel comment (``// FIXTURE_GRAPH_RESPONSE_v1``); tolerating any
    leading ``//`` lines lets those files be served verbatim.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = 0
    while start < len(lines) and lines[start].lstrip().startswith("//"):
        start += 1
    try:
        return json.loads("\n".join(lines[start:]))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Response fixture {path} is not valid JSON "
            f"(after stripping {start} leading comment line(s)): {exc.msg}"
        ) from exc


def _parse_route(entry: Any, source_dir: Path, index: int) -> SimRoute:
    if not isinstance(entry, dict):
        raise ValueError(
            f"{source_dir / MANIFEST_FILENAME}: routes[{index}] must be a mapping"
        )

    def _require(key: str) -> Any:
        value = entry.get(key)
        if not value or not isinstance(value, str):
            raise ValueError(
                f"{source_dir / MANIFEST_FILENAME}: routes[{index}] missing "
                f"required string field {key!r}"
            )
        return value

    operation_id = _require("operation_id")
    if not _IDENT_RE.match(operation_id):
        raise ValueError(
            f"{source_dir / MANIFEST_FILENAME}: routes[{index}] operation_id "
            f"{operation_id!r} must be a valid identifier"
        )

    method = _require("method").lower()
    if method not in _ALLOWED_METHODS:
        raise ValueError(
            f"{source_dir / MANIFEST_FILENAME}: routes[{index}] method "
            f"{method!r} not in {_ALLOWED_METHODS}"
        )

    path = _require("path")
    if not path.startswith("/"):
        raise ValueError(
            f"{source_dir / MANIFEST_FILENAME}: routes[{index}] path "
            f"{path!r} must start with '/'"
        )

    response_file = _require("response_file")
    resolved = (source_dir / response_file).resolve()
    if not str(resolved).startswith(str(source_dir.resolve())):
        raise ValueError(
            f"{source_dir / MANIFEST_FILENAME}: routes[{index}] response_file "
            f"{response_file!r} escapes the source directory"
        )
    if not resolved.is_file():
        raise ValueError(
            f"{source_dir / MANIFEST_FILENAME}: routes[{index}] response_file "
            f"{response_file!r} not found at {resolved}"
        )

    params_raw = entry.get("parameters") or []
    if not isinstance(params_raw, list):
        raise ValueError(
            f"{source_dir / MANIFEST_FILENAME}: routes[{index}] parameters "
            f"must be a list"
        )
    parameters: list[SimParameter] = []
    for p in params_raw:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str):
            raise ValueError(
                f"{source_dir / MANIFEST_FILENAME}: routes[{index}] each "
                f"parameter must be a mapping with a string 'name'"
            )
        parameters.append(
            SimParameter(
                name=p["name"],
                description=str(p.get("description", "")),
                required=bool(p.get("required", False)),
            )
        )

    return SimRoute(
        operation_id=operation_id,
        method=method,
        path=path,
        response_file=response_file,
        status_code=int(entry.get("status_code", 200)),
        summary=str(entry.get("summary", "")),
        description=str(entry.get("description", "")),
        parameters=tuple(parameters),
    )


def load_source(source_dir: Path) -> SimSource:
    """Parse one source directory's ``routes.yaml`` into a :class:`SimSource`.

    Raises ``ValueError`` with an actionable message on any manifest
    problem (missing manifest, bad shape, missing/unparseable response
    file, duplicate operation ids).
    """
    source_dir = Path(source_dir)
    manifest_path = source_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ValueError(
            f"Simulated source {source_dir} has no {MANIFEST_FILENAME}"
        )

    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{manifest_path}: manifest must be a mapping")

    routes_raw = raw.get("routes")
    if not isinstance(routes_raw, list) or not routes_raw:
        raise ValueError(
            f"{manifest_path}: manifest must declare a non-empty 'routes' list"
        )

    routes = tuple(
        _parse_route(entry, source_dir, i) for i, entry in enumerate(routes_raw)
    )

    seen: set[str] = set()
    for r in routes:
        if r.operation_id in seen:
            raise ValueError(
                f"{manifest_path}: duplicate operation_id {r.operation_id!r}"
            )
        seen.add(r.operation_id)

    # Fail fast on unparseable response fixtures (load_response_json raises).
    for r in routes:
        load_response_json(source_dir / r.response_file)

    name = str(raw.get("name") or source_dir.name)
    if not _IDENT_RE.match(name):
        raise ValueError(
            f"{manifest_path}: source name {name!r} must be a valid identifier"
        )

    return SimSource(
        name=name,
        title=str(raw.get("title") or f"{name} simulator"),
        version=str(raw.get("version") or "0.1.0"),
        base_dir=source_dir,
        routes=routes,
    )


def discover_sources(fixtures_root: Path) -> list[SimSource]:
    """Discover simulated sources under ``fixtures_root``.

    A root that itself contains ``routes.yaml`` is a single source;
    otherwise every immediate subdirectory containing ``routes.yaml``
    is one source. Raises ``ValueError`` when nothing is found.
    """
    fixtures_root = Path(fixtures_root)
    if not fixtures_root.is_dir():
        raise ValueError(
            f"Simulator fixtures directory {fixtures_root} does not exist"
        )
    if (fixtures_root / MANIFEST_FILENAME).is_file():
        return [load_source(fixtures_root)]

    sources = [
        load_source(child)
        for child in sorted(fixtures_root.iterdir())
        if child.is_dir() and (child / MANIFEST_FILENAME).is_file()
    ]
    if not sources:
        raise ValueError(
            f"No simulated sources found under {fixtures_root} "
            f"(expected {MANIFEST_FILENAME} in the directory or its "
            f"immediate subdirectories)"
        )
    return sources


def _make_endpoint(payload: Any, status_code: int, parameters: tuple[SimParameter, ...]):
    """Build a canned-response endpoint with a dynamic query-param signature.

    FastAPI reads ``__signature__`` to build both validation and the
    OpenAPI parameter list, so declared parameters appear in the spec
    (and required ones are enforced with 422) while the response stays
    canned regardless of the values sent.
    """

    async def endpoint(**_ignored: Any) -> JSONResponse:
        return JSONResponse(content=payload, status_code=status_code)

    sig_params = [
        inspect.Parameter(
            p.name,
            inspect.Parameter.KEYWORD_ONLY,
            default=Query(
                ... if p.required else None,
                description=p.description or None,
            ),
            annotation=str if p.required else str | None,
        )
        for p in parameters
    ]
    setattr(  # noqa: B010 — plain attribute assignment confuses mypy on functions
        endpoint, "__signature__", inspect.Signature(sig_params)
    )
    return endpoint


def make_source_app(source: SimSource) -> FastAPI:
    """Build the per-source FastAPI app (mounted at ``/<source_name>``)."""
    app = FastAPI(title=source.title, version=source.version)
    for route in source.routes:
        payload = load_response_json(source.base_dir / route.response_file)
        app.add_api_route(
            route.path,
            _make_endpoint(payload, route.status_code, route.parameters),
            methods=[route.method.upper()],
            operation_id=route.operation_id,
            summary=route.summary or route.operation_id,
            description=route.description
            or f"Simulated (canned) response from {route.response_file}.",
        )
    return app


def make_simulator_app(fixtures_root: Path) -> FastAPI:
    """Build the root simulator app: ``/health`` + one mount per source."""
    sources = discover_sources(fixtures_root)
    return make_simulator_app_from_sources(sources)


def make_simulator_app_from_sources(sources: list[SimSource]) -> FastAPI:
    """Build the root simulator app from already-loaded sources."""
    app = FastAPI(title="assistant-simulator", version="0.1.0")
    mounts: dict[str, str] = {}
    for source in sources:
        app.mount(f"/{source.name}", make_source_app(source))
        mounts[source.name] = f"/{source.name}"
        logger.info(
            "simulator: mounted source %r (%d operations)",
            source.name, len(source.routes),
        )

    @app.get("/health", include_in_schema=True, operation_id="simulator_health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "sources": mounts}

    return app
