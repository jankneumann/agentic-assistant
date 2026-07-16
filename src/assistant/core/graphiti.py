"""Graphiti client factory with FalkorDB driver — per-persona caching."""

from __future__ import annotations

import logging
from typing import Any

from graphiti_core import Graphiti
from graphiti_core.driver.falkordb_driver import FalkorDriver

from assistant.core.capabilities.credentials import EnvCredentialProvider

logger = logging.getLogger(__name__)

_graphiti_cache: dict[str, Any] = {}


def create_graphiti_client(persona: Any) -> Any | None:
    graphiti_url = persona.graphiti_url
    if not graphiti_url:
        return None

    cache_key = f"{persona.name}:{graphiti_url}"
    if cache_key in _graphiti_cache:
        return _graphiti_cache[cache_key]

    graphiti_cfg = persona.raw.get("graphiti", {})

    # P13 security-hardening: graphiti connection secrets resolve
    # through the persona-scoped CredentialProvider (persona .env
    # first, process env fallback), matching persona load.
    credentials = getattr(persona, "credentials", None) or EnvCredentialProvider()

    def _cred(ref: Any) -> str:
        return credentials.get_credential(str(ref)) if ref else ""

    host = _cred(graphiti_cfg.get("host_env")) or "localhost"
    port_str = _cred(graphiti_cfg.get("port_env")) or "6379"
    port = int(port_str)
    password = _cred(graphiti_cfg.get("password_env")) or ""
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
