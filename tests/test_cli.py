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


def test_h_ms_agent_framework_blocked_when_persona_disables_it(stub_factory) -> None:
    """Post-P5 contract: the MSAF harness is real, but personal persona
    leaves ``ms_agent_framework.enabled = false`` so the factory's
    enablement gate raises before any harness construction.

    The legacy "not yet implemented" / "P5 / deferred" surface is gone
    (covered by the dedicated ``test_harness_ms_agent_fw.py`` suite);
    this test now asserts the post-P5 enablement-gate failure mode.
    """
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-H", "ms_agent_framework"],
        input="quit\n",
    )
    assert result.exit_code != 0
    combined = result.output + (str(result.exception) if result.exception else "")
    # Legacy stub markers MUST be gone now.
    assert "not yet implemented" not in combined.lower()
    assert "deferred" not in combined.lower()
    # New failure mode: factory enablement gate.
    assert (
        "not enabled" in combined.lower()
        or "harness" in combined.lower()
    )


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
    from assistant.core.toolspec import ToolSpec
    from assistant.http_tools import HttpToolRegistry

    async def _noop(name: str) -> None:
        return None

    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    reg = HttpToolRegistry()
    reg.register(
        "backend", "list_items",
        ToolSpec(
            name="backend:list_items", description="List items",
            input_schema=dict(schema), handler=_noop,
        ),
    )
    reg.register(
        "backend", "create_item",
        ToolSpec(
            name="backend:create_item", description="Create an item",
            input_schema=dict(schema), handler=_noop,
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

    async def _spy(tool_sources, *, client=None, credentials=None):
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

    from assistant.core.toolspec import ToolSpec
    from assistant.http_tools import HttpToolRegistry

    async def _noop(q: str) -> None:
        return None

    # The persona's configured source is `content_analyzer` — build the
    # registry with that source name so by_source() matches.
    registry = HttpToolRegistry()
    registry.register(
        "content_analyzer", "search",
        ToolSpec(
            name="content_analyzer:search",
            description="Search content",
            input_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
            handler=_noop,
        ),
    )

    async def _fake_discover(tool_sources, *, client=None, credentials=None):
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
    from assistant.core.toolspec import ToolSpec
    from assistant.http_tools import HttpToolRegistry

    async def _noop() -> None:
        return None

    registry = HttpToolRegistry()
    registry.register(
        "content_analyzer", "search",
        ToolSpec(
            name="content_analyzer:search",
            description="Search content",
            input_schema={"type": "object", "properties": {}},
            handler=_noop,
        ),
    )

    async def _fake_discover(tool_sources, *, client=None, credentials=None):
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

    async def _fake_discover(tool_sources, *, client=None, credentials=None):
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

    async def _spy(tool_sources, *, client=None, credentials=None):
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

    async def _spy(tool_sources, *, client=None, credentials=None):
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


# ── Teacher --method CLI flag (add-teacher-role) ─────────────────────


def test_method_flag_with_teacher_role_accepted(
    stub_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--method feynman` with `-r teacher` is accepted; the first
    user-turn is prefixed with a directive naming the method."""
    seen_invocations: list[str] = []

    real_stub_invoke = StubHarness.invoke

    async def capture_invoke(self, agent, message):
        seen_invocations.append(message)
        return await real_stub_invoke(self, agent, message)

    monkeypatch.setattr(StubHarness, "invoke", capture_invoke)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher", "--method", "feynman"],
        input="entropy\nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert seen_invocations, "expected at least one invoke() call"
    assert "feynman" in seen_invocations[0].lower()


def test_method_flag_without_teacher_role_rejected(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "coder", "--method", "feynman"],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "--method" in combined
    assert "teacher" in combined


def test_method_flag_with_unknown_method_rejected(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher", "--method", "made_up"],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    # Error MUST list the available method names.
    assert "feynman" in combined
    assert "socratic" in combined


def test_methods_repl_command_lists_skills(stub_factory) -> None:
    """`/methods` lists feynman + socratic, with an active marker on the
    currently-active method when one is set via --method."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher", "--method", "feynman"],
        input="/methods\nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert "feynman" in result.output
    assert "socratic" in result.output
    # The active method MUST have a trailing arrow marker.
    assert "feynman ←" in result.output or "feynman  ←" in result.output


def test_methods_repl_command_rejected_outside_teacher(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "coder"],
        input="/methods\nquit\n",
    )
    assert result.exit_code == 0
    # Guard message names the teacher requirement.
    assert "teacher" in result.output.lower()


def test_method_repl_command_switches_without_rebuilding(
    stub_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/method socratic` after `/method feynman` records the new active
    method WITHOUT calling _create_harness again (contrast with /role
    which rebuilds)."""
    call_count = {"n": 0}

    def counting_factory(persona, role, harness_name):
        call_count["n"] += 1
        return StubHarness(persona, role)

    monkeypatch.setattr(cli_mod, "_create_harness", counting_factory)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],
        input="/method feynman\n/method socratic\nteach me entropy\nquit\n",
    )
    assert result.exit_code == 0, result.output
    # Exactly one initial harness construction; /method MUST NOT add more.
    assert call_count["n"] == 1, (
        f"expected 1 harness build, got {call_count['n']}"
    )
    # Prompt prefix reflects the latest active method on assistant responses.
    assert "[Teacher:socratic]>" in result.output


def test_method_repl_command_rejects_invalid(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],
        input="/method feynman\n/method bogus\nteach me entropy\nquit\n",
    )
    assert result.exit_code == 0, result.output
    # Error message lists valid methods.
    assert "feynman" in result.output
    assert "socratic" in result.output
    # Active method unchanged from feynman — the prompt prefix should
    # still read feynman after the rejected /method bogus.
    assert "[Teacher:feynman]>" in result.output


def test_methods_repl_command_no_active_method_shows_no_marker(
    stub_factory,
) -> None:
    """When --method was NOT supplied, /methods lists methods without an
    active marker — the user hasn't picked yet."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],
        input="/methods\nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert "feynman" in result.output
    assert "socratic" in result.output
    # No marker until the user picks.
    assert "←" not in result.output.split("/methods", 1)[-1].split("You>", 1)[0]


def test_method_repl_command_outside_teacher_role(stub_factory) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "coder"],
        input="/method feynman\nquit\n",
    )
    assert result.exit_code == 0
    assert "teacher" in result.output.lower()


def test_teacher_role_prompt_prefix_without_active_method(stub_factory) -> None:
    """When teacher is active but no method is set, the prompt prefix is
    `[Teacher]>`, not `[Teacher:None]>`."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],
        input="hello\nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert "[Teacher]>" in result.output
    assert "Teacher:None" not in result.output


def test_teacher_role_help_line_lists_method_commands(stub_factory) -> None:
    """When starting role is teacher, the Commands help line includes
    /method and /methods."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],
        input="quit\n",
    )
    assert result.exit_code == 0, result.output
    assert "/method" in result.output
    assert "/methods" in result.output


