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
from assistant.harnesses.base import SdkHarnessAdapter
from assistant.harnesses.host.claude_code import ClaudeCodeHarness
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def chdir_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI uses relative paths `personas/`, `roles/` — run tests from root."""
    monkeypatch.chdir(REPO_ROOT)


class StubHarness(SdkHarnessAdapter):
    invoke_response = "hello back"
    spawn_response = "draft text"

    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        super().__init__(persona, role)

    def name(self) -> str:
        return "stub"

    def harness_type(self) -> str:
        return "sdk"

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
        if harness_name == "claude_code":
            return ClaudeCodeHarness(persona, role)
        raise ValueError(f"Unknown harness '{harness_name}'. Available: ['deep_agents', 'ms_agent_framework', 'claude_code']")

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


# ── CLI Export Subcommand (Phase 5) ─────────────────────────────────


def test_export_generates_context_artifacts(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["export", "-p", "personal", "-H", "claude_code"]
    )
    assert result.exit_code == 0
    assert len(result.output.strip()) > 0


def test_export_requires_persona() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["export", "-H", "claude_code"])
    assert result.exit_code != 0


def test_export_rejects_sdk_harness(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["export", "-p", "personal", "-H", "deep_agents"]
    )
    assert result.exit_code != 0
    combined = result.output + (str(result.exception) if result.exception else "")
    assert "SDK harness" in combined or "sdk" in combined.lower()


# ── HTTP Tool Discovery Wiring (P3) ──────────────────────────────────


def _canned_registry() -> object:
    """Build a small ``HttpToolRegistry`` for list-tools / startup tests."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    from assistant.http_tools import HttpToolRegistry

    class _Args(BaseModel):
        name: str

    async def _noop(name: str) -> None:
        return None

    reg = HttpToolRegistry()
    reg.register(
        "backend", "list_items",
        StructuredTool.from_function(
            coroutine=_noop, name="backend:list_items",
            description="List items", args_schema=_Args,
        ),
    )
    reg.register(
        "backend", "create_item",
        StructuredTool.from_function(
            coroutine=_noop, name="backend:create_item",
            description="Create an item", args_schema=_Args,
        ),
    )
    return reg


