"""Tests for CLI db and export-memory commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from assistant.cli import main


@pytest.fixture
def runner():
    return CliRunner()


class TestDbUpgrade:
    def test_upgrade_invokes_alembic(self, runner):
        with patch("alembic.config.Config") as mock_config_cls, \
             patch("alembic.command.upgrade") as mock_upgrade:
            mock_cfg = MagicMock()
            mock_config_cls.return_value = mock_cfg
            result = runner.invoke(main, ["db", "upgrade"])
            assert result.exit_code == 0
            assert "Migrations applied" in result.output
            mock_upgrade.assert_called_once_with(mock_cfg, "head")


class TestDbUpgradeCheckpointerHook:
    """P30 owner-review amendment: `db upgrade -p` provisions the
    durable checkpointer schema (one command, two schema owners)."""

    def _persona(self, *, durable, database_url="postgresql://db/x"):
        persona = MagicMock()
        persona.name = "test"
        persona.sessions = MagicMock() if durable else None
        persona.database_url = database_url
        return persona

    def _invoke(self, runner, persona, setup_mock):
        with patch("alembic.config.Config"), \
             patch("alembic.command.upgrade"), \
             patch("assistant.cli.PersonaRegistry") as mock_reg_cls, \
             patch(
                 "assistant.harnesses.sdk.checkpointer.setup_durable_schema",
                 setup_mock,
             ):
            mock_reg_cls.return_value.load.return_value = persona
            return runner.invoke(main, ["db", "upgrade", "-p", "test"])

    def test_durable_persona_provisions_schema(self, runner):
        setup = AsyncMock()
        result = self._invoke(runner, self._persona(durable=True), setup)
        assert result.exit_code == 0
        assert "checkpointer schema provisioned" in result.output.lower()
        setup.assert_awaited_once_with("postgresql://db/x")

    def test_non_durable_persona_skips_provisioning(self, runner):
        setup = AsyncMock()
        result = self._invoke(runner, self._persona(durable=False), setup)
        assert result.exit_code == 0
        assert "not required" in result.output
        setup.assert_not_awaited()

    def test_durable_without_database_url_errors(self, runner):
        setup = AsyncMock()
        result = self._invoke(
            runner, self._persona(durable=True, database_url=""), setup
        )
        assert result.exit_code == 1
        assert "database url" in result.output
        setup.assert_not_awaited()

    def test_provisioning_failure_exits_nonzero(self, runner):
        setup = AsyncMock(side_effect=RuntimeError("conn refused"))
        result = self._invoke(runner, self._persona(durable=True), setup)
        assert result.exit_code == 1
        assert "conn refused" in result.output


class TestDbDowngrade:
    def test_downgrade_invokes_alembic(self, runner):
        with patch("alembic.config.Config") as mock_config_cls, \
             patch("alembic.command.downgrade") as mock_downgrade:
            mock_cfg = MagicMock()
            mock_config_cls.return_value = mock_cfg
            result = runner.invoke(main, ["db", "downgrade", "001"])
            assert result.exit_code == 0
            mock_downgrade.assert_called_once_with(mock_cfg, "001")


class TestExportMemory:
    def test_requires_persona_flag(self, runner):
        result = runner.invoke(main, ["export-memory"])
        assert result.exit_code != 0

    def test_fails_when_no_database_url(self, runner):
        persona = MagicMock()
        persona.name = "test"
        persona.database_url = ""
        mock_reg = MagicMock()
        mock_reg.load.return_value = persona

        with patch("assistant.cli.PersonaRegistry", return_value=mock_reg):
            result = runner.invoke(main, ["export-memory", "-p", "test"])
            assert result.exit_code != 0
            assert "no database_url" in result.output
