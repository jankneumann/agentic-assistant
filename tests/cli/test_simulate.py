"""Tests for `assistant simulate` and `assistant export-eval-dataset`.

Spec: openspec/changes/eval-simulation-loop/specs/cli-interface/spec.md
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from assistant.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def chdir_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)


# ---------------------------------------------------------------------------
# assistant simulate
# ---------------------------------------------------------------------------


class TestSimulateCommand:
    def test_registered_in_group(self) -> None:
        # `assistant --help` routes to `run --help` by design
        # (_DefaultGroup), so registration is asserted on the group's
        # command map — same approach as tests/cli/test_serve.py.
        assert "simulate" in main.commands
        assert "export-eval-dataset" in main.commands

    def test_help_exits_zero(self) -> None:
        result = CliRunner().invoke(main, ["simulate", "--help"])
        assert result.exit_code == 0
        assert "simulat" in result.output.lower()

    def test_missing_fixtures_dir_is_usage_error(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            main, ["simulate", "--fixtures", str(tmp_path / "nope")]
        )
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_prints_env_exports_and_serves_seed_corpus(self) -> None:
        calls: list[dict] = []

        def fake_uvicorn_run(app, *, host, port, **kw):
            calls.append({"app": app, "host": host, "port": port})

        with patch("uvicorn.run", side_effect=fake_uvicorn_run):
            result = CliRunner().invoke(main, ["simulate", "--port", "8955"])

        assert result.exit_code == 0
        # One export line per seed source, matching the persona's env vars.
        assert "export SIM_CONTENT_ANALYZER_URL=http://127.0.0.1:8955/content_analyzer" in result.output
        assert "export SIM_CODING_TOOLS_URL=http://127.0.0.1:8955/coding_tools" in result.output
        assert "export SIM_MS_GRAPH_URL=http://127.0.0.1:8955/ms_graph" in result.output
        assert "export ASSISTANT_PERSONAS_DIR=" in result.output
        assert calls == [
            {"app": calls[0]["app"], "host": "127.0.0.1", "port": 8955}
        ]

    def test_non_loopback_host_warns(self) -> None:
        with patch("uvicorn.run"):
            result = CliRunner().invoke(
                main, ["simulate", "--host", "0.0.0.0"]
            )
        assert result.exit_code == 0
        assert "non-loopback" in result.output


class TestSimulationPersonaLoads:
    """The shipped sim persona parses through the real PersonaRegistry."""

    def test_sim_persona_loads_with_env_urls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from assistant.core.persona import PersonaRegistry

        monkeypatch.setenv("SIM_CONTENT_ANALYZER_URL", "http://127.0.0.1:8901/content_analyzer")
        monkeypatch.setenv("SIM_CODING_TOOLS_URL", "http://127.0.0.1:8901/coding_tools")
        monkeypatch.setenv("SIM_MS_GRAPH_URL", "http://127.0.0.1:8901/ms_graph")

        reg = PersonaRegistry(
            personas_dir=REPO_ROOT / "evaluation" / "simulation" / "personas"
        )
        assert reg.discover() == ["sim"]
        pc = reg.load("sim")
        assert pc.name == "sim"
        assert pc.database_url == ""
        assert pc.extensions == []
        assert set(pc.tool_sources) == {
            "content_analyzer", "coding_tools", "ms_graph",
        }
        for src in pc.tool_sources.values():
            assert src["base_url"].startswith("http://127.0.0.1:8901/")
            assert src["auth_header"] is None

    def test_sim_persona_sources_match_seed_corpus(self) -> None:
        """Persona tool_sources and simulator seed sources stay in lockstep."""
        from assistant.simulation.server import discover_sources, env_var_for_source

        persona_yaml = yaml.safe_load(
            (
                REPO_ROOT / "evaluation" / "simulation" / "personas" / "sim"
                / "persona.yaml"
            ).read_text()
        )
        declared = {
            name: cfg["base_url_env"]
            for name, cfg in persona_yaml["tool_sources"].items()
        }
        sources = discover_sources(
            REPO_ROOT / "evaluation" / "simulation" / "sources"
        )
        expected = {s.name: env_var_for_source(s.name) for s in sources}
        assert declared == expected


# ---------------------------------------------------------------------------
# assistant export-eval-dataset
# ---------------------------------------------------------------------------


class TestExportEvalDataset:
    def test_help_exits_zero(self) -> None:
        result = CliRunner().invoke(main, ["export-eval-dataset", "--help"])
        assert result.exit_code == 0

    def test_persona_without_database_url_errors(self) -> None:
        # Fixture persona 'personal' resolves database_url from
        # PERSONAL_DATABASE_URL, which is unset in the test env.
        result = CliRunner().invoke(
            main, ["export-eval-dataset", "-p", "personal"]
        )
        assert result.exit_code == 1
        assert "no database_url" in result.output

    def _invoke_with_mocked_memory(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        interactions: list[dict],
        extra_args: list[str] | None = None,
    ):
        monkeypatch.setenv(
            "PERSONAL_DATABASE_URL", "postgresql://synthetic.invalid/db"
        )
        mgr = MagicMock()
        mgr.list_interactions = AsyncMock(return_value=interactions)
        out_dir = tmp_path / "exported"
        with (
            patch("assistant.core.db.create_async_engine"),
            patch("assistant.core.db.async_session_factory"),
            patch("assistant.core.graphiti.create_graphiti_client"),
            patch("assistant.core.memory.MemoryManager", return_value=mgr),
        ):
            result = CliRunner().invoke(
                main,
                [
                    "export-eval-dataset", "-p", "personal",
                    "--output-dir", str(out_dir),
                    *(extra_args or []),
                ],
            )
        return result, mgr, out_dir

    def test_writes_one_stub_per_interaction(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        interactions = [
            {
                "id": 1,
                "role": "coder",
                "summary": "Fixed the flaky test",
                "created_at": "2026-07-16T00:00:00+00:00",
                "metadata": {},
            },
            {
                "id": 2,
                "role": "researcher",
                "summary": "Collected sources",
                "created_at": "2026-07-15T00:00:00+00:00",
                "metadata": {},
            },
        ]
        result, _mgr, out_dir = self._invoke_with_mocked_memory(
            tmp_path, monkeypatch, interactions
        )
        assert result.exit_code == 0, result.output
        files = sorted(out_dir.glob("*.yaml"))
        assert len(files) == 2
        parsed = yaml.safe_load(files[0].read_text())
        assert parsed["category"] == "regression"
        assert parsed["source"]["persona"] == "personal"
        assert "Exported 2 scenario stub(s)" in result.output

    def test_role_and_limit_forwarded_to_memory_manager(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, mgr, _ = self._invoke_with_mocked_memory(
            tmp_path, monkeypatch, [], extra_args=["-r", "coder", "--limit", "5"]
        )
        assert result.exit_code == 0, result.output
        mgr.list_interactions.assert_awaited_once_with(
            "personal", role="coder", limit=5
        )
        assert "nothing to export" in result.output


# ---------------------------------------------------------------------------
# evaluation/run-gate.sh (advisory-skip contract)
# ---------------------------------------------------------------------------


class TestRunGateScript:
    GATE = REPO_ROOT / "evaluation" / "run-gate.sh"

    def test_skips_cleanly_when_gen_eval_absent(self, tmp_path) -> None:
        env = {
            "PATH": "/usr/bin:/bin",
            "GEN_EVAL_PROJECT": str(tmp_path / "definitely-missing"),
        }
        proc = subprocess.run(
            ["bash", str(self.GATE)],
            capture_output=True, text=True, env=env, timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        assert "SKIP" in proc.stdout
        assert "ADR 0006" in proc.stdout

    def test_skips_when_gen_eval_dir_is_a_non_runnable_stub(
        self, tmp_path
    ) -> None:
        import shutil

        uv = shutil.which("uv")
        if uv is None:
            pytest.skip("uv not on PATH")
        # A directory that exists but is not a runnable gen-eval project
        # (mirrors the offline lock-resolution stub) must be treated as
        # unavailable, not as a scenario failure.
        stub = tmp_path / "stub-gen-eval"
        stub.mkdir()
        env = {
            "PATH": f"{Path(uv).parent}:/usr/bin:/bin",
            "GEN_EVAL_PROJECT": str(stub),
        }
        proc = subprocess.run(
            ["bash", str(self.GATE)],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "SKIP" in proc.stdout
        assert "not runnable" in proc.stdout

    def test_required_mode_fails_when_gen_eval_absent(self, tmp_path) -> None:
        env = {
            "PATH": "/usr/bin:/bin",
            "GEN_EVAL_PROJECT": str(tmp_path / "definitely-missing"),
            "EVAL_GATE_REQUIRE": "1",
        }
        proc = subprocess.run(
            ["bash", str(self.GATE)],
            capture_output=True, text=True, env=env, timeout=30,
        )
        assert proc.returncode == 3
        assert "FAIL" in proc.stderr