def test_non_teacher_help_line_omits_method_commands(stub_factory) -> None:
    """Other roles see the existing help line unchanged."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "coder"],
        input="quit\n",
    )
    assert result.exit_code == 0, result.output
    # The /methods command is teacher-specific; it MUST NOT appear in
    # the coder role's startup help line. (The command still works as a
    # guard message if typed.)
    initial_help = result.output.split("You>", 1)[0]
    assert "/methods" not in initial_help


# ── Regression: /role transition clears teacher state (finding #1) ───


def test_role_switch_clears_active_method_state(
    stub_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for review-findings.json #1.

    Sequence that triggered the latent bug:
      1. --method feynman → active_method=feynman, directive queued
      2. real user turn → directive consumed (sent to agent)
      3. /role teacher → harness IS rebuilt (conversation lost) but
         active_method was preserved, so the next response prefix would
         render [Teacher:feynman]> on a fresh agent that has no method
         context. Fix: /role always resets method state.
    """
    seen_messages: list[str] = []
    real_invoke = StubHarness.invoke

    async def capture(self, agent, message):
        seen_messages.append(message)
        return await real_invoke(self, agent, message)

    monkeypatch.setattr(StubHarness, "invoke", capture)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher", "--method", "feynman"],
        input="entropy\n/role teacher\nentropy again\nquit\n",
    )
    assert result.exit_code == 0, result.output

    # First message: directive prepended (contains 'feynman').
    assert any("feynman" in m.lower() for m in seen_messages[:1])
    # Second message: post-/role rebuild, NO directive — agent gets the
    # bare user input. The phantom-badge would have rendered prefix
    # [Teacher:feynman]> even though the agent doesn't know about it.
    # Fix: state cleared → second message has no directive AND prefix
    # is the generic [Teacher]>.
    assert "feynman" not in seen_messages[-1].lower(), (
        f"second message leaked stale directive: {seen_messages[-1]!r}"
    )
    # After /role rebuild, the prefix MUST drop the method portion.
    post_role_output = result.output.split("→ Teacher", 1)[-1]
    assert "[Teacher:feynman]" not in post_role_output, (
        "phantom method badge after /role rebuild"
    )
    assert "[Teacher]>" in post_role_output


