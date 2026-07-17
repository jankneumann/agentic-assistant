"""Tests for `assistant serve --mcp` wiring (P17 mcp-server-exposure).

Spec scenarios: cli-interface (CLI serve Subcommand — --mcp flag).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from assistant.cli import main
from assistant.harnesses.base import SdkHarnessAdapter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def chdir_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)


class _FakeHarness(SdkHarnessAdapter):
    def name(self) -> str:
        return "fake"

    @property
    def thread_id(self) -> str:
        return "thread-fake"

    async def create_agent(self, tools, extensions):
        return object()

    async def invoke(self, agent, message) -> str:
        return "ok"

    async def spawn_sub_agent(self, role, task, tools, extensions) -> str:
        return "ok"


def _fake_sdk_harness(persona, role, harness_name):
    return _FakeHarness(persona, role)


def _invoke_serve(args: list[str]):
    """Run `assistant serve <args>` capturing make_app call kwargs."""
    make_app_calls: list = []

    def fake_make_app(persona, role, harness_name, **kwargs):
        make_app_calls.append(
            {"persona": persona, "role": role, "kwargs": kwargs}
        )
        return MagicMock()

    runner = CliRunner()
    with (
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.make_app", side_effect=fake_make_app),
        patch("uvicorn.run") as mock_uv_run,
    ):
        mock_uv_run.return_value = None
        result = runner.invoke(main, ["serve", *args], catch_exceptions=False)
    return result, make_app_calls


def test_serve_mcp_flag_enables_mcp():
    result, calls = _invoke_serve(
        ["-p", "personal", "-r", "coder", "--mcp", "--port", "9002"]
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["kwargs"] == {"enable_mcp": True}


def test_serve_without_flag_keeps_legacy_call_shape():
    """No --mcp → make_app is called with NO extra kwargs (legacy shape)."""
    result, calls = _invoke_serve(["-p", "personal", "-r", "coder"])
    assert result.exit_code == 0, result.output
    assert calls[0]["kwargs"] == {}


def test_serve_mcp_and_a2a_compose():
    """Both flags can be enabled on the same server."""
    result, calls = _invoke_serve(
        ["-p", "personal", "-r", "coder", "--a2a", "--mcp"]
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["kwargs"] == {
        "enable_a2a": True,
        "a2a_base_url": "http://127.0.0.1:8765",
        "enable_mcp": True,
    }


def test_serve_mcp_announces_endpoint():
    result, _ = _invoke_serve(["-p", "personal", "-r", "coder", "--mcp"])
    assert result.exit_code == 0, result.output
    assert "/mcp" in result.output


def test_serve_help_documents_mcp_flag():
    serve_cmd = main.commands["serve"]
    param_names = {p.name for p in serve_cmd.params}
    assert "enable_mcp" in param_names
