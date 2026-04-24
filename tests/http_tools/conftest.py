"""Shared fixtures for ``tests/http_tools``.

Exposes:

- ``fixtures_dir``    — path to the OpenAPI fixture directory under
  ``openspec/changes/http-tools-layer/contracts/fixtures/``.
- ``load_fixture``    — callable that loads a fixture file by name and
  returns the parsed JSON payload.
- ``httpserver``      — re-exported from ``pytest_httpserver`` so tests
  in this package can spin up a local HTTP server without declaring
  the plugin explicitly.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# pytest-httpserver's plugin is auto-registered via setuptools entry
# points when the package is installed (see wp-prep / pyproject.toml);
# no explicit `pytest_plugins` declaration is needed, and declaring it
# at subpackage level is rejected when pytest is invoked from the
# top-level ``tests/`` directory.


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_DIR = (
    _REPO_ROOT
    / "openspec"
    / "changes"
    / "http-tools-layer"
    / "contracts"
    / "fixtures"
)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Absolute path to the OpenAPI fixture directory."""
    return _FIXTURES_DIR


@pytest.fixture(scope="session")
def load_fixture(fixtures_dir: Path) -> Callable[[str], dict[str, Any]]:
    """Return a loader that reads a named fixture as parsed JSON."""

    def _load(name: str) -> dict[str, Any]:
        return json.loads((fixtures_dir / name).read_text())

    return _load
