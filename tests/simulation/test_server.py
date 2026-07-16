"""Tests for the fixture-backed simulator (spec: simulation / Simulator Server).

Covers manifest loading, the served surface (/health, per-source
/openapi.json + canned routes), and the shipped seed corpus under
``evaluation/simulation/sources/`` — validating the committed assets is
deliberate: a broken manifest should fail the public suite, not the
first gate run.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from assistant.simulation.server import (
    discover_sources,
    env_var_for_source,
    load_response_json,
    load_source,
    make_simulator_app,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEED_SOURCES = REPO_ROOT / "evaluation" / "simulation" / "sources"


def _write_source(root: Path, name: str = "demo", **route_overrides) -> Path:
    """Create a minimal valid single-source fixture dir under ``root``."""
    src = root / name
    (src / "responses").mkdir(parents=True)
    (src / "responses" / "ok.json").write_text(
        '// FIXTURE_SIM_RESPONSE_v1\n{"answer": 42}\n', encoding="utf-8"
    )
    route = {
        "operation_id": "get_answer",
        "method": "GET",
        "path": "/answer",
        "response_file": "responses/ok.json",
    }
    route.update(route_overrides)
    manifest = {"routes": [route]}
    import yaml

    (src / "routes.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return src


class TestLoadResponseJson:
    def test_strips_leading_comment_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "r.json"
        p.write_text('// sentinel one\n// sentinel two\n{"a": 1}\n')
        assert load_response_json(p) == {"a": 1}

    def test_plain_json_loads(self, tmp_path: Path) -> None:
        p = tmp_path / "r.json"
        p.write_text('{"a": 1}')
        assert load_response_json(p) == {"a": 1}

    def test_invalid_json_raises_value_error_naming_file(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("// c\nnot json")
        with pytest.raises(ValueError, match=r"bad\.json"):
            load_response_json(p)


class TestLoadSource:
    def test_loads_minimal_source(self, tmp_path: Path) -> None:
        src_dir = _write_source(tmp_path)
        source = load_source(src_dir)
        assert source.name == "demo"
        assert [r.operation_id for r in source.routes] == ["get_answer"]

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        with pytest.raises(ValueError, match=r"routes\.yaml"):
            load_source(tmp_path / "empty")

    def test_missing_response_file_raises(self, tmp_path: Path) -> None:
        src_dir = _write_source(tmp_path, response_file="responses/nope.json")
        with pytest.raises(ValueError, match=r"nope\.json"):
            load_source(src_dir)

    def test_bad_method_raises(self, tmp_path: Path) -> None:
        src_dir = _write_source(tmp_path, method="BREW")
        with pytest.raises(ValueError, match="brew"):
            load_source(src_dir)

    def test_response_file_escaping_source_dir_raises(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.json"
        outside.write_text("{}")
        src_dir = _write_source(tmp_path, response_file="../outside.json")
        with pytest.raises(ValueError, match="escapes"):
            load_source(src_dir)

    def test_duplicate_operation_ids_raise(self, tmp_path: Path) -> None:
        import yaml

        src_dir = _write_source(tmp_path)
        manifest = yaml.safe_load((src_dir / "routes.yaml").read_text())
        manifest["routes"].append(dict(manifest["routes"][0], path="/other"))
        (src_dir / "routes.yaml").write_text(yaml.safe_dump(manifest))
        with pytest.raises(ValueError, match="duplicate operation_id"):
            load_source(src_dir)


class TestDiscoverSources:
    def test_missing_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            discover_sources(tmp_path / "nope")

    def test_empty_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="No simulated sources"):
            discover_sources(tmp_path)

    def test_single_source_root(self, tmp_path: Path) -> None:
        src_dir = _write_source(tmp_path)
        assert [s.name for s in discover_sources(src_dir)] == ["demo"]

    def test_multi_source_root(self, tmp_path: Path) -> None:
        _write_source(tmp_path, name="alpha")
        _write_source(tmp_path, name="beta")
        assert [s.name for s in discover_sources(tmp_path)] == ["alpha", "beta"]


class TestEnvVarConvention:
    def test_upper_cases_source_name(self) -> None:
        assert env_var_for_source("content_analyzer") == "SIM_CONTENT_ANALYZER_URL"


@pytest.fixture
async def seed_client():
    """ASGI client over the app built from the shipped seed corpus."""
    app = make_simulator_app(SEED_SOURCES)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://sim"
    ) as client:
        yield client


class TestSimulatorAppSeedCorpus:
    async def test_health_lists_all_sources(self, seed_client) -> None:
        resp = await seed_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert set(body["sources"]) == {
            "content_analyzer", "coding_tools", "ms_graph",
        }

    async def test_each_source_serves_openapi_3x_with_operation_ids(
        self, seed_client
    ) -> None:
        for name in ("content_analyzer", "coding_tools", "ms_graph"):
            resp = await seed_client.get(f"/{name}/openapi.json")
            assert resp.status_code == 200, name
            spec = resp.json()
            assert spec["openapi"].startswith("3."), name
            op_ids = [
                op.get("operationId")
                for path_item in spec["paths"].values()
                for op in path_item.values()
                if isinstance(op, dict)
            ]
            assert op_ids and all(op_ids), name

    async def test_graph_route_serves_promoted_fixture_verbatim(
        self, seed_client
    ) -> None:
        resp = await seed_client.get("/ms_graph/me")
        assert resp.status_code == 200
        original = REPO_ROOT / "tests" / "fixtures" / "graph_responses" / (
            "ms_graph"
        ) / "get_my_profile.json"
        lines = original.read_text().splitlines()
        expected = json.loads("\n".join(lines[1:]))
        assert resp.json() == expected

    async def test_declared_query_params_do_not_change_canned_payload(
        self, seed_client
    ) -> None:
        bare = await seed_client.get(
            "/content_analyzer/search", params={"query": "a"}
        )
        with_params = await seed_client.get(
            "/content_analyzer/search", params={"query": "z", "limit": "3"}
        )
        assert bare.json() == with_params.json()

    async def test_required_param_missing_is_422(self, seed_client) -> None:
        resp = await seed_client.get("/content_analyzer/search")
        assert resp.status_code == 422

    async def test_post_route_serves_canned_response(self, seed_client) -> None:
        resp = await seed_client.post("/coding_tools/agents/coordinate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "acknowledged"

    async def test_seed_operation_ids_cover_role_preferred_tools(self) -> None:
        """Every content_analyzer/coding_tools preferred tool in roles/ is simulated."""
        import yaml

        sources = {s.name: s for s in discover_sources(SEED_SOURCES)}
        simulated = {
            f"{name}:{r.operation_id}"
            for name, s in sources.items()
            for r in s.routes
        }
        for role_yaml in (REPO_ROOT / "roles").glob("*/role.yaml"):
            role = yaml.safe_load(role_yaml.read_text()) or {}
            for tool in role.get("preferred_tools") or []:
                source_name = tool.split(":", 1)[0]
                if source_name in sources:
                    assert tool in simulated, (
                        f"{role_yaml.parent.name} prefers {tool} but the "
                        f"seed corpus does not simulate it"
                    )
