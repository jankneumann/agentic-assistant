"""Layer 2 runtime filesystem guard for the privacy boundary.

This pytest plugin patches the canonical I/O entry points for the duration
of a pytest session so that any read of a path under ``personas/<name>/``
(for ``<name>`` in ``FORBIDDEN_PATH_NAMES``) raises
``_PrivacyBoundaryViolation`` unless the path falls under an
``ALLOWED_READ_PREFIXES`` entry.

Patched entry points (per design D1 + Round 2 findings B-N1/B-N2):

- ``pathlib.Path.open``, ``Path.read_text``, ``Path.read_bytes``
- ``builtins.open``
- ``os.open``                         -- canonical syscall choke point
- ``subprocess.Popen.__init__``       -- argv scan for forbidden substrings

A self-probe at ``pytest_configure`` verifies the patches are active
(B-N8); if a future CPython refuses Python-level rebinding of a C-slot
method the session fails loudly rather than silently passing.

Originals are restored at ``pytest_unconfigure``.

Wired in via ``pytest_plugins = ["tests._privacy_guard_plugin"]`` in
``tests/conftest.py``.
"""

from __future__ import annotations

import builtins
import os
import pathlib
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests._privacy_guard_config import (
    ALLOWED_READ_PREFIXES,
    FORBIDDEN_PATH_NAMES,
)


class _PrivacyBoundaryViolation(pytest.UsageError):  # type: ignore[misc]
    """Raised when a Layer 2 patched I/O entry point sees a forbidden read.

    ``pytest.UsageError`` is declared ``@final`` in pytest's type stubs,
    but at runtime it is a plain exception class and subclassing works.
    We accept the mypy suppression here to preserve the
    "subclass-of-UsageError" contract that pytest's own session-fail
    machinery recognizes.
    """


# Resolved at pytest_configure; used to turn absolute paths back into
# repo-root-relative POSIX strings for prefix comparison.
_REPO_ROOT: Path | None = None

# Cached saved originals; populated at pytest_configure.
_ORIGINALS: dict[str, Any] = {}


def _forbidden_needles() -> tuple[str, ...]:
    """Return the POSIX substrings that indicate a forbidden path.

    Computed from ``FORBIDDEN_PATH_NAMES`` so adding a persona name to the
    deny-list auto-updates every check site.
    """
    return tuple(f"personas/{name}/" for name in FORBIDDEN_PATH_NAMES)


def _allowed_prefixes() -> tuple[str, ...]:
    return ALLOWED_READ_PREFIXES


def _normalize(path: Any) -> str:
    """Return a POSIX-shaped path string for comparison.

    - Absolute paths under ``_REPO_ROOT`` are stripped to repo-relative.
    - PathLike and bytes are coerced to ``str``.
    - Unresolvable inputs fall back to ``str(path)``.
    """
    # bytes -> str
    if isinstance(path, (bytes, bytearray)):
        try:
            path = path.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover -- defensive
            path = str(path)
    # PathLike -> str
    if hasattr(path, "__fspath__"):
        try:
            path = os.fspath(path)
        except Exception:  # pragma: no cover -- defensive
            path = str(path)
    if not isinstance(path, str):
        path = str(path)
    posix = path.replace("\\", "/")
    if _REPO_ROOT is not None:
        # If the path resolves (or lexically lives) under repo-root, strip it.
        try:
            resolved = Path(path)
            if not resolved.is_absolute():
                resolved = _REPO_ROOT / resolved
            # Avoid touching the filesystem for .resolve(); use normalization
            # so a nonexistent path still participates in the comparison.
            abs_posix = os.path.normpath(str(resolved)).replace("\\", "/")
            root_posix = os.path.normpath(str(_REPO_ROOT)).replace("\\", "/")
            if abs_posix.startswith(root_posix + "/"):
                posix = abs_posix[len(root_posix) + 1 :]
            elif abs_posix == root_posix:
                posix = ""
        except Exception:  # pragma: no cover -- defensive
            pass
    return posix


