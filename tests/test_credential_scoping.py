"""Tests for per-persona credential scoping — security-hardening (P13).

Covers: ``.env`` parsing, persona-scoped resolution precedence
(persona ``.env`` first, process env fallback), cross-persona
isolation without ``os.environ`` pollution, persona load routing all
secret reads through the injected ``CredentialProvider``, and the
auth-header resolution path consuming the persona provider.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from assistant.core.capabilities.credentials import (
    CredentialProvider,
    EnvCredentialProvider,
    load_env_file,
    parse_env_file,
    persona_credential_provider,
)
from assistant.core.persona import PersonaRegistry
from assistant.http_tools.auth import resolve_auth_header

# ── .env parsing ─────────────────────────────────────────────────────


def test_parse_env_file_basic_forms() -> None:
    values = parse_env_file(
        textwrap.dedent(
            """
            # comment line
            PLAIN=value
            export EXPORTED=exported-value
            SPACED = padded
            DQUOTED="quoted value"
            SQUOTED='single quoted'
            EMPTY=
            """
        )
    )
    assert values == {
        "PLAIN": "value",
        "EXPORTED": "exported-value",
        "SPACED": "padded",
        "DQUOTED": "quoted value",
        "SQUOTED": "single quoted",
        "EMPTY": "",
    }


def test_parse_env_file_skips_malformed_lines_without_leaking_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        values = parse_env_file(
            "GOOD=ok\nthis is not an assignment sekrit-value\n1BAD=x\n"
        )
    assert values == {"GOOD": "ok"}
    assert len(caplog.records) == 2
    for record in caplog.records:
        assert "sekrit-value" not in record.getMessage()


def test_load_env_file_missing_returns_empty(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / ".env") == {}


# ── EnvCredentialProvider precedence ─────────────────────────────────


def test_scoped_value_wins_over_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("P13_TEST_TOKEN", "process-value")
    provider = EnvCredentialProvider(scoped={"P13_TEST_TOKEN": "scoped-value"})
    assert provider.get_credential("P13_TEST_TOKEN") == "scoped-value"


def test_unscoped_ref_falls_back_to_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("P13_TEST_FALLBACK", "process-value")
    provider = EnvCredentialProvider(scoped={"OTHER": "x"})
    assert provider.get_credential("P13_TEST_FALLBACK") == "process-value"


def test_empty_scoped_value_masks_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("P13_TEST_MASKED", "process-value")
    provider = EnvCredentialProvider(scoped={"P13_TEST_MASKED": ""})
    assert provider.get_credential("P13_TEST_MASKED") == ""


def test_default_provider_preserves_env_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("P13_UNSET_VAR", raising=False)
    provider = EnvCredentialProvider()
    assert provider.get_credential("") == ""
    assert provider.get_credential("P13_UNSET_VAR") == ""


def test_persona_provider_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(
        persona_credential_provider(tmp_path), CredentialProvider
    )


# ── cross-persona isolation ──────────────────────────────────────────


def _write_persona(root: Path, name: str, env_lines: str | None) -> None:
    persona_dir = root / name
    persona_dir.mkdir(parents=True)
    (persona_dir / "persona.yaml").write_text(
        textwrap.dedent(
            f"""
            name: {name}
            display_name: {name}
            database: {{url_env: SHARED_DB_URL}}
            graphiti: {{url_env: ""}}
            auth:
              provider: custom
              config:
                api_key_env: SHARED_API_KEY
            tool_sources:
              src_a:
                base_url_env: SHARED_BASE_URL
                auth_header:
                  type: bearer
                  env: SHARED_BEARER
                allowed_tools: []
            """
        )
    )
    if env_lines is not None:
        (persona_dir / ".env").write_text(env_lines)


def test_two_personas_resolve_same_ref_to_different_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same env-var NAME, different per-persona .env values — and the
    process environment is never polluted by either."""
    monkeypatch.delenv("SHARED_DB_URL", raising=False)
    monkeypatch.delenv("SHARED_API_KEY", raising=False)
    _write_persona(
        tmp_path,
        "alpha",
        "SHARED_DB_URL=postgresql://localhost/alpha\nSHARED_API_KEY=alpha-key\n",
    )
    _write_persona(
        tmp_path,
        "beta",
        "SHARED_DB_URL=postgresql://localhost/beta\nSHARED_API_KEY=beta-key\n",
    )

    registry = PersonaRegistry(tmp_path)
    alpha = registry.load("alpha")
    beta = registry.load("beta")

    assert alpha.database_url == "postgresql://localhost/alpha"
    assert beta.database_url == "postgresql://localhost/beta"
    assert alpha.auth_config["api_key_env"] == "alpha-key"
    assert beta.auth_config["api_key_env"] == "beta-key"

    # Isolation: neither persona's .env leaked into the process env.
    assert "SHARED_DB_URL" not in os.environ
    assert "SHARED_API_KEY" not in os.environ

    # And each persona's provider stays scoped to its own namespace.
    assert alpha.credentials.get_credential("SHARED_API_KEY") == "alpha-key"
    assert beta.credentials.get_credential("SHARED_API_KEY") == "beta-key"


