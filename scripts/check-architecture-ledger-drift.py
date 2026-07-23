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

Escape hatch: a change under a watched path that is genuinely NOT an
interface change (a bugfix, a comment, an internal refactor) can bypass the
gate by putting a marker in any commit message on the branch:

    [skip-ledger: <reason>]

This is deliberately a declaration in the git history, not a silent
whitespace edit to the ledger. It is visible in review and auditable after
the fact -- someone consciously asserting "not an interface change" is far
better signal than a token ledger touch made only to satisfy the gate.

Exit codes:
  0  no drift, nothing relevant changed, or an explicit skip declaration
  1  drift: interface-bearing files changed, ledger did not
  2  could not determine a comparison base (environment problem, not drift)
"""

from __future__ import annotations

import argparse
import os
import re
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

# Case-insensitive; reason is required and must be non-empty so the marker
# cannot be used as a contentless bypass.
_SKIP_MARKER = re.compile(r"\[skip-ledger:\s*(?P<reason>[^\]]*\S)\s*\]", re.I)


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


def _merge_base(base: str) -> str:
    """Merge base of ``base`` and HEAD, or ``base`` if none is reachable."""
    try:
        return _git("merge-base", base, "HEAD").strip()
    except subprocess.CalledProcessError:
        # Unrelated histories (e.g. a shallow clone not reaching a common
        # ancestor) -- fall back to comparing against the base directly.
        return base


def _changed_files(merge_base: str) -> list[str]:
    """Files changed between the merge base and HEAD."""
    out = _git("diff", "--name-only", f"{merge_base}..HEAD")
    return [line.strip() for line in out.splitlines() if line.strip()]


def _skip_reason(merge_base: str) -> str | None:
    """Return the reason if any commit in the range declares a skip marker."""
    try:
        log = _git("log", "--format=%B", f"{merge_base}..HEAD")
    except subprocess.CalledProcessError:
        return None
    match = _SKIP_MARKER.search(log)
    return match.group("reason").strip() if match else None


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

    merge_base = _merge_base(base)
    changed = _changed_files(merge_base)
    touched_interface = sorted(
        path for path in changed if path.startswith(WATCHED_PREFIXES)
    )
    touched_ledger = any(path in LEDGER_FILES for path in changed)

    if touched_interface and not touched_ledger:
        skip = _skip_reason(merge_base)
        if skip is not None:
            # Declared non-interface change -- allow, but record it so the
            # bypass is visible in the CI log, not silent.
            print(
                "Architecture ledger drift gate bypassed via "
                f"[skip-ledger: {skip}]. Watched paths changed without a "
                "ledger update:"
            )
            for path in touched_interface:
                print(f"  - {path}")
            return 0

        print(
            "Interface-bearing files changed without architecture ledger "
            f"updates (compared against {base}):"
        )
        for path in touched_interface:
            print(f"  - {path}")
        print("\nUpdate one of:")
        for path in sorted(LEDGER_FILES):
            print(f"  - {path}")
        print(
            "\nOr, if this is genuinely not an interface change, declare it "
            "in a commit message: [skip-ledger: <reason>]"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
