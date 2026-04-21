"""Tests for CLI db and export-memory commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
