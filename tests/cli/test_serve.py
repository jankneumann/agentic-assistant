"""Tests for the `serve` CLI subcommand - Section 6 tasks 6.1-6.8 (incl 6.6b, 6.6c, 6.6d).

Spec scenarios: cli-interface
Design decisions: D6, D12
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from assistant.cli import main
from assistant.harnesses.base import SdkHarnessAdapter
from assistant.harnesses.host.claude_code import ClaudeCodeHarness

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def chdir_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)


# ---------------------------------------------------------------------------
# Fake harness + app factory helpers
# ---------------------------------------------------------------------------


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

    async def spawn_sub_agent(
        self, role, task, tools, extensions, context=None
    ) -> str:
        return "ok"


def _fake_sdk_harness(persona, role, harness_name):
    return _FakeHarness(persona, role)


def _fake_host_harness(persona, role, harness_name):
    return ClaudeCodeHarness(persona, role)


def _make_serve_invocation(args: list[str], uvicorn_run=None):
    """Run `assistant serve <args>` with uvicorn.run patched out.

    Returns (result, uvicorn_call_args).
    """
    runner = CliRunner()
    uvicorn_calls: list = []

    def fake_uvicorn_run(app, *, host, port, **kw):
        uvicorn_calls.append({"host": host, "port": port, "app": app})

    with (
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.create_harness", side_effect=_fake_sdk_harness),
        patch("uvicorn.run") as mock_uv_run,
    ):
        mock_uv_run.side_effect = fake_uvicorn_run
        result = runner.invoke(main, ["serve", *args], catch_exceptions=False)

    return result, uvicorn_calls


# ---------------------------------------------------------------------------
# 6.1 — serve binds persona and role at startup
# ---------------------------------------------------------------------------


def test_serve_binds_persona_and_role():
    """`serve` calls make_app with the supplied persona and role."""
    make_app_calls: list = []

    def fake_make_app(persona, role, harness_name):
        make_app_calls.append({"persona": persona, "role": role})
        app = MagicMock()
        app.state = MagicMock()
        return app

    runner = CliRunner()
    with (
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.make_app", side_effect=fake_make_app),
        patch("uvicorn.run") as mock_uv_run,
    ):
        mock_uv_run.return_value = None
        result = runner.invoke(
            main, ["serve", "-p", "personal", "-r", "coder"], catch_exceptions=False
        )

    assert result.exit_code == 0, result.output
    assert make_app_calls[0]["persona"] == "personal"
    assert make_app_calls[0]["role"] == "coder"


# ---------------------------------------------------------------------------
# 6.2 — Default host is 127.0.0.1
# ---------------------------------------------------------------------------


def test_serve_defaults_host_to_loopback():
    """`serve` without --host must bind to 127.0.0.1."""
    uvicorn_calls: list = []

    def fake_uvicorn_run(app, *, host, port, **kw):
        uvicorn_calls.append({"host": host, "port": port})

    runner = CliRunner()
    with (
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.make_app", return_value=MagicMock()),
        patch("uvicorn.run") as mock_uv_run,
    ):
        mock_uv_run.side_effect = fake_uvicorn_run
        result = runner.invoke(
            main, ["serve", "-p", "personal", "-r", "coder"], catch_exceptions=False
        )

    assert result.exit_code == 0, result.output
    assert uvicorn_calls[0]["host"] == "127.0.0.1"


# ---------------------------------------------------------------------------
# 6.3 — default_role fallback when -r omitted
# ---------------------------------------------------------------------------


def test_serve_uses_default_role_when_r_omitted():
    """`serve` must fall back to persona.default_role when -r is not supplied.

    Injects a sentinel default_role on a mocked PersonaConfig so the test
    proves the exact value was propagated to make_app() rather than just
    accepting "any non-None role" (IMPL_REVIEW round-1 claude #2).
    """
    make_app_calls: list = []

    def fake_make_app(persona, role, harness_name):
        make_app_calls.append({"persona": persona, "role": role})
        return MagicMock()

    runner = CliRunner()
    with (
        patch("assistant.cli._load_persona_or_fail") as mock_load,
        patch("assistant.cli.RoleRegistry") as mock_role_reg_cls,
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.make_app", side_effect=fake_make_app),
        patch("uvicorn.run") as mock_uv_run,
    ):
        pc = MagicMock()
        pc.default_role = "sentinel-default-role"
        mock_load.return_value = pc
        # Accept the sentinel as a valid role name so the test exercises
        # the default-role fallback path independently of the on-disk
        # role registry.
        mock_role_reg_cls.return_value.load.return_value = MagicMock(
            name="sentinel-default-role",
        )
        mock_uv_run.return_value = None
        result = runner.invoke(main, ["serve", "-p", "personal"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert make_app_calls[0]["role"] == "sentinel-default-role"


# ---------------------------------------------------------------------------
# 6.4 — Unknown persona → non-zero exit
# ---------------------------------------------------------------------------


def test_serve_rejects_unknown_persona():
    """`serve` with an unknown persona must exit non-zero."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["serve", "-p", "nonexistent_persona_xyz"], catch_exceptions=False
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 6.5 — Host-harness rejection at CLI boundary
# ---------------------------------------------------------------------------


def test_serve_rejects_host_harness():
    """`serve` must reject host harness names (e.g. claude_code) before uvicorn."""
    uvicorn_calls: list = []

    def fake_uvicorn_run(app, *, host, port, **kw):
        uvicorn_calls.append(True)

    runner = CliRunner()
    with (
        patch("assistant.cli._create_harness", side_effect=_fake_host_harness),
        patch("uvicorn.run") as mock_uv_run,
    ):
        mock_uv_run.side_effect = fake_uvicorn_run
        result = runner.invoke(
            main,
            ["serve", "-p", "personal", "-r", "coder", "-H", "claude_code"],
            catch_exceptions=False,
        )

    assert result.exit_code != 0
    assert len(uvicorn_calls) == 0


# ---------------------------------------------------------------------------
# 6.6 — Clean Ctrl-C exit (status 0)
# ---------------------------------------------------------------------------


def test_serve_ctrl_c_exits_cleanly():
    """KeyboardInterrupt during uvicorn.run must exit with status 0."""
    runner = CliRunner()
    with (
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.make_app", return_value=MagicMock()),
        patch("uvicorn.run") as mock_uv_run,
    ):
        mock_uv_run.side_effect = KeyboardInterrupt
        result = runner.invoke(
            main, ["serve", "-p", "personal", "-r", "coder"], catch_exceptions=False
        )

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 6.6b — Persona with no default_role + -r omitted
# ---------------------------------------------------------------------------


def test_serve_no_default_role_persona_without_r():
    """`serve` on a persona with no default_role and -r omitted must exit non-zero."""
    runner = CliRunner()

    with patch("assistant.cli._load_persona_or_fail") as mock_load:
        pc = MagicMock()
        pc.default_role = None
        mock_load.return_value = pc
        result = runner.invoke(
            main, ["serve", "-p", "personal"], catch_exceptions=False
        )

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 6.6c — Unknown harness name
# ---------------------------------------------------------------------------


def test_serve_rejects_unknown_harness_name():
    """`serve` must reject unrecognised harness names with non-zero exit."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["serve", "-p", "personal", "-r", "coder", "-H", "unknown_harness_xyz"],
        catch_exceptions=False,
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 6.6d — Non-loopback host warning
# ---------------------------------------------------------------------------


def test_serve_warns_non_loopback_host():
    """`serve --host 0.0.0.0` must emit a warning before starting."""
    runner = CliRunner()
    with (
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.make_app", return_value=MagicMock()),
        patch("uvicorn.run") as mock_uv_run,
    ):
        mock_uv_run.return_value = None
        result = runner.invoke(
            main,
            ["serve", "-p", "personal", "-r", "coder", "--host", "0.0.0.0"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    combined = (result.output or "") + (result.stderr or "")
    assert "warn" in combined.lower() or "non-loopback" in combined.lower() or "0.0.0.0" in combined


# ---------------------------------------------------------------------------
# 6.7 — --help mentions serve
# ---------------------------------------------------------------------------


def test_help_mentions_serve():
    """The click main group must register `serve` as a subcommand.

    Bypasses the runner because `_DefaultGroup` rewrites bare arg lists to
    route through the default `run` subcommand, so `runner.invoke(main, ["--help"])`
    shows `run`'s help instead of the group's. Inspect the registry directly.
    """
    assert "serve" in main.commands


# ---------------------------------------------------------------------------
# P11 harness-routing — serve resolves 'auto' before make_app
# ---------------------------------------------------------------------------


def test_serve_auto_default_passes_concrete_harness_to_make_app():
    """The default -H auto resolves against the personal persona
    (deep_agents is its only enabled SDK harness) so make_app never
    sees the sentinel."""
    make_app_calls: list = []

    def fake_make_app(persona, role, harness_name):
        make_app_calls.append(harness_name)
        return MagicMock(name="asgi-app")

    with (
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.make_app", side_effect=fake_make_app),
        patch("uvicorn.run"),
    ):
        result = CliRunner().invoke(
            main, ["serve", "-p", "personal"], catch_exceptions=False
        )
    assert result.exit_code == 0, result.output
    assert make_app_calls == ["deep_agents"]


def test_serve_explicit_harness_bypasses_routing():
    make_app_calls: list = []

    def fake_make_app(persona, role, harness_name):
        make_app_calls.append(harness_name)
        return MagicMock(name="asgi-app")

    with (
        patch("assistant.cli._create_harness", side_effect=_fake_sdk_harness),
        patch("assistant.web.app.make_app", side_effect=fake_make_app),
        patch("uvicorn.run"),
    ):
        result = CliRunner().invoke(
            main,
            ["serve", "-p", "personal", "-H", "deep_agents"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output
    assert make_app_calls == ["deep_agents"]
