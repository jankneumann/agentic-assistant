"""Single source of truth for the two-layer privacy-boundary guard.

Layer 1 (collection-time substring scan in ``tests/conftest.py``) and Layer 2
(runtime FS-I/O patching in ``tests/_privacy_guard_plugin.py``) both read
from the constants defined here. Adding a new persona name (e.g. when P6
populates ``personas/work/``) is a one-line change here, not two.

This module is intentionally NOT a conftest and NOT a test module. It is
imported by the guard infrastructure; pytest never collects it.

See ``openspec/changes/test-privacy-boundary/design.md`` D2, D8, D9 for the
rationale behind each constant.
"""

from __future__ import annotations

# Persona names that public tests are forbidden from reading from at
# ``personas/<name>/``. Currently covers ``personal`` (populated submodule)
# and ``work`` (future P6 populated submodule) — future-proofs the guard
# so adding ``work`` later is one line.
FORBIDDEN_PATH_NAMES: tuple[str, ...] = ("personal", "work")

# Read-path prefixes that ARE allowed to resolve under ``personas/<name>/``
# (or elsewhere). ``tests/fixtures/`` is the public-test persona root after
# repoint (task 2.2). ``personas/_template/`` is public-by-design template
# content that new personas scaffold from.
ALLOWED_READ_PREFIXES: tuple[str, ...] = (
    "tests/fixtures/",
    "personas/_template/",
)

# Files that Layer 1 (collection-time substring scan) SHALL NOT inspect.
# These files legitimately contain forbidden substrings as *data* (the
# guard implementation, deny-list config, and hygiene tests that scan
# workflow / pyproject YAML for leakage) — they do not constitute a
# privacy-boundary violation. The hygiene tests additionally construct
# their forbidden needles dynamically from FORBIDDEN_PATH_NAMES so a
# naive contributor can't accidentally reintroduce a literal substring
# (belt-and-suspenders per D9).
#
# Paths are repo-root-relative POSIX strings; the Layer 1 hook compares
# via ``pathlib.PurePath.as_posix()``.
SCAN_EXCLUDED_FILES: tuple[str, ...] = (
    "tests/_privacy_guard_config.py",
    "tests/_privacy_guard_plugin.py",
    "tests/test_ci_workflow_hygiene.py",
    "tests/test_workspace_hygiene.py",
)

# Directories that Layer 1 SHALL NOT inspect. ``tests/fixtures/`` is the
# public-test fixture tree (Layer 1 scans only Python test/conftest files,
# but fixtures can contain YAML/Markdown with forbidden-looking strings
# that are in fact fixture content — defensive exclusion). ``tests/_helpers/``
# is the documented location for non-test Python helpers per D8.
#
# Paths are repo-root-relative POSIX strings with trailing slash.
SCAN_EXCLUDED_DIRS: tuple[str, ...] = (
    "tests/fixtures/",
    "tests/_helpers/",
)
