#!/usr/bin/env bash
# Verify public tests pass without the private personas/personal submodule
# being populated (spec: test-privacy-boundary / public-test-fixture-root:
# "Public test suite passes without submodule content").
#
# Strategy:
#   1. git submodule deinit -f personas/personal  (leaves mount empty)
#   2. uv run pytest tests/                        (public suite against
#                                                   fixtures only)
#   3. Restore via trap:  git submodule update --init personas/personal
#
# The `trap ... EXIT` guarantees restoration even on pytest failure or
# user interrupt. Replaces the unsafe `mv` approach rejected in Round 1
# (finding I5).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SUBMODULE="personas/personal"

restore() {
    # Best-effort restore; don't mask the original exit code.
    local rc=$?
    echo "[verify-public-tests] restoring submodule $SUBMODULE..." >&2
    git submodule update --init "$SUBMODULE" >/dev/null 2>&1 || \
        echo "[verify-public-tests] WARNING: submodule restore failed; run 'git submodule update --init $SUBMODULE' manually" >&2
    exit "$rc"
}
trap restore EXIT INT TERM

echo "[verify-public-tests] deiniting $SUBMODULE..."
git submodule deinit -f "$SUBMODULE"

echo "[verify-public-tests] running uv run pytest tests/..."
uv run pytest tests/
