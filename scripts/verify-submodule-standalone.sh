#!/usr/bin/env bash
# verify-submodule-standalone.sh — fresh-venv standalone proof for the
# personas/personal submodule test suite (task 3.6, design D4).
#
# Contract:
#   1. Create a fresh venv at a unique path.
#   2. Install ONLY pytest>=8 and pyyaml>=6 (pinned minimums per B-N7).
#   3. cd into personas/personal BEFORE invoking pytest so rootdir is the
#      submodule's pyproject.toml, not the parent repo's (Round 2 B-N7).
#   4. Run pytest with --override-ini='addopts=' to defeat any inherited
#      addopts from the parent's pytest config.
#   5. Clean up the venv via trap on EXIT / INT / TERM.
#
# Exit 0 on pass; non-zero on any failure (pytest or setup).

set -euo pipefail

VENV="/tmp/spb-venv-$$"

cleanup() {
    rm -rf "$VENV"
}
trap cleanup EXIT INT TERM

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SUBMODULE_DIR="$REPO_ROOT/personas/personal"

if [[ ! -d "$SUBMODULE_DIR" ]]; then
    echo "ERROR: submodule dir not found at $SUBMODULE_DIR" >&2
    exit 1
fi

echo "Creating fresh venv at $VENV ..."
python3 -m venv "$VENV"

echo "Installing pytest>=8 and pyyaml>=6 ..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet 'pytest>=8' 'pyyaml>=6'

echo "Running submodule tests from $SUBMODULE_DIR ..."
cd "$SUBMODULE_DIR"
"$VENV/bin/pytest" tests/ --rootdir=. --override-ini='addopts=' -v

echo ""
echo "Submodule standalone verification PASSED"