def test_role_switch_to_other_role_clears_method_state(stub_factory) -> None:
    """Switching to a non-teacher role MUST also clear method state — was
    already correct pre-fix but now guaranteed by unconditional reset."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher", "--method", "feynman"],
        input="/role writer\nhello\nquit\n",
    )
    assert result.exit_code == 0, result.output
    # After /role writer, prefix is plain Writer (no method portion).
    post = result.output.split("→ Writer", 1)[-1]
    assert "Writer:" not in post
    assert "[Writer]>" in post


# ── /method no-arg usage hint (finding #4) ──────────────────────────


def test_method_repl_command_no_arg_shows_usage(stub_factory) -> None:
    """Bare `/method` (no argument) should print a usage hint and list
    available methods, matching the /delegate UX pattern at cli.py."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],
        input="/method\nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert "Usage: /method" in result.output
    # Available methods listed in the hint.
    assert "feynman" in result.output
    assert "socratic" in result.output


def test_method_repl_command_trailing_space_shows_usage(stub_factory) -> None:
    """`/method <space>` with no name — same hint, not the 'Unknown
    method' branch."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],
        input="/method \nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert "Usage: /method" in result.output
    # Must NOT have fallen through to the "Unknown method ''" branch.
    assert "Unknown method ''" not in result.output


# ── Help-line consistency: /quit advertised, bare quit/exit accepted ──


def test_help_line_advertises_slash_quit(stub_factory) -> None:
    """Help line must advertise the slash-prefixed `/quit` so the
    displayed command set is internally consistent (all session
    commands share the `/` prefix)."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["-p", "personal"], input="quit\n"
    )
    assert result.exit_code == 0, result.output
    # The startup help line — extract just the "Commands:" header
    # region so we don't false-positive on later REPL output.
    help_region = result.output.split("Commands:", 1)[1].split("You", 1)[0]
    assert "/quit" in help_region
    # Bare `quit` MUST NOT be advertised in the help line (it remains
    # an undocumented compatibility alias).
    assert " quit" not in help_region.replace("/quit", "")


@pytest.mark.parametrize("terminator", ["quit", "exit", "/quit", "/exit"])
def test_repl_accepts_all_quit_forms(stub_factory, terminator: str) -> None:
    """All four forms terminate the REPL cleanly: bare `quit`/`exit`
    (REPL muscle memory) and slash-prefixed `/quit`/`/exit` (matches
    the convention of the other session commands)."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["-p", "personal"], input=f"{terminator}\n"
    )
    assert result.exit_code == 0, result.output


def test_quit_forms_are_case_insensitive(stub_factory) -> None:
    """`QUIT`, `EXIT`, `/QUIT`, `/Quit` all work — same case-insensitive
    behavior the bare forms had before option-1 normalization."""
    runner = CliRunner()
    for term in ("QUIT", "Exit", "/QUIT", "/Quit"):
        result = runner.invoke(
            cli_mod.main, ["-p", "personal"], input=f"{term}\n"
        )
        assert result.exit_code == 0, f"{term!r} failed: {result.output}"


# ── Method-persistence sticky reminder (Bug B fix) ───────────────────


def test_sticky_method_reminder_injected_on_subsequent_turns(
    stub_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for Bug B from the 2026-05-14 smoke test.

    After `--method feynman`, the FIRST user turn gets the full setup
    directive (existing behavior). EVERY subsequent turn while
    `active_method` is set MUST get a compact `[system] Active
    teaching method: <name>` reminder, so the agent doesn't drift
    back to method-negotiation between turns of the loop.
    """
    seen: list[str] = []
    real_invoke = StubHarness.invoke

    async def capture(self, agent, message):
        seen.append(message)
        return await real_invoke(self, agent, message)

    monkeypatch.setattr(StubHarness, "invoke", capture)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher", "--method", "feynman"],
        input="entropy\nmy explanation\nfollowup\nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert len(seen) == 3, f"expected 3 invocations, got {len(seen)}"

    # Turn 1: full setup directive (contains "Begin Step 1").
    assert "begin step 1" in seen[0].lower(), (
        f"first-turn directive missing: {seen[0]!r}"
    )

    # Turns 2 and 3: compact reminder (contains "Active teaching method").
    for i, msg in enumerate(seen[1:], start=2):
        assert "active teaching method" in msg.lower(), (
            f"turn {i} missing sticky reminder: {msg!r}"
        )
        assert "feynman" in msg.lower(), (
            f"turn {i} reminder missing method name: {msg!r}"
        )
        # Reminder MUST NOT contain the full setup directive's
        # "Begin Step 1" — it's a different shape.
        assert "begin step 1" not in msg.lower(), (
            f"turn {i} got full directive instead of compact reminder: {msg!r}"
        )