def _is_forbidden(path: Any) -> tuple[bool, str, str]:
    """Return ``(is_forbidden, needle, normalized_path)``.

    Two-pass check. First the lexical pass (cheap, covers the common
    case). Then, only if the lexical pass didn't already conclude the
    path is forbidden/allowed unambiguously, a resolve pass (IR-A3)
    catches symlink-based bypasses like
    ``tests/fixtures/sneaky -> ../../personas/personal``.
    """
    normalized = _normalize(path)
    # Lexical allow-list short-circuit. If the lexical path is allow-
    # listed AND a symlink resolution stays within an allow-listed
    # prefix, the read proceeds; if resolution escapes to a forbidden
    # location, we reject.
    for prefix in _allowed_prefixes():
        if normalized.startswith(prefix):
            resolved_posix = _resolve_relative_to_root(path)
            if resolved_posix is None:
                return False, "", normalized
            # If the resolved path is ALSO under an allow-listed prefix,
            # it's fine even if the normalized form contains a
            # sub-string match for a forbidden name (legitimate case:
            # tests/fixtures/personas/personal/*).
            for allowed in _allowed_prefixes():
                if resolved_posix.startswith(allowed):
                    return False, "", normalized
            # Resolved out of allow-list -- check for forbidden needles.
            for needle in _forbidden_needles():
                if needle in resolved_posix:
                    return True, needle, resolved_posix
            return False, "", normalized
    # Lexical forbidden check.
    for needle in _forbidden_needles():
        if needle in normalized:
            return True, needle, normalized
    # Final resolve pass: catches cases where the lexical path didn't
    # hit any needle but a symlink redirects to forbidden territory.
    resolved_posix = _resolve_relative_to_root(path)
    if resolved_posix is not None and resolved_posix != normalized:
        for allowed in _allowed_prefixes():
            if resolved_posix.startswith(allowed):
                return False, "", normalized
        for needle in _forbidden_needles():
            if needle in resolved_posix:
                return True, needle, resolved_posix
    return False, "", normalized


def _resolve_relative_to_root(path: Any) -> str | None:
    """Best-effort resolve to a repo-relative POSIX string; None on failure."""
    try:
        if isinstance(path, (int, bytes, bytearray)):
            return None
        p = Path(path) if not isinstance(path, Path) else path
        resolved = p.resolve(strict=False)
    except (OSError, ValueError, RuntimeError):
        return None
    posix = str(resolved).replace("\\", "/")
    if _REPO_ROOT is not None:
        root_posix = str(_REPO_ROOT).replace("\\", "/")
        if posix.startswith(root_posix + "/"):
            posix = posix[len(root_posix) + 1 :]
        elif posix == root_posix:
            posix = ""
    return posix


def _violate(path: Any, needle: str, normalized: str) -> None:
    """Raise ``_PrivacyBoundaryViolation`` identifying the matched needle.

    Deliberately does NOT echo file contents (spec scenario "Guard failure
    messages do not echo private payloads").
    """
    raise _PrivacyBoundaryViolation(
        "Privacy-boundary violation: runtime read of "
        f"{normalized!r} matched forbidden path prefix {needle!r}. "
        "Public tests must use tests/fixtures/ instead. "
        "See docs/gotchas.md G6."
    )


# ── Patched entry points ────────────────────────────────────────────────


def _patched_path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
    forbidden, needle, normalized = _is_forbidden(self)
    if forbidden:
        _violate(self, needle, normalized)
    return _ORIGINALS["path_open"](self, *args, **kwargs)


def _patched_path_read_text(self: Path, *args: Any, **kwargs: Any) -> Any:
    forbidden, needle, normalized = _is_forbidden(self)
    if forbidden:
        _violate(self, needle, normalized)
    return _ORIGINALS["path_read_text"](self, *args, **kwargs)


def _patched_path_read_bytes(self: Path, *args: Any, **kwargs: Any) -> Any:
    forbidden, needle, normalized = _is_forbidden(self)
    if forbidden:
        _violate(self, needle, normalized)
    return _ORIGINALS["path_read_bytes"](self, *args, **kwargs)


