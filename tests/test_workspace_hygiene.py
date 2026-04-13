"""Regression guard: the parent pyproject must not draw submodules into a uv workspace.

Design D4 relies on the submodule's own ``[tool.uv]`` declaration to keep
``uv run pytest`` inside the submodule from reusing the parent venv. But
workspace *membership* is declared by the root, not the member — if the
parent ever adds ``[tool.uv.workspace] members = ['personas/*']`` for dev
ergonomics, the submodule's ``workspace.members = []`` cannot veto
inclusion (Round 2 finding B-N6). This test asserts no such inclusion
exists so the self-containment invariant stays load-bearing.

Needles for the forbidden members are constructed dynamically from
``FORBIDDEN_PATH_NAMES`` (same pattern as ``test_ci_workflow_hygiene``),
so Layer 1's substring scan does not self-trip. This file is also in
the Layer 1 exclusion list.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from tests._privacy_guard_config import FORBIDDEN_PATH_NAMES

REPO_ROOT = Path(__file__).resolve().parent.parent
PARENT_PYPROJECT = REPO_ROOT / "pyproject.toml"


def _load_parent_pyproject() -> dict:
    return tomllib.loads(PARENT_PYPROJECT.read_text())


def _matches_forbidden_submodule(member_glob: str) -> str | None:
    """Return the forbidden-name the glob expands to, or None."""
    for name in FORBIDDEN_PATH_NAMES:
        target = f"personas/{name}"
        if member_glob == target or member_glob == f"{target}/":
            return name
        if member_glob.startswith("personas/") and member_glob.endswith(("*", "**")):
            return name
    return None


def test_parent_pyproject_does_not_include_submodule_in_uv_workspace() -> None:
    config = _load_parent_pyproject()
    uv_workspace = config.get("tool", {}).get("uv", {}).get("workspace")
    if uv_workspace is None:
        return

    members = uv_workspace.get("members", [])
    for member in members:
        forbidden = _matches_forbidden_submodule(member)
        if forbidden is not None:
            raise AssertionError(
                f"Parent pyproject.toml declares workspace member {member!r} "
                f"that draws the private submodule personas/{forbidden}/ "
                f"into the parent venv. This defeats the self-containment "
                f"invariant (design D4 / Round-2 finding B-N6). Remove the "
                f"glob or exclude personas/ from the members list."
            )
