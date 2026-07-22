#!/usr/bin/env python3
"""Fail when interface-bearing code changes without an architecture-ledger update.

Compares the branch against its **merge base with the base branch**, not
``HEAD~1..HEAD``. Two reasons the naive form does not work:

1. A pull request is usually more than one commit. ``HEAD~1..HEAD`` inspects
   only the tip, so a PR that touches ``src/assistant/harnesses/`` in an
   earlier commit slips through the gate.
2. ``actions/checkout`` defaults to ``fetch-depth: 1``. On that shallow clone
   ``HEAD~1`` is not a valid revision at all and git exits 128, which crashes
   the gate rather than reporting drift. The workflow therefore sets
   ``fetch-depth: 0``; this script still fails loudly (exit 2) if the base is
   unresolvable, so a gate that silently did not run is never mistaken for a
   pass.

Exit codes:
  0  no drift (or nothing relevant changed)
  1  drift: interface-bearing files changed, ledger did not
  2  could not determine a comparison base (environment problem, not drift)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

WATCHED_PREFIXES = (
    "src/assistant/harnesses/",
    "src/assistant/extensions/",
    "src/assistant/core/memory",
    "src/assistant/telemetry/",
)
LEDGER_FILES = {
    "docs/architecture/interface-stability.md",
    "docs/architecture/primitives-and-providers.md",
}


def _git(*args: str) -> str:
    """Run a git command and return stdout. Raises CalledProcessError."""
    return subprocess.check_output(
        ["git", *args], text=True, stderr=subprocess.DEVNULL
    )


def _rev_exists(rev: str) -> bool:
    try:
        _git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


def _resolve_base(explicit: str | None) -> str | None:
    """Pick the revision to diff against, most specific source first."""
    candidates: list[str] = []

    if explicit:
        candidates.append(explicit)

    # GitHub Actions sets GITHUB_BASE_REF only for pull_request events.
    base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if base_ref:
        candidates += [f"origin/{base_ref}", base_ref]
    else:
        # push event (or a local run on the trunk): the previous commit is
        # the change actually being introduced.
        candidates.append("HEAD~1")

    candidates += ["origin/main", "main"]

    for cand in candidates:
        if _rev_exists(cand):
            return cand
    return None


def _changed_files(base: str) -> list[str]:
    """Files changed between the merge base and HEAD."""
    try:
        merge_base = _git("merge-base", base, "HEAD").strip()
    except subprocess.CalledProcessError:
        # Unrelated histories (e.g. a shallow clone not reaching a common
        # ancestor) -- fall back to comparing against the base directly.
        merge_base = base
    out = _git("diff", "--name-only", f"{merge_base}..HEAD")
    return [line.strip() for line in out.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=None,
        help="Revision to compare against (default: auto-detect).",
    )
    args = parser.parse_args()

    base = _resolve_base(args.base)
    if base is None:
        print(
            "ERROR: could not determine a comparison base. On CI ensure "
            "actions/checkout uses fetch-depth: 0; locally pass --base <rev>.",
            file=sys.stderr,
        )
        return 2

    changed = _changed_files(base)
    touched_interface = sorted(
        path for path in changed if path.startswith(WATCHED_PREFIXES)
    )
    touched_ledger = any(path in LEDGER_FILES for path in changed)

    if touched_interface and not touched_ledger:
        print(
            "Interface-bearing files changed without architecture ledger "
            f"updates (compared against {base}):"
        )
        for path in touched_interface:
            print(f"  - {path}")
        print("\nUpdate one of:")
        for path in sorted(LEDGER_FILES):
            print(f"  - {path}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