def _patched_builtins_open(file: Any, *args: Any, **kwargs: Any) -> Any:
    forbidden, needle, normalized = _is_forbidden(file)
    if forbidden:
        _violate(file, needle, normalized)
    return _ORIGINALS["builtins_open"](file, *args, **kwargs)


def _patched_os_open(path: Any, *args: Any, **kwargs: Any) -> Any:
    forbidden, needle, normalized = _is_forbidden(path)
    if forbidden:
        _violate(path, needle, normalized)
    return _ORIGINALS["os_open"](path, *args, **kwargs)


def _decode_candidate(element: Any) -> str:
    if isinstance(element, (bytes, bytearray)):
        try:
            return element.decode("utf-8", errors="replace")
        except Exception:
            return str(element)
    return str(element)


def _subprocess_candidates(args: tuple, kwargs: dict) -> list[str]:
    """Harvest every string the subprocess could plausibly resolve to a path.

    Covers the positional ``args`` argv (list or string), and the
    ``executable=``, ``cwd=`` kwargs (IR-A4). ``env=`` is intentionally
    excluded -- its values are typically system paths, and scanning them
    generates too many false positives vs threat-model value.
    """
    argv: Any = args[0] if args else kwargs.get("args")
    candidates: list[str] = []
    if isinstance(argv, (list, tuple)):
        candidates.extend(_decode_candidate(e) for e in argv)
    elif isinstance(argv, (str, bytes, bytearray)):
        candidates.append(_decode_candidate(argv))
    for kw in ("executable", "cwd"):
        v = kwargs.get(kw)
        if v is not None:
            candidates.append(_decode_candidate(v))
    return candidates


def _argv_element_is_forbidden(posix: str) -> tuple[str, str] | None:
    """Return ``(matched_name, evidence)`` if this argv element references a
    forbidden persona path, else None.

    Uses component-aware matching (IR-A2): ``personas/<name>`` followed by
    end-of-string OR a non-word boundary counts as a hit. This catches
    ``git -C personas/personal log`` (bare-dir), ``cat personas/personal/x``
    (child-path), and ``--config=personas/personal`` (embedded) alike,
    while ignoring ``personas/personality`` (different name).

    Allow-list (IR-A5): any occurrence of an allow-listed prefix elsewhere
    in the element does NOT short-circuit -- we only skip if the
    forbidden hit is LEXICALLY CONTAINED WITHIN an allow-listed path
    (e.g. ``tests/fixtures/personas/_template/`` via the template
    allow-list). This closes the
    ``--config=tests/fixtures/x:personas/personal/y`` bypass class.
    """
    for name in FORBIDDEN_PATH_NAMES:
        pattern = re.compile(
            rf"(?:^|[^A-Za-z0-9_]|/){re.escape('personas/' + name)}(?=$|[^A-Za-z0-9_])"
        )
        m = pattern.search(posix)
        if not m:
            continue
        hit_start = m.start() + (1 if m.group().startswith(("/",)) or not m.group().startswith("personas") else 0)
        # A hit is allow-listed ONLY if the substring from hit_start back
        # to the start of an allow-listed prefix is purely path-component
        # characters. Cheap approximation: does any allow-listed prefix
        # occur as a prefix of posix AND extend through the hit position?
        allowed = False
        for prefix in ALLOWED_READ_PREFIXES:
            prefix_posix = prefix.replace("\\", "/")
            if posix.startswith(prefix_posix) and hit_start >= len(prefix_posix):
                allowed = True
                break
        if allowed:
            continue
        return name, m.group()
    return None


def _patched_popen_init(self: subprocess.Popen, *args: Any, **kwargs: Any) -> Any:
    candidates = _subprocess_candidates(args, kwargs)
    for element in candidates:
        posix_element = element.replace("\\", "/")
        hit = _argv_element_is_forbidden(posix_element)
        if hit is not None:
            matched_name, evidence = hit
            raise _PrivacyBoundaryViolation(
                "Privacy-boundary violation: subprocess argv or kwargs "
                f"referenced persona {matched_name!r} "
                f"(matched pattern {evidence!r}). Public tests must use "
                "tests/fixtures/ instead. See docs/gotchas.md G6."
            )
    return _ORIGINALS["popen_init"](self, *args, **kwargs)