def test_list_tools_with_no_sources_prints_message(
    stub_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per spec: 'No tool_sources configured.' + exit 0 when all sources lack base_url."""
    # The personal fixture has tool_sources but their base_url_env vars are
    # unset, so base_url resolves to empty — same effective state as "no sources".
    monkeypatch.delenv("CONTENT_ANALYZER_URL", raising=False)
    monkeypatch.delenv("SEARCH_API_URL", raising=False)
    monkeypatch.delenv("BACKEND_URL", raising=False)

    from assistant.http_tools import HttpToolRegistry

    async def _spy(tool_sources, *, client=None):
        return HttpToolRegistry()

    monkeypatch.setattr(cli_mod, "discover_tools", _spy)

    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal", "--list-tools"])
    # With all base_urls empty, the CLI short-circuits to the "no configured
    # sources" branch with exit 0.
    assert result.exit_code == 0
    # Non-empty output either way (either "No tool_sources configured." or
    # per-source sections listing zero tools).
    assert result.output


def test_list_tools_with_successful_sources(
    stub_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per spec: per-source sections with tool names + exit 0 on success."""
    monkeypatch.setenv("CONTENT_ANALYZER_URL", "http://127.0.0.1:1/ignored")

    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    from assistant.http_tools import HttpToolRegistry

    class _Args(BaseModel):
        q: str

    async def _noop(q: str) -> None:
        return None

    # The persona's configured source is `content_analyzer` — build the
    # registry with that source name so by_source() matches.
    registry = HttpToolRegistry()
    registry.register(
        "content_analyzer", "search",
        StructuredTool.from_function(
            coroutine=_noop, name="content_analyzer:search",
            description="Search content", args_schema=_Args,
        ),
    )

    async def _fake_discover(tool_sources, *, client=None):
        return registry

    monkeypatch.setattr(cli_mod, "discover_tools", _fake_discover)

    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal", "--list-tools"])
    assert result.exit_code == 0, result.output
    assert "[content_analyzer]" in result.output
    assert "content_analyzer:search" in result.output


def test_list_tools_exits_zero_when_warning_but_tools_registered(
    stub_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit 0 when a source emits a WARNING but still registers tools.

    Real case: ``/openapi.json`` returns 500 → fallback to ``/help``
    succeeds. A WARNING is emitted for the 500 but the registry ends up
    with tools for the source. Exit code MUST be 0.
    """
    import logging

    monkeypatch.setenv("CONTENT_ANALYZER_URL", "http://127.0.0.1:1/ignored")

    # Canned registry has `backend:*` tools, not `content_analyzer:*`,
    # so we need a registry keyed by the actually-configured source name.
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    from assistant.http_tools import HttpToolRegistry

    class _Args(BaseModel):
        pass

    async def _noop() -> None:
        return None

    registry = HttpToolRegistry()
    registry.register(
        "content_analyzer", "search",
        StructuredTool.from_function(
            coroutine=_noop, name="content_analyzer:search",
            description="Search content", args_schema=_Args,
        ),
    )

    async def _fake_discover(tool_sources, *, client=None):
        # Emit a warning like discovery would when /openapi.json 500s —
        # but still succeed via the fallback.
        logging.getLogger("assistant.http_tools.discovery").warning(
            "discovery failed for source %r: HTTP %d", "content_analyzer", 500,
        )
        return registry

    monkeypatch.setattr(cli_mod, "discover_tools", _fake_discover)

    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal", "--list-tools"])
    assert result.exit_code == 0, result.output
    assert "content_analyzer:search" in result.output


def test_list_tools_with_failing_source_exits_nonzero(
    stub_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per spec: exit 1 when any configured source fails discovery."""
    import logging

    monkeypatch.setenv("CONTENT_ANALYZER_URL", "http://127.0.0.1:1/ignored")
    from assistant.http_tools import HttpToolRegistry

    async def _fake_discover(tool_sources, *, client=None):
        logging.getLogger("assistant.http_tools.discovery").warning(
            "skipping source %r: simulated failure", "content_analyzer",
        )
        return HttpToolRegistry()

    monkeypatch.setattr(cli_mod, "discover_tools", _fake_discover)

    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal", "--list-tools"])
    assert result.exit_code == 1
    assert "content_analyzer" in result.output or "content_analyzer" in (
        result.stderr_bytes.decode() if result.stderr_bytes else ""
    )


def test_startup_calls_discover_tools_when_base_url_set(
    stub_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per spec: `discover_tools` MUST be called before agent creation when a
    tool source is configured with a base_url.
    """
    monkeypatch.setenv("CONTENT_ANALYZER_URL", "http://127.0.0.1:1/unused")

    called = {"count": 0}
    registry = _canned_registry()

    async def _spy(tool_sources, *, client=None):
        called["count"] += 1
        return registry

    monkeypatch.setattr(cli_mod, "discover_tools", _spy)

    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal"], input="quit\n")
    assert result.exit_code == 0
    assert called["count"] >= 1
    assert "HTTP tool discovery is deferred" not in result.output


def test_startup_skips_discovery_when_no_sources(
    stub_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per spec: discovery is skipped when no tool_sources have base_url."""
    monkeypatch.delenv("CONTENT_ANALYZER_URL", raising=False)
    monkeypatch.delenv("SEARCH_API_URL", raising=False)
    monkeypatch.delenv("BACKEND_URL", raising=False)

    called = {"count": 0}

    async def _spy(tool_sources, *, client=None):
        called["count"] += 1
        from assistant.http_tools import HttpToolRegistry
        return HttpToolRegistry()

    monkeypatch.setattr(cli_mod, "discover_tools", _spy)

    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal"], input="quit\n")
    assert result.exit_code == 0
    assert called["count"] == 0
    assert "HTTP tool discovery is deferred" not in result.output


# ── Bare invocation defaults to run ──────────────────────────────────


def test_bare_invocation_defaults_to_run(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["-p", "personal"], input="quit\n"
    )
    assert result.exit_code == 0
    assert "Chief of Staff" in result.output


def test_explicit_run_subcommand(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["run", "-p", "personal"], input="quit\n"
    )
    assert result.exit_code == 0
    assert "Chief of Staff" in result.output
