"""CLI tests for the `assistant cleanroom` command group (P26)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from assistant.cli import main
from assistant.core import cleanroom as cr
from tests.test_cleanroom import FakeMemoryManager, _seeded_manager


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _patch_manager(
    monkeypatch: pytest.MonkeyPatch, manager: FakeMemoryManager
) -> None:
    monkeypatch.setattr(
        "assistant.cli._cleanroom_manager", lambda pc: manager
    )


def _write_fixture_bundle(space: Path) -> dict[str, Any]:
    """Drop a minimal alpha→beta bundle into the given space dir."""
    content = "shared note"
    item = {
        "item_id": "fact:note",
        "kind": "fact",
        "key": "note",
        "content": content,
        "content_hash": cr.content_hash(content),
    }
    payload: dict[str, Any] = {
        "format": cr.BUNDLE_FORMAT,
        "version": cr.BUNDLE_VERSION,
        "bundle_id": "cafebabe" * 4,
        "source_persona": "cleanroom_alpha",
        "audience": "cleanroom_beta",
        "profile": "standard",
        "exported_at": "2026-07-17T00:00:00+00:00",
        "exporter": {
            "persona": "cleanroom_alpha",
            "role": "chief_of_staff",
            "delegation_chain": [],
            "session_id": "",
            "issued_at": "2026-07-17T00:00:00+00:00",
        },
        "items": [item],
    }
    payload["bundle_hash"] = cr.compute_bundle_hash(payload)
    path = space / "cleanroom_beta" / f"{payload['bundle_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_export_requires_database_url(runner: CliRunner):
    # Fixture personas resolve no CLEANROOM_ALPHA_DATABASE_URL, so the
    # command must fail actionably before touching the gateway.
    result = runner.invoke(
        main,
        ["cleanroom", "export", "-p", "cleanroom_alpha", "--to", "cleanroom_beta"],
    )
    assert result.exit_code == 1
    assert "no database_url" in result.output


def test_export_writes_bundle_to_default_space(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    _patch_manager(monkeypatch, _seeded_manager())
    with runner.isolated_filesystem():
        result = runner.invoke(
            main,
            [
                "cleanroom",
                "export",
                "-p",
                "cleanroom_alpha",
                "--to",
                "cleanroom_beta",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Exported 2 item(s)" in result.output
        bundles = list(Path(".cleanroom/cleanroom_beta").glob("*.json"))
        assert len(bundles) == 1


def test_export_refused_without_clean_room_section(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    _patch_manager(monkeypatch, FakeMemoryManager())
    with runner.isolated_filesystem():
        result = runner.invoke(
            main,
            ["cleanroom", "export", "-p", "personal", "--to", "cleanroom_beta"],
        )
        assert result.exit_code == 1
        assert "no clean_room" in result.output


def test_import_and_sync_flow(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    consumer = FakeMemoryManager()
    _patch_manager(monkeypatch, consumer)
    with runner.isolated_filesystem():
        payload = _write_fixture_bundle(Path(".cleanroom"))
        bundle_file = (
            Path(".cleanroom/cleanroom_beta") / f"{payload['bundle_id']}.json"
        )

        result = runner.invoke(
            main,
            ["cleanroom", "import", "-p", "cleanroom_beta", str(bundle_file)],
        )
        assert result.exit_code == 0, result.output
        assert "Imported 1 item(s)" in result.output
        assert len(consumer.stored) == 1

        # Source persona revokes; the consumer's next sync purges.
        result = runner.invoke(
            main,
            ["cleanroom", "revoke", "-p", "cleanroom_alpha", payload["bundle_id"]],
        )
        assert result.exit_code == 0, result.output
        assert Path(
            f".cleanroom/revocations/{payload['bundle_id']}.json"
        ).is_file()

        result = runner.invoke(
            main, ["cleanroom", "sync", "-p", "cleanroom_beta"]
        )
        assert result.exit_code == 0, result.output
        assert "Purged 1" in result.output
        assert consumer.stored == {}

        # Re-import after revocation is refused.
        result = runner.invoke(
            main,
            ["cleanroom", "import", "-p", "cleanroom_beta", str(bundle_file)],
        )
        assert result.exit_code == 1
        assert "revoked" in result.output


def test_revoke_by_non_source_persona_fails(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    with runner.isolated_filesystem():
        payload = _write_fixture_bundle(Path(".cleanroom"))
        result = runner.invoke(
            main,
            ["cleanroom", "revoke", "-p", "cleanroom_beta", payload["bundle_id"]],
        )
        assert result.exit_code == 1
        assert "only" in result.output