# ── Install / uninstall / self-probe ────────────────────────────────────


def _install_patches() -> None:
    # Idempotent: a second pytest_configure (xdist bootstrap, plugin
    # re-registration, or a self-test that triggers pytest_configure
    # manually) MUST NOT overwrite _ORIGINALS with the already-patched
    # callables -- that would turn every subsequent I/O call into
    # infinite recursion (IR-A1).
    if _ORIGINALS:
        return
    _ORIGINALS["path_open"] = pathlib.Path.open
    _ORIGINALS["path_read_text"] = pathlib.Path.read_text
    _ORIGINALS["path_read_bytes"] = pathlib.Path.read_bytes
    _ORIGINALS["builtins_open"] = builtins.open
    _ORIGINALS["os_open"] = os.open
    _ORIGINALS["popen_init"] = subprocess.Popen.__init__

    pathlib.Path.open = _patched_path_open  # type: ignore[method-assign]
    pathlib.Path.read_text = _patched_path_read_text  # type: ignore[method-assign]
    pathlib.Path.read_bytes = _patched_path_read_bytes  # type: ignore[method-assign]
    builtins.open = _patched_builtins_open
    os.open = _patched_os_open
    subprocess.Popen.__init__ = _patched_popen_init  # type: ignore[method-assign]


def _uninstall_patches() -> None:
    if not _ORIGINALS:
        return
    pathlib.Path.open = _ORIGINALS["path_open"]  # type: ignore[method-assign]
    pathlib.Path.read_text = _ORIGINALS["path_read_text"]  # type: ignore[method-assign]
    pathlib.Path.read_bytes = _ORIGINALS["path_read_bytes"]  # type: ignore[method-assign]
    builtins.open = _ORIGINALS["builtins_open"]
    os.open = _ORIGINALS["os_open"]
    subprocess.Popen.__init__ = _ORIGINALS["popen_init"]  # type: ignore[method-assign]
    _ORIGINALS.clear()


def _self_probe() -> None:
    """Attempt a canary forbidden read; assert guard raises.

    Uses ``Path.read_text`` on a canonically-forbidden nonexistent path.
    If patches silently failed to install, the read would raise
    ``FileNotFoundError`` (or succeed if the path exists) rather than
    ``_PrivacyBoundaryViolation``. We detect either non-violation outcome
    and fail the session.
    """
    # Build canary dynamically so this module's own source does NOT embed
    # a forbidden literal.
    canary_name = FORBIDDEN_PATH_NAMES[0] if FORBIDDEN_PATH_NAMES else "personal"
    canary = Path("personas") / canary_name / "privacy-guard-canary-nonexistent"
    probe_outcome: str
    try:
        canary.read_text()
    except _PrivacyBoundaryViolation:
        return  # Guard is live -- correct outcome.
    except (FileNotFoundError, OSError, PermissionError) as exc:
        # Patches didn't fire but the real I/O path did -- guard is off.
        probe_outcome = f"raised {type(exc).__name__} instead of _PrivacyBoundaryViolation"
    except Exception as exc:  # narrower than BaseException (IR-A7)
        probe_outcome = f"raised unexpected {type(exc).__name__}: {exc!r}"
    else:
        probe_outcome = "no exception -- guard patches are inert"
    raise pytest.UsageError(
        f"Layer 2 privacy guard failed to install (canary read {probe_outcome})"
    )


# ── pytest hooks ────────────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    global _REPO_ROOT
    # rootpath is pytest's resolved rootdir; the worktree root for us.
    try:
        _REPO_ROOT = Path(str(config.rootpath)).resolve()
    except Exception:  # pragma: no cover -- fallback if rootpath absent
        _REPO_ROOT = Path.cwd().resolve()
    _install_patches()
    _self_probe()


def pytest_unconfigure(config: pytest.Config) -> None:
    _uninstall_patches()