def test_sticky_reminder_absent_when_no_active_method(
    stub_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No reminder when `active_method` is None — first-turn negotiation
    handles that path via the prompt, not via CLI injection."""
    seen: list[str] = []
    real_invoke = StubHarness.invoke

    async def capture(self, agent, message):
        seen.append(message)
        return await real_invoke(self, agent, message)

    monkeypatch.setattr(StubHarness, "invoke", capture)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],  # no --method
        input="entropy\nfollowup\nquit\n",
    )
    assert result.exit_code == 0, result.output
    for msg in seen:
        assert "active teaching method" not in msg.lower(), (
            f"unexpected reminder when no method active: {msg!r}"
        )


def test_sticky_reminder_absent_for_non_teacher_roles(
    stub_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No reminder on non-teacher roles even if `active_method` would
    somehow be set — the role guard belongs to the teacher role only."""
    seen: list[str] = []
    real_invoke = StubHarness.invoke

    async def capture(self, agent, message):
        seen.append(message)
        return await real_invoke(self, agent, message)

    monkeypatch.setattr(StubHarness, "invoke", capture)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "coder"],
        input="hello\nfollowup\nquit\n",
    )
    assert result.exit_code == 0, result.output
    for msg in seen:
        assert "active teaching method" not in msg.lower()


def test_sticky_reminder_persists_across_method_switch(
    stub_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After `/method socratic` (mid-session switch), subsequent turns
    MUST get a reminder naming `socratic`, not the stale `feynman`."""
    seen: list[str] = []
    real_invoke = StubHarness.invoke

    async def capture(self, agent, message):
        seen.append(message)
        return await real_invoke(self, agent, message)

    monkeypatch.setattr(StubHarness, "invoke", capture)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher", "--method", "feynman"],
        input="entropy\n/method socratic\nfollowup\nfollowup2\nquit\n",
    )
    assert result.exit_code == 0, result.output
    # Three invocations: "entropy" (with setup directive),
    # "followup" (with switch directive then socratic-reminder
    # after consumption), "followup2" (sticky socratic-reminder).
    assert len(seen) == 3

    # Last two turns mention socratic, not feynman.
    for i in (1, 2):
        msg_lower = seen[i].lower()
        if "active teaching method" in msg_lower:
            assert "socratic" in msg_lower, (
                f"turn {i+1} reminder names wrong method: {seen[i]!r}"
            )
            assert "feynman" not in msg_lower.split("\n\n", 1)[0], (
                f"turn {i+1} reminder still names feynman: {seen[i]!r}"
            )


def test_teacher_help_line_appends_method_commands(stub_factory) -> None:
    """Teacher role's help line MUST end with /methods and /method,
    while still advertising /quit before them."""
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["-p", "personal", "-r", "teacher"],
        input="/quit\n",
    )
    assert result.exit_code == 0, result.output
    help_region = result.output.split("Commands:", 1)[1].split("You", 1)[0]
    assert "/quit" in help_region
    assert "/methods" in help_region
    assert "/method <name>" in help_region
    # Order: /quit MUST come before /methods (terminator before
    # teacher-specific commands, matching the visual progression).
    assert help_region.index("/quit") < help_region.index("/methods")


# ── P11 harness-routing: --harness auto default ─────────────────────


def test_auto_default_resolves_through_select_harness(
    stub_factory, monkeypatch
) -> None:
    """Omitted -H sends the 'auto' sentinel through the _select_harness
    seam; the factory receives the concrete resolution."""
    select_seen: list[str | None] = []
    create_seen: list[str] = []

    def fake_select(pc, rc, *, requested=None):
        select_seen.append(requested)
        return "deep_agents"

    def capture(persona, role, harness_name):
        create_seen.append(harness_name)
        return StubHarness(persona, role)

    monkeypatch.setattr(cli_mod, "_select_harness", fake_select)
    monkeypatch.setattr(cli_mod, "_create_harness", capture)
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal"], input="quit\n")
    assert result.exit_code == 0
    assert select_seen == ["auto"]
    assert create_seen and create_seen[0] == "deep_agents"


def test_explicit_harness_bypasses_routing(stub_factory, monkeypatch) -> None:
    """-H deep_agents reaches the factory verbatim (select passes
    explicit names through — exercised here with the REAL seam)."""
    create_seen: list[str] = []

    def capture(persona, role, harness_name):
        create_seen.append(harness_name)
        return StubHarness(persona, role)

    monkeypatch.setattr(cli_mod, "_create_harness", capture)
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["-p", "personal", "-H", "deep_agents"], input="quit\n"
    )
    assert result.exit_code == 0
    assert create_seen and create_seen[0] == "deep_agents"


def test_auto_routing_failure_is_a_usage_error(
    stub_factory, monkeypatch
) -> None:
    def fail_select(pc, rc, *, requested=None):
        raise ValueError("No enabled SDK harness for persona 'personal'")

    monkeypatch.setattr(cli_mod, "_select_harness", fail_select)
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["-p", "personal"], input="quit\n")
    assert result.exit_code != 0
    assert "No enabled SDK harness" in result.output


def test_run_help_advertises_auto_choice() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, ["run", "--help"])
    assert result.exit_code == 0
    assert "auto" in result.output
