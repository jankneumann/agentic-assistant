"""http_tools discovery against the simulator (spec: simulation / Discovery Compatibility).

The load-bearing property of the whole phase: the EXISTING
``discover_tools`` path consumes the simulator's per-source
``/openapi.json`` unchanged, so simulation personas need zero new
agent code paths. Runs the real FastAPI app in-process via
``httpx.ASGITransport``.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from assistant.http_tools.discovery import discover_tools
from assistant.simulation.server import make_simulator_app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEED_SOURCES = REPO_ROOT / "evaluation" / "simulation" / "sources"


@pytest.fixture
async def asgi_client():
    app = make_simulator_app(SEED_SOURCES)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://sim"
    ) as client:
        yield client


def _tool_sources(*names: str) -> dict:
    """Simulate the persona-registry shape for resolved tool_sources."""
    return {
        name: {
            "base_url": f"http://sim/{name}",
            "auth_header": None,
            "allowed_tools": [],
        }
        for name in names
    }


class TestDiscoveryAgainstSimulator:
    async def test_all_seed_sources_yield_tools(self, asgi_client) -> None:
        registry = await discover_tools(
            _tool_sources("content_analyzer", "coding_tools", "ms_graph"),
            client=asgi_client,
        )
        by_source = {
            name: [t.name for t in registry.by_source(name)]
            for name in ("content_analyzer", "coding_tools", "ms_graph")
        }
        assert "content_analyzer:search" in by_source["content_analyzer"]
        assert "coding_tools:repo_status" in by_source["coding_tools"]
        assert "ms_graph:get_my_profile" in by_source["ms_graph"]

    async def test_declared_parameters_become_args_schema_fields(
        self, asgi_client
    ) -> None:
        registry = await discover_tools(
            _tool_sources("content_analyzer"), client=asgi_client,
        )
        (search,) = [
            t for t in registry.by_source("content_analyzer")
            if t.name == "content_analyzer:search"
        ]
        # P17 tool-spec migration: discovered tools are ToolSpecs whose
        # input_schema is a JSON-Schema object.
        assert search.input_schema is not None
        fields = search.input_schema.get("properties", {})
        assert "query" in fields

    async def test_discovered_tool_invocation_returns_canned_payload(
        self, asgi_client
    ) -> None:
        registry = await discover_tools(
            _tool_sources("ms_graph"), client=asgi_client,
        )
        (profile,) = [
            t for t in registry.by_source("ms_graph")
            if t.name == "ms_graph:get_my_profile"
        ]
        result = await profile.handler()
        assert "synthetic.test@synthetic.example" in str(result)
