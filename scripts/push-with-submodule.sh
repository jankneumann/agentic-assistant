#!/usr/bin/env bash
# push-with-submodule.sh — atomic wrapper for the two-commit submodule
# push topology (task 5.0, design D7).
#
# Usage:
#   scripts/push-with-submodule.sh --submodule-only
#   scripts/push-with-submodule.sh --parent-only
#
# Modes are intentionally separate invocations:
#   --submodule-only   cd into personas/personal, git push, print pushed SHA.
#   --parent-only      verify parent branch rebased onto origin/main,
#                      git add personas/personal gitlink, commit w/ SHA
#                      in message, push parent branch.
#
# Idempotency: re-invoking either mode with nothing to do is a no-op
# exit 0. Safe to re-run after transient network failures.
#
# Exit-code contract:
#   0   success (including "nothing to push")
#   1   generic failure (git error, invalid state)
#   2   usage error (bad or missing mode flag)
#  47   parent push failed AFTER submodule push had succeeded —
#       distinctive code that the 5.3-alt dispatcher recognizes and
#       routes into the quarantine/operator-handoff path. The diagnostic
#       names the dangling submodule SHA and a suggested recovery.

set -euo pipefail

MODE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SUBMODULE_DIR="$REPO_ROOT/personas/personal"

usage() {
    echo "Usage: $0 --submodule-only | --parent-only" >&2
    exit 2
}

case "$MODE" in
    --submodule-only)
        if [[ ! -d "$SUBMODULE_DIR" ]]; then
            echo "ERROR: submodule dir not found at $SUBMODULE_DIR" >&2
            exit 1
        fi
        cd "$SUBMODULE_DIR"

        # Idempotency: nothing dirty in working tree AND nothing unpushed
        # relative to upstream => no-op.
        dirty="$(git status --porcelain)"
        # `git log @{u}..` fails if no upstream is set; treat that as
        # "needs push" (conservative — better to attempt and fail loudly
        # than to silently no-op).
        if unpushed="$(git log '@{u}..' --oneline 2>/dev/null)"; then
            :
        else
            unpushed="needs-push-unknown-upstream"
        fi

        if [[ -z "$dirty" && -z "$unpushed" ]]; then
            echo "Submodule: nothing to push (working tree clean, upstream in sync)"
            SHA="$(git rev-parse HEAD)"
            echo "$SHA"
            exit 0
        fi

        if [[ -n "$dirty" ]]; then
            echo "ERROR: submodule working tree is dirty; commit before pushing" >&2
            echo "$dirty" >&2
            exit 1
        fi

        git push
        SHA="$(git rev-parse HEAD)"
        echo "Submodule pushed: $SHA"
        echo "$SHA"
        ;;

    --parent-only)
        cd "$REPO_ROOT"

        # Verify parent branch is rebased onto origin/main before bumping
        # the submodule gitlink.
        git fetch origin main
        if ! git merge-base --is-ancestor origin/main HEAD; then
            echo "ERROR: parent branch is not rebased onto origin/main" >&2
            echo "Run: git rebase origin/main" >&2
            exit 1
        fi

        # Stage the submodule gitlink update (if any).
        git add personas/personal

        if git diff --cached --quiet personas/personal; then
            echo "Parent: no submodule SHA change staged (gitlink already current)"
        else
            SUB_SHA="$(git -C "$SUBMODULE_DIR" rev-parse HEAD)"
            git commit -m "chore(submodule): bump personas/personal to $SUB_SHA"
        fi

        # Attempt parent push. If this fails after we have already pushed
        # the submodule (via an earlier --submodule-only invocation),
        # emit the dangling-SHA diagnostic and exit 47.
        if ! git push 2>&1; then
            DANGLING_SHA="$(git -C "$SUBMODULE_DIR" rev-parse HEAD)"
            echo "" >&2
            echo "ERROR: parent push FAILED after submodule push had succeeded" >&2
            echo "Dangling submodule SHA: $DANGLING_SHA" >&2
            echo "" >&2
            echo "Recovery options:" >&2
            echo "  1. Rebase the parent branch and re-run --parent-only:" >&2
            echo "       git fetch origin main && git rebase origin/main" >&2
            echo "       bash scripts/push-with-submodule.sh --parent-only" >&2
            echo "  2. If the submodule SHA must be retracted, delete the" >&2
            echo "     remote ref from the private submodule host:" >&2
            echo "       git -C personas/personal push -d origin <branch-with-dangling-sha>" >&2
            echo "  3. Or open an operator ticket with the SHA above." >&2
            exit 47
        fi

        echo "Parent pushed."
        ;;

    *)
        usage
        ;;
esac