def test_persona_env_wins_over_process_env_at_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHARED_DB_URL", "postgresql://localhost/process")
    _write_persona(
        tmp_path, "alpha", "SHARED_DB_URL=postgresql://localhost/dotenv\n"
    )
    registry = PersonaRegistry(tmp_path)
    assert (
        registry.load("alpha").database_url == "postgresql://localhost/dotenv"
    )


def test_persona_without_env_file_falls_back_to_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHARED_DB_URL", "postgresql://localhost/process")
    _write_persona(tmp_path, "alpha", None)
    registry = PersonaRegistry(tmp_path)
    assert (
        registry.load("alpha").database_url
        == "postgresql://localhost/process"
    )


# ── injected CredentialProvider (spec: backend swap) ─────────────────


def test_persona_load_uses_injected_credential_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All persona-config secret reads flow through the injected
    provider — never a direct os.environ read."""
    monkeypatch.setenv("SHARED_DB_URL", "process-value-must-not-win")
    _write_persona(tmp_path, "alpha", None)

    seen_refs: list[str] = []

    class RecordingProvider:
        def get_credential(self, ref: str) -> str:
            seen_refs.append(ref)
            return f"vault::{ref}" if ref else ""

    registry = PersonaRegistry(
        tmp_path,
        credential_provider_factory=lambda name, d: RecordingProvider(),
    )
    config = registry.load("alpha")

    assert config.database_url == "vault::SHARED_DB_URL"
    assert config.auth_config["api_key_env"] == "vault::SHARED_API_KEY"
    assert config.tool_sources["src_a"]["base_url"] == "vault::SHARED_BASE_URL"
    assert "SHARED_DB_URL" in seen_refs
    assert config.credentials is not None


# ── auth-header resolution through the seam ──────────────────────────


def test_resolve_auth_header_uses_persona_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("P13_SRC_TOKEN", raising=False)
    provider = EnvCredentialProvider(scoped={"P13_SRC_TOKEN": "tok-123"})
    headers = resolve_auth_header(
        {"type": "bearer", "env": "P13_SRC_TOKEN"}, provider
    )
    assert headers == {"Authorization": "Bearer tok-123"}


def test_resolve_auth_header_empty_resolution_raises_keyerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("P13_SRC_TOKEN", raising=False)
    with pytest.raises(KeyError) as excinfo:
        resolve_auth_header({"type": "bearer", "env": "P13_SRC_TOKEN"})
    assert "P13_SRC_TOKEN" in str(excinfo.value)


def test_persona_config_repr_hides_credential_namespace(
    tmp_path: Path,
) -> None:
    """The scoped .env namespace (repr=False) never leaks via repr —
    even for keys no config field references."""
    _write_persona(
        tmp_path, "alpha", "UNREFERENCED_SECRET=super-secret-value\n"
    )
    config = PersonaRegistry(tmp_path).load("alpha")
    assert "super-secret-value" not in repr(config)
    assert (
        config.credentials.get_credential("UNREFERENCED_SECRET")
        == "super-secret-value"
    )
