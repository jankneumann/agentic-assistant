"""Tests for the `assistant daemon` subcommand (P7 scheduler CLI wiring).

The async daemon body (``_run_daemon``) is stubbed via monkeypatch so
these tests exercise validation and wiring only; the scheduler runtime
itself is covered by ``tests/test_scheduler.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import assistant.cli as cli_mod

REPO_ROOT = Path(__file__).resolve().parent.parent

PERSONA_WITH_SCHEDULES = """\
name: schedp
display_name: "Sched Persona"
harnesses:
  deep_agents:
    enabled: true
schedules:
  morning:
    trigger: {cron: "0 7 * * *"}
    role: chief_of_staff
    prompt: brief me
  triage:
    trigger: {interval: 900}
    role: chief_of_staff
    prompt: triage email
"""


@pytest.fixture(autouse=True)
def chdir_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI uses relative `roles/` — run tests from the repo root."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture
def personas_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(tmp_path))
    return tmp_path


def write_persona(root: Path, name: str, content: str) -> None:
    pdir = root / name
    pdir.mkdir()
    (pdir / "persona.yaml").write_text(content)


@pytest.fixture
def daemon_stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the async daemon body with a recorder."""
    calls: dict[str, Any] = {}

    async def fake_run_daemon(
        persona_reg, role_reg, pc, harness_name, with_server, host, port
    ) -> None:
        calls.update(
            persona=pc.name,
            harness=harness_name,
            with_server=with_server,
            host=host,
            port=port,
        )

    monkeypatch.setattr(cli_mod, "_run_daemon", fake_run_daemon)
    return calls


def test_daemon_registered_in_cli_group() -> None:
    assert "daemon" in cli_mod.main.commands
    result = CliRunner().invoke(cli_mod.main, ["daemon", "--help"])
    assert result.exit_code == 0
    assert "scheduled jobs" in result.output


def test_daemon_requires_persona() -> None:
    result = CliRunner().invoke(cli_mod.main, ["daemon"])
    assert result.exit_code != 0
    assert "--persona" in result.output or "-p" in result.output


def test_daemon_errors_when_no_schedules(personas_root: Path) -> None:
    write_persona(
        personas_root,
        "plain",
        "name: plain\nharnesses:\n  deep_agents:\n    enabled: true\n",
    )
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "plain"])
    assert result.exit_code != 0
    assert "schedules" in result.output


def test_daemon_errors_when_all_jobs_disabled(personas_root: Path) -> None:
    write_persona(
        personas_root,
        "alloff",
        "name: alloff\n"
        "harnesses:\n  deep_agents:\n    enabled: true\n"
        "schedules:\n"
        "  morning:\n"
        "    trigger: {cron: '0 7 * * *'}\n"
        "    role: chief_of_staff\n"
        "    prompt: brief me\n"
        "    enabled: false\n",
    )
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "alloff"])
    assert result.exit_code != 0
    assert "enabled: false" in result.output


def test_daemon_errors_on_unknown_job_role(personas_root: Path) -> None:
    write_persona(
        personas_root,
        "badrole",
        "name: badrole\n"
        "harnesses:\n  deep_agents:\n    enabled: true\n"
        "schedules:\n"
        "  morning:\n"
        "    trigger: {cron: '0 7 * * *'}\n"
        "    role: not_a_role\n"
        "    prompt: brief me\n",
    )
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "badrole"])
    assert result.exit_code != 0
    assert "morning" in result.output
    assert "not_a_role" in result.output


def test_daemon_rejects_host_harness(personas_root: Path) -> None:
    write_persona(personas_root, "schedp", PERSONA_WITH_SCHEDULES)
    result = CliRunner().invoke(
        cli_mod.main, ["daemon", "-p", "schedp", "-H", "claude_code"]
    )
    assert result.exit_code != 0
    assert "host harness" in result.output


def test_daemon_rejects_disabled_sdk_harness(personas_root: Path) -> None:
    write_persona(personas_root, "schedp", PERSONA_WITH_SCHEDULES)
    result = CliRunner().invoke(
        cli_mod.main, ["daemon", "-p", "schedp", "-H", "ms_agent_framework"]
    )
    assert result.exit_code != 0
    assert "not enabled" in result.output


