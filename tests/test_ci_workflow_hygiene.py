"""Regression guard: no GitHub workflow should reference private persona paths.

After commit 76a313e's populate-personas step was removed (design D6), no
CI workflow, action, or composite action should reference
``personas/personal/`` or ``personas/work/`` at all. If a future PR adds
such a reference, this test fails loudly at the same layer the rest of
the privacy boundary relies on.

Needles are constructed dynamically from ``FORBIDDEN_PATH_NAMES`` so this
file's own source does not contain forbidden literals (Layer 1 self-trip
avoidance, design D9 + Round 2 finding B-N4). This file is also on the
Layer 1 exclusion list as belt-and-suspenders.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._privacy_guard_config import FORBIDDEN_PATH_NAMES

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB_DIR = REPO_ROOT / ".github"


def _workflow_files() -> list[Path]:
    if not GITHUB_DIR.exists():
        return []
    return sorted(
        p
        for ext in ("yml", "yaml")
        for glob in (f"workflows/*.{ext}", f"actions/**/*.{ext}")
        for p in GITHUB_DIR.glob(glob)
    )


def _forbidden_needles() -> tuple[str, ...]:
    return tuple(f"personas/{name}/" for name in FORBIDDEN_PATH_NAMES)


@pytest.mark.parametrize("workflow_file", _workflow_files(), ids=lambda p: p.name)
def test_workflow_has_no_forbidden_persona_reference(workflow_file: Path) -> None:
    content = workflow_file.read_text()
    needles = _forbidden_needles()
    for needle in needles:
        if needle in content:
            raise AssertionError(
                f"Workflow {workflow_file.relative_to(REPO_ROOT)} references "
                f"a forbidden persona path ({needle!r}). After the populate"
                f"-personas step removal (design D6), no workflow should "
                f"read/write to the real submodule mount; use fixtures. "
                f"See docs/gotchas.md G6."
            )


def test_at_least_one_workflow_scanned() -> None:
    assert _workflow_files(), (
        "Expected .github/workflows/*.yml to exist; test_workflow_has_no_"
        "forbidden_persona_reference is silently skipping everything."
    )
