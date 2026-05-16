#!/usr/bin/env python3
from __future__ import annotations

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


def _changed_files() -> list[str]:
    out = subprocess.check_output(["git", "diff", "--name-only", "HEAD~1", "HEAD"], text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def main() -> int:
    changed = _changed_files()
    touched_interface = any(path.startswith(WATCHED_PREFIXES) for path in changed)
    touched_ledger = any(path in LEDGER_FILES for path in changed)
    if touched_interface and not touched_ledger:
        print("Interface-bearing files changed without architecture ledger updates.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
