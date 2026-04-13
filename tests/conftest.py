"""Shared pytest fixtures + two-layer privacy-boundary guard.

Public tests run against the in-repo ``tests/fixtures/personas/`` root so the
suite stays green without the private ``personas/<name>/`` submodules being
initialized (spec: test-privacy-boundary / public-test-fixture-root).

This conftest also implements **Layer 1** of the privacy-boundary guard:
a ``pytest_collection_modifyitems`` hook that scans every collected test
file (and every conftest under ``tests/``) for forbidden path substrings
defined in ``tests/_privacy_guard_config.py``. **Layer 2** (runtime FS-I/O
patching) lives in ``tests/_privacy_guard_plugin.py`` and is wired in via
``pytest_plugins`` below. See that module and
``openspec/changes/test-privacy-boundary/design.md`` D1+D9 for details.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._privacy_guard_config import (
    FORBIDDEN_PATH_NAMES,
    SCAN_EXCLUDED_DIRS,
    SCAN_EXCLUDED_FILES,
)

# Layer 2 runtime guard -- registered as a plugin so its pytest_configure
# hook runs before any test collects (so the self-probe fires before any
# test body can read private content).
pytest_plugins = ["tests._privacy_guard_plugin"]


REPO_ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = REPO_ROOT / "roles"
# Public-test persona root: the in-repo fixture tree. Public tests MUST NOT
# read from ``REPO_ROOT / "personas"`` (the real submodule mount) -- the
# Layer 2 runtime guard will reject any such read.
PERSONAS_DIR = REPO_ROOT / "tests" / "fixtures" / "personas"

# Point every in-process PersonaRegistry (including the one the CLI builds
# via `assistant -p personal`) at the fixture root for the duration of the
# pytest session. Production callers with the env var unset keep their
# existing default (Path("personas")).
os.environ.setdefault("ASSISTANT_PERSONAS_DIR", str(PERSONAS_DIR))


@pytest.fixture
def roles_dir() -> Path:
    return ROLES_DIR


@pytest.fixture
def personas_dir() -> Path:
    return PERSONAS_DIR


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


# ── Layer 1: collection-time substring scan ────────────────────────────


# Cache of already-scanned files keyed on POSIX repo-relative path, so
# each file's source is read once per session even if multiple items
# resolve to it.
_SCANNED_FILES: set[str] = set()


def _forbidden_substrings() -> tuple[str, ...]:
    """Build needles dynamically from the deny-list config.

    Keeps this conftest free of forbidden literals (so it doesn't self-trip
    when Layer 1 scans itself) and auto-extends when a new persona name is
    added to ``FORBIDDEN_PATH_NAMES``.
    """
    return tuple(f"personas/{name}/" for name in FORBIDDEN_PATH_NAMES)


def _is_excluded(rel_posix: str) -> bool:
    if rel_posix in SCAN_EXCLUDED_FILES:
        return True
    for d in SCAN_EXCLUDED_DIRS:
        if rel_posix.startswith(d):
            return True
    return False


def _scan_file(rel_posix: str, abs_path: Path) -> None:
    """Scan one file for forbidden substrings; raise on violation.

    Uses the saved original ``Path.read_text`` via the Layer 2 plugin's
    stash if present (the plugin allow-lists our own scan; ``tests/`` is
    not under ``personas/<forbidden>/`` so it isn't flagged anyway).
    """
    if rel_posix in _SCANNED_FILES:
        return
    _SCANNED_FILES.add(rel_posix)
    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return  # non-readable or binary -- nothing to scan
    for needle in _forbidden_substrings():
        if needle in source:
            raise pytest.UsageError(
                f"Privacy-boundary violation: {rel_posix} contains "
                f"forbidden path prefix {needle!r}. Public tests must use "
                "tests/fixtures/ instead. Add the file to "
                "tests/_privacy_guard_config.SCAN_EXCLUDED_FILES only if "
                "it legitimately needs the substring as data (hygiene "
                "tests). See docs/gotchas.md G6."
            )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Layer 1: scan every collected test file + conftest for forbidden paths.

    Runs once per collection. Scans each unique source file once (memoized
    via ``_SCANNED_FILES``). On first violation, raises ``pytest.UsageError``
    naming the file and matched deny-list entry, NOT echoing the file's
    contents (spec: "Guard failure messages do not echo private payloads").
    """
    repo_root = REPO_ROOT.resolve()

    # Collect unique test-file paths from items.
    candidate_paths: set[Path] = set()
    for item in items:
        fs_path = getattr(item, "path", None)
        if fs_path is None:
            continue
        try:
            candidate_paths.add(Path(str(fs_path)).resolve())
        except Exception:
            continue

    # Also scan every conftest.py under tests/ (D9: fixtures-via-conftest
    # bypass closure). rglob via the original Path.rglob -- Layer 2 guard
    # does not patch rglob, so this is safe.
    tests_root = repo_root / "tests"
    if tests_root.is_dir():
        for conftest in tests_root.rglob("conftest.py"):
            try:
                candidate_paths.add(conftest.resolve())
            except Exception:
                continue

    for abs_path in candidate_paths:
        try:
            rel = abs_path.relative_to(repo_root)
        except ValueError:
            continue  # outside repo -- not in scope
        rel_posix = rel.as_posix()
        if _is_excluded(rel_posix):
            continue
        _scan_file(rel_posix, abs_path)
