"""Tests for the P22 Omnigent-shaped agent-definition export and the
meta-harness documentation deliverables (ADR 0007, deployment doc)."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

import assistant.cli as cli_mod
from assistant.composition.omnigent import (
    UNVERIFIED_SCHEMA_HEADER,
    build_omnigent_agent_definition,
    render_omnigent_agent_yaml,
)
from assistant.core.persona import A2AAuthConfig, PersonaConfig
from assistant.core.role import RoleConfig

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_persona(**overrides: object) -> PersonaConfig:
    defaults: dict[str, object] = dict(
        name="fixture",
        display_name="Fixture Persona",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={},
        tool_sources={},
        extensions=[],
        extensions_dir=Path("/nonexistent"),
    )
    defaults.update(overrides)
    return PersonaConfig(**defaults)  # type: ignore[arg-type]


def make_role(name: str, description: str = "does things") -> RoleConfig:
    return RoleConfig(
        name=name,
        display_name=name.title(),
        description=description,
        prompt="",
    )


def test_definition_carries_persona_identity_and_endpoints() -> None:
    persona = make_persona()
    roles = [make_role("coder"), make_role("writer")]
    d = build_omnigent_agent_definition(
        persona, roles, base_url="http://gx10:8765/"
    )
    assert d["name"] == "fixture"
    assert d["display_name"] == "Fixture Persona"
    assert "persona 'fixture'" in d["description"]
    api = d["api"]
    assert api["a2a"]["agent_card"] == (
        "http://gx10:8765/.well-known/agent-card.json"
    )
    assert api["a2a"]["rpc"] == "http://gx10:8765/a2a/v1"
    assert api["mcp"]["endpoint"] == "http://gx10:8765/mcp"
    assert api["mcp"]["tools"] == ["ask", "ask_coder", "ask_writer"]
    assert api["ag_ui"]["chat"] == "http://gx10:8765/chat"
    assert api["ag_ui"]["health"] == "http://gx10:8765/health"


def test_definition_skills_mirror_roles() -> None:
    d = build_omnigent_agent_definition(
        make_persona(),
        [make_role("coder", "writes code")],
        base_url="http://x",
    )
    assert d["skills"] == [
        {"id": "coder", "name": "Coder", "description": "writes code"}
    ]


def test_definition_auth_shape_from_p25_declaration_without_token_value() -> None:
    persona = make_persona(
        a2a_auth=A2AAuthConfig(type="bearer", token_env="A2A_TOKEN")
    )
    d = build_omnigent_agent_definition(persona, [], base_url="http://x")
    assert d["auth"]["a2a"] == {"type": "bearer", "token_env": "A2A_TOKEN"}


def test_definition_auth_none_when_undeclared() -> None:
    d = build_omnigent_agent_definition(make_persona(), [], base_url="http://x")
    assert d["auth"]["a2a"]["type"] == "none"
    assert "loopback" in d["auth"]["a2a"]["note"]


def test_definition_marks_schema_unverified() -> None:
    d = build_omnigent_agent_definition(make_persona(), [], base_url="http://x")
    assert d["x_generator"]["schema_verified"] is False


def test_rendered_yaml_has_unverified_header_and_parses() -> None:
    d = build_omnigent_agent_definition(
        make_persona(), [make_role("coder")], base_url="http://x"
    )
    text = render_omnigent_agent_yaml(d)
    assert text.startswith(UNVERIFIED_SCHEMA_HEADER)
    assert "verify" in text.lower()
    assert "omnigent-ai/omnigent" in text
    parsed = yaml.safe_load(text)
    assert parsed["kind"] == "external-agent"
    assert parsed["name"] == "fixture"


# -- CLI command (fixture persona via conftest ASSISTANT_PERSONAS_DIR) ----


def test_cli_export_omnigent_agent_stdout(
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["export-omnigent-agent", "-p", "personal", "--base-url", "http://h:1"],
    )
    assert result.exit_code == 0, result.output
    parsed = yaml.safe_load(result.output)
    assert parsed["name"] == "personal"
    assert parsed["api"]["a2a"]["rpc"] == "http://h:1/a2a/v1"
    assert "ask_chief_of_staff" in parsed["api"]["mcp"]["tools"]
    assert any(s["id"] == "coder" for s in parsed["skills"])


def test_cli_export_omnigent_agent_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "agent.yaml"
    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        ["export-omnigent-agent", "-p", "personal", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "VERIFY BEFORE USE" in out.read_text()


def test_cli_export_omnigent_agent_requires_persona() -> None:
    result = CliRunner().invoke(cli_mod.main, ["export-omnigent-agent"])
    assert result.exit_code != 0
    assert "persona" in result.output.lower()


# -- documentation deliverables (P22) -------------------------------------


def test_adr_0007_exists_with_required_sections_and_verdicts() -> None:
    adr = REPO_ROOT / "docs" / "decisions" / "0007-meta-harness-posture.md"
    assert adr.exists(), "ADR 0007 (meta-harness posture) is a P22 deliverable"
    text = adr.read_text()
    for section in ("## Status", "## Context", "## Decision", "## Consequences"):
        assert section in text, f"ADR 0007 missing section {section!r}"
    assert "ACCEPTED" in text
    # Per-meta-harness verdicts.
    assert "Omnigent" in text
    assert "NemoClaw" in text
    assert "OpenShell" in text
    # Honest-uncertainty caveat for the disconnected environment.
    assert "verify" in text.lower()
    # Indexed in the ADR README.
    readme = REPO_ROOT / "docs" / "decisions" / "README.md"
    assert "0007" in readme.read_text()


def test_meta_harness_deployment_doc_exists() -> None:
    doc = REPO_ROOT / "docs" / "deployment" / "meta-harness.md"
    assert doc.exists()
    text = doc.read_text()
    assert "Omnigent" in text
    assert "NemoClaw" in text
    assert "export-omnigent-agent" in text
