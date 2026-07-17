"""Tests for the private-extension integrity manifest — security-hardening (P13).

Covers: manifest generation, verify-before-exec (verified load,
missing-manifest warning, mismatch/unlisted/malformed disable with
ERROR and no execution, no fallback to a public module), sibling
isolation, and the ``assistant persona hash-extensions`` subcommand.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from assistant.core.extension_integrity import (
    MANIFEST_FILENAME,
    IntegrityVerdict,
    check_extension_integrity,
    file_sha256,
    generate_manifest,
    load_manifest,
)
from assistant.core.persona import PersonaConfig, PersonaRegistry

_EXT_TEMPLATE = """
EXECUTED = True


class _Ext:
    def __init__(self, config, persona=None):
        self.name = "{name}"
        self.scopes = config.get("scopes", [])

    def tool_specs(self):
        return []

    async def health_check(self):
        from assistant.core.resilience import (
            default_health_status_for_unimplemented,
        )
        return default_health_status_for_unimplemented(self.name)


def create_extension(config, *, persona=None):
    return _Ext(config, persona=persona)
"""


def _write_ext(extensions_dir: Path, name: str) -> Path:
    extensions_dir.mkdir(parents=True, exist_ok=True)
    path = extensions_dir / f"{name}.py"
    path.write_text(textwrap.dedent(_EXT_TEMPLATE.format(name=name)))
    return path


def _make_persona(tmp_path: Path, modules: list[str]) -> PersonaConfig:
    extensions_dir = tmp_path / "extensions"
    for mod in modules:
        _write_ext(extensions_dir, mod)
    return PersonaConfig(
        name="integrity_test",
        display_name="integrity_test",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={},
        tool_sources={},
        extensions=[
            {"name": mod, "module": mod, "config": {}} for mod in modules
        ],
        extensions_dir=extensions_dir,
    )


# ── manifest generation + low-level checks ───────────────────────────


def test_generate_manifest_hashes_all_py_files(tmp_path: Path) -> None:
    ext_dir = tmp_path / "extensions"
    path_a = _write_ext(ext_dir, "ext_a")
    path_b = _write_ext(ext_dir, "ext_b")

    hashes = generate_manifest(ext_dir)

    assert set(hashes) == {"ext_a.py", "ext_b.py"}
    assert hashes["ext_a.py"] == file_sha256(path_a)
    assert hashes["ext_b.py"] == file_sha256(path_b)
    on_disk = yaml.safe_load((ext_dir / MANIFEST_FILENAME).read_text())
    assert on_disk["version"] == 1
    assert on_disk["hashes"] == hashes


def test_generate_manifest_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        generate_manifest(tmp_path / "nope")


def test_load_manifest_absent_returns_none(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    assert load_manifest(tmp_path) is None


def test_check_verdicts(tmp_path: Path) -> None:
    ext_dir = tmp_path / "extensions"
    path = _write_ext(ext_dir, "ext_a")

    # No manifest → UNVERIFIED (allowed with warning).
    assert (
        check_extension_integrity(ext_dir, path).verdict
        is IntegrityVerdict.UNVERIFIED
    )

    generate_manifest(ext_dir)
    assert (
        check_extension_integrity(ext_dir, path).verdict
        is IntegrityVerdict.VERIFIED
    )

    # Tamper → MISMATCH, blocked.
    path.write_text(path.read_text() + "\n# tampered\n")
    check = check_extension_integrity(ext_dir, path)
    assert check.verdict is IntegrityVerdict.MISMATCH
    assert check.blocked

    # File present but not listed → UNLISTED, blocked.
    unlisted = _write_ext(ext_dir, "ext_new")
    check = check_extension_integrity(ext_dir, unlisted)
    assert check.verdict is IntegrityVerdict.UNLISTED
    assert check.blocked

    # Malformed manifest → MALFORMED, blocked.
    (ext_dir / MANIFEST_FILENAME).write_text("just a string\n")
    check = check_extension_integrity(ext_dir, path)
    assert check.verdict is IntegrityVerdict.MALFORMED
    assert check.blocked


def test_bare_hex_digest_accepted(tmp_path: Path) -> None:
    ext_dir = tmp_path / "extensions"
    path = _write_ext(ext_dir, "ext_a")
    bare = file_sha256(path).removeprefix("sha256:")
    (ext_dir / MANIFEST_FILENAME).write_text(
        yaml.safe_dump({"version": 1, "hashes": {"ext_a.py": bare}})
    )
    assert (
        check_extension_integrity(ext_dir, path).verdict
        is IntegrityVerdict.VERIFIED
    )


# ── registry verify-before-exec behavior ─────────────────────────────


def test_verified_extension_loads_silently(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    persona = _make_persona(tmp_path, ["ext_ok"])
    generate_manifest(persona.extensions_dir)
    registry = PersonaRegistry(tmp_path / "personas")
    with caplog.at_level("WARNING"):
        loaded = registry.load_extensions(persona)
    assert [e.name for e in loaded] == ["ext_ok"]
    assert not caplog.records


def test_missing_manifest_loads_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    persona = _make_persona(tmp_path, ["ext_ok"])
    registry = PersonaRegistry(tmp_path / "personas")
    with caplog.at_level("WARNING"):
        loaded = registry.load_extensions(persona)
    assert [e.name for e in loaded] == ["ext_ok"]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "UNVERIFIED" in warnings[0].getMessage()


def test_mismatched_extension_is_not_executed_and_disabled(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Tampered file: ERROR log, never executed, sibling still loads."""
    persona = _make_persona(tmp_path, ["ext_bad", "ext_good"])
    generate_manifest(persona.extensions_dir)
    tampered = persona.extensions_dir / "ext_bad.py"
    tampered.write_text(
        "raise SystemExit('tampered code must never execute')\n"
        + tampered.read_text()
    )

    registry = PersonaRegistry(tmp_path / "personas")
    with caplog.at_level("ERROR"):
        loaded = registry.load_extensions(persona)

    assert [e.name for e in loaded] == ["ext_good"]
    errors = [r for r in caplog.records if r.levelno >= 40]
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert "ext_bad" in message
    assert "hash-extensions" in message


