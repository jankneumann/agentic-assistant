"""Tests for cli-interface spec.

Covers all 13 scenarios across 7 requirements in
``openspec/changes/bootstrap-vertical-slice/specs/cli-interface/spec.md``.

A `StubHarness` is injected via the ``_create_harness`` module-level seam so
the CLI can be exercised end-to-end without invoking real LLMs or the MS AF
stack.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import assistant.cli as cli_mod
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import HarnessAdapter
from assistant.harnesses.ms_agent_fw import MSAgentFrameworkHarness

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def chdir_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI uses relative paths `personas/`, `roles/` — run tests from root."""
    monkeypatch.chdir(REPO_ROOT)


class StubHarness(HarnessAdapter):
    invoke_response = "hello back"
    spawn_response = "draft text"

    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        super().__init__(persona, role)

    def name(self) -> str:
        return "stub"

    async def create_agent(self, tools, extensions):
        return object()

    async def invoke(self, agent, message) -> str:
        return self.invoke_response

    async def spawn_sub_agent(
        self, role: RoleConfig, task: str, tools, extensions
    ) -> str:
        return self.spawn_response


@pytest.fixture
def stub_factory(monkeypatch: pytest.MonkeyPatch):
    """Install a factory that returns StubHarness for 'deep_agents' and the
    real MS AF stub (which raises NotImplementedError) for 'ms_agent_framework'."""

    def fake(persona, role, harness_name):
        if harness_name == "ms_agent_framework":
            return MSAgentFrameworkHarness(persona, role)
        if harness_name == "deep_agents":
            return StubHarness(persona, role)
        raise ValueError(f"Unknown harness '{harness_name}'. Available: ['deep_agents', 'ms_agent_framework']")

    monkeypatch.setattr(cli_mod, "_create_harness", fake)


# ── CLI Entry Point ──────────────────────────────────────────────────


def test_entry_point_is_installed() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["--help"])
    assert result.exit_code == 0
    assert "--persona" in result.output
    assert "--role" in result.output
    assert "--harness" in result.output


# ── List Personas ────────────────────────────────────────────────────


def test_only_initialized_personas_are_listed() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["--list-personas"])
    assert result.exit_code == 0
    assert "personal" in result.output
    assert "work" not in result.output
    assert "_template" not in result.output


# ── List Roles Requires Persona ──────────────────────────────────────


def test_listing_roles_without_persona_errors() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["--list-roles"])
    assert result.exit_code != 0


def test_listing_roles_for_personal_persona() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal", "--list-roles"])
    assert result.exit_code == 0
    for expected in ("researcher", "chief_of_staff", "writer"):
        assert expected in result.output


# ── Default Role Fallback ────────────────────────────────────────────


def test_default_role_used_when_r_omitted(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["-p", "personal"], input="quit\n"
    )
    assert result.exit_code == 0
    # personal persona default_role is chief_of_staff
    assert "Chief of Staff" in result.output


# ── Unknown Persona ──────────────────────────────────────────────────


def test_unknown_persona_fails_with_hint() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "nonexistent", "--list-roles"])
    assert result.exit_code != 0
    combined = (result.output or "") + (str(result.exception) if result.exception else "")
    assert "Available:" in combined


# ── Harness Selection ───────────────────────────────────────────────


def test_default_harness_is_deep_agents(stub_factory, monkeypatch) -> None:
    """When -H is omitted, the CLI passes 'deep_agents' to the factory."""
    seen: list[str] = []

    def capture(persona, role, harness_name):
        seen.append(harness_name)
        return StubHarness(persona, role)

    monkeypatch.setattr(cli_mod, "_create_harness", capture)
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal"], input="quit\n")
    assert result.exit_code == 0
    assert seen and seen[0] == "deep_agents"


def test_h_ms_agent_framework_surfaces_stub_error(stub_factory) -> None:
    runner = CliRunner()
    # personal persona has ms_agent_framework disabled by default; enable it
    # by passing through to the real factory would also raise "not enabled".
    # But here the stub_factory returns the real MSAgentFrameworkHarness for
    # this name, so the error will come from create_agent.
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-H", "ms_agent_framework"],
        input="quit\n",
    )
    assert result.exit_code != 0
    combined = result.output + (str(result.exception) if result.exception else "")
    assert "not yet implemented" in combined.lower() or "p5" in combined.lower()


# ── Interactive REPL Loop ───────────────────────────────────────────


def test_repl_echoes_harness_response(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["-p", "personal"], input="hi\nquit\n"
    )
    assert result.exit_code == 0
    assert "hello back" in result.output


def test_role_switches_active_role_midsession(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal"],
        input="/role writer\nhi\nquit\n",
    )
    assert result.exit_code == 0
    # After /role writer, the response prompt should use Writer display_name
    assert "Writer" in result.output


def test_role_with_unknown_role_prints_error_keeps_current(
    stub_factory,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal"],
        input="/role nonexistent\nhi\nquit\n",
    )
    assert result.exit_code == 0
    assert "Error" in result.output
    # Current role remains Chief of Staff (default)
    assert "Chief of Staff" in result.output


# ── Delegation via /delegate Command ────────────────────────────────


def test_valid_delegation_returns_sub_agent_output(stub_factory) -> None:
    runner = CliRunner()
    # chief_of_staff allows writer; after /role researcher, researcher allows
    # writer too. Use chief_of_staff default to keep it simple.
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal"],
        input="/delegate writer draft an email\nquit\n",
    )
    assert result.exit_code == 0
    assert "draft text" in result.output
    assert "[writer]" in result.output


def test_invalid_delegate_usage_prints_hint(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["-p", "personal"], input="/delegate\nquit\n"
    )
    assert result.exit_code == 0
    assert "Usage:" in result.output
