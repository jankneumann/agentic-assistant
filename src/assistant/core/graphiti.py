"""Graphiti client factory with FalkorDB driver — per-persona caching."""

from __future__ import annotations

import logging
import os
from typing import Any

from graphiti_core import Graphiti
from graphiti_core.driver.falkordb_driver import FalkorDriver

logger = logging.getLogger(__name__)

_graphiti_cache: dict[str, Any] = {}


def _env(var_name: str | None) -> str:
    if not var_name:
        return ""
    return os.environ.get(var_name, "")


def create_graphiti_client(persona: Any) -> Any | None:
    graphiti_url = persona.graphiti_url
    if not graphiti_url:
        return None

    cache_key = f"{persona.name}:{graphiti_url}"
    if cache_key in _graphiti_cache:
        return _graphiti_cache[cache_key]

    graphiti_cfg = persona.raw.get("graphiti", {})

    host = _env(graphiti_cfg.get("host_env")) or "localhost"
    port_str = _env(graphiti_cfg.get("port_env")) or "6379"
    port = int(port_str)
    password = _env(graphiti_cfg.get("password_env")) or ""
    database = graphiti_cfg.get("database", f"{persona.name}_graph")

    driver = FalkorDriver(
        host=host,
        port=port,
        username="",
        password=password,
        database=database,
    )
    client = Graphiti(graph_driver=driver)
    _graphiti_cache[cache_key] = client
    logger.info(
        "Created Graphiti client for persona '%s' at %s:%d/%s",
        persona.name, host, port, database,
    )
    return client


def _clear_graphiti_cache() -> None:
    _graphiti_cache.clear()