def test_daemon_happy_path_wires_run_daemon(
    personas_root: Path, daemon_stub: dict[str, Any]
) -> None:
    write_persona(personas_root, "schedp", PERSONA_WITH_SCHEDULES)
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "schedp"])
    assert result.exit_code == 0, result.output
    # P11 harness-routing: the daemon default is the 'auto' sentinel —
    # it is forwarded as-is so the job runner resolves per job (the
    # per-job startup validation already ran against the resolution).
    assert daemon_stub == {
        "persona": "schedp",
        "harness": "auto",
        "with_server": False,
        "host": "127.0.0.1",
        "port": 8765,
    }
    # Startup banner lists the enabled jobs.
    assert "morning" in result.output
    assert "triage" in result.output


def test_daemon_serve_flag_is_forwarded(
    personas_root: Path, daemon_stub: dict[str, Any]
) -> None:
    write_persona(personas_root, "schedp", PERSONA_WITH_SCHEDULES)
    result = CliRunner().invoke(
        cli_mod.main,
        ["daemon", "-p", "schedp", "--serve", "--port", "9001"],
    )
    assert result.exit_code == 0, result.output
    assert daemon_stub["with_server"] is True
    assert daemon_stub["port"] == 9001


def test_daemon_warns_on_memory_only_budget_ledger(
    personas_root: Path, daemon_stub: dict[str, Any]
) -> None:
    write_persona(
        personas_root,
        "budgeted",
        PERSONA_WITH_SCHEDULES.replace("name: schedp", "name: budgeted")
        + "guardrails:\n"
        "  budgets:\n"
        "    model_call:\n"
        "      daily_usd: 5.0\n",
    )
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "budgeted"])
    assert result.exit_code == 0, result.output
    assert "persist: file" in result.output


def test_daemon_no_budget_warning_with_file_ledger(
    personas_root: Path, daemon_stub: dict[str, Any]
) -> None:
    write_persona(
        personas_root,
        "filedger",
        PERSONA_WITH_SCHEDULES.replace("name: schedp", "name: filedger")
        + "guardrails:\n"
        "  budgets:\n"
        "    model_call:\n"
        "      daily_usd: 5.0\n"
        "      persist: file\n",
    )
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "filedger"])
    assert result.exit_code == 0, result.output
    assert "in-memory" not in result.output


# ── P11 harness-routing: per-job harness override + auto default ────


def test_daemon_rejects_job_host_harness_override(
    personas_root: Path, daemon_stub: dict[str, Any]
) -> None:
    """A per-job `harness: claude_code` fails startup naming the job."""
    write_persona(
        personas_root,
        "hostjob",
        "name: hostjob\n"
        "harnesses:\n  deep_agents:\n    enabled: true\n"
        "schedules:\n"
        "  morning:\n"
        "    trigger: {cron: '0 7 * * *'}\n"
        "    role: chief_of_staff\n"
        "    prompt: brief me\n"
        "    harness: claude_code\n",
    )
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "hostjob"])
    assert result.exit_code != 0
    assert "morning" in result.output
    assert "host harness" in result.output


def test_daemon_rejects_job_disabled_harness_override(
    personas_root: Path, daemon_stub: dict[str, Any]
) -> None:
    write_persona(
        personas_root,
        "disjob",
        PERSONA_WITH_SCHEDULES.replace("name: schedp", "name: disjob").replace(
            "    prompt: triage email\n",
            "    prompt: triage email\n    harness: ms_agent_framework\n",
        ),
    )
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "disjob"])
    assert result.exit_code != 0
    assert "triage" in result.output
    assert "not enabled" in result.output


def test_daemon_explicit_harness_is_forwarded(
    personas_root: Path, daemon_stub: dict[str, Any]
) -> None:
    write_persona(personas_root, "schedp", PERSONA_WITH_SCHEDULES)
    result = CliRunner().invoke(
        cli_mod.main, ["daemon", "-p", "schedp", "-H", "deep_agents"]
    )
    assert result.exit_code == 0, result.output
    assert daemon_stub["harness"] == "deep_agents"


def test_daemon_auto_default_validates_jobs_via_routing(
    personas_root: Path, daemon_stub: dict[str, Any]
) -> None:
    """Default -H auto: startup validation resolves each job through
    select_harness (deep_agents here) and the daemon starts."""
    write_persona(personas_root, "schedp", PERSONA_WITH_SCHEDULES)
    result = CliRunner().invoke(cli_mod.main, ["daemon", "-p", "schedp"])
    assert result.exit_code == 0, result.output
    assert daemon_stub["harness"] == "auto"