def test_mismatch_does_not_fall_back_to_public_module(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A blocked private file must not silently swap to the public
    implementation of the same module name (here: the gmail stub)."""
    extensions_dir = tmp_path / "extensions"
    _write_ext(extensions_dir, "gmail")
    generate_manifest(extensions_dir)
    (extensions_dir / "gmail.py").write_text("TAMPERED = True\n")

    persona = PersonaConfig(
        name="integrity_test",
        display_name="integrity_test",
        database_url="",
        graphiti_url="",
        auth_provider="custom",
        auth_config={},
        harnesses={},
        tool_sources={},
        extensions=[{"name": "gmail", "module": "gmail", "config": {}}],
        extensions_dir=extensions_dir,
    )
    registry = PersonaRegistry(tmp_path / "personas")
    with caplog.at_level("ERROR"):
        loaded = registry.load_extensions(persona)
    assert loaded == []


def test_malformed_manifest_blocks_all_private_extensions(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    persona = _make_persona(tmp_path, ["ext_a", "ext_b"])
    (persona.extensions_dir / MANIFEST_FILENAME).write_text("[not, a, map]\n")
    registry = PersonaRegistry(tmp_path / "personas")
    with caplog.at_level("ERROR"):
        loaded = registry.load_extensions(persona)
    assert loaded == []
    assert len([r for r in caplog.records if r.levelno >= 40]) == 2


# ── CLI: assistant persona hash-extensions ───────────────────────────


def _write_cli_persona(root: Path, name: str) -> Path:
    persona_dir = root / name
    persona_dir.mkdir(parents=True)
    (persona_dir / "persona.yaml").write_text(
        f"name: {name}\ndisplay_name: {name}\n"
        "database: {url_env: ''}\ngraphiti: {url_env: ''}\n"
        "auth: {provider: custom, config: {}}\n"
    )
    return persona_dir


def test_cli_hash_extensions_writes_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assistant import cli as cli_mod

    persona_dir = _write_cli_persona(tmp_path, "hashme")
    _write_ext(persona_dir / "extensions", "ext_a")
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["persona", "hash-extensions", "-p", "hashme"]
    )

    assert result.exit_code == 0, result.output
    assert "ext_a.py" in result.output
    manifest = yaml.safe_load(
        (persona_dir / "extensions" / MANIFEST_FILENAME).read_text()
    )
    assert "ext_a.py" in manifest["hashes"]


def test_cli_hash_extensions_missing_dir_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assistant import cli as cli_mod

    _write_cli_persona(tmp_path, "hashme")
    monkeypatch.setenv("ASSISTANT_PERSONAS_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main, ["persona", "hash-extensions", "-p", "hashme"]
    )
    assert result.exit_code == 1
    assert "does not exist" in result.output
