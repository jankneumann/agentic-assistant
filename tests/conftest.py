"""Shared pytest fixtures.

All tests run against the real in-repo `roles/` and `personas/` directories.
A fresh per-test working directory would break the submodule layout, so tests
use the canonical project-root paths resolved from this file's location.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = REPO_ROOT / "roles"
PERSONAS_DIR = REPO_ROOT / "personas"


@pytest.fixture
def roles_dir() -> Path:
    return ROLES_DIR


@pytest.fixture
def personas_dir() -> Path:
    return PERSONAS_DIR


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
