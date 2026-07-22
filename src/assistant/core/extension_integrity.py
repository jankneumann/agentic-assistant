"""Private-extension integrity manifest — security-hardening (P13).

A persona's private ``extensions/`` directory may carry an optional
``manifest.yaml`` listing a SHA-256 hash per extension file:

.. code-block:: yaml

    version: 1
    hashes:
      gmail.py: "sha256:0f1e2d..."

``PersonaRegistry`` verifies a private extension file against this
manifest BEFORE ``spec.loader.exec_module()`` runs it:

- **manifest absent** → allowed with a WARNING (current personas keep
  working; generate a manifest with ``assistant persona
  hash-extensions``);
- **manifest present, hash matches** → verified, loaded silently;
- **manifest present, hash mismatch OR file not listed OR manifest
  malformed** → the extension is NOT executed and is disabled with an
  ERROR log (P10 failure-isolation: only that extension is lost;
  there is deliberately NO fallback to a public module of the same
  name — a tampered private file must not silently swap
  implementations).

The verification hashes the same bytes it returns for a match check
in one read; the loader still re-reads the file via
``importlib`` (an in-process TOCTOU window we accept — the manifest
defends against at-rest tampering of a private config repo, not
against an attacker who can already race writes inside the running
process).
"""

from __future__ import annotations

import enum
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.yaml"
MANIFEST_VERSION = 1
_HASH_PREFIX = "sha256:"


class ManifestError(ValueError):
    """The integrity manifest exists but cannot be trusted (malformed)."""


class IntegrityVerdict(enum.Enum):
    """Outcome of checking one extension file against the manifest."""

    #: Manifest present, hash matches — execute.
    VERIFIED = "verified"
    #: No manifest in the extensions dir — execute, with a WARNING.
    UNVERIFIED = "unverified"
    #: Manifest present but this file's hash differs — do NOT execute.
    MISMATCH = "mismatch"
    #: Manifest present but does not list this file — do NOT execute.
    UNLISTED = "unlisted"
    #: Manifest exists but is malformed — do NOT execute anything.
    MALFORMED = "malformed"


@dataclass
class IntegrityCheck:
    verdict: IntegrityVerdict
    detail: str = ""

    @property
    def blocked(self) -> bool:
        """True when the extension file must NOT be executed."""
        return self.verdict in (
            IntegrityVerdict.MISMATCH,
            IntegrityVerdict.UNLISTED,
            IntegrityVerdict.MALFORMED,
        )


def file_sha256(path: Path) -> str:
    """Hex SHA-256 of a file's bytes, ``sha256:``-prefixed."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{_HASH_PREFIX}{digest}"


def load_manifest(extensions_dir: Path) -> dict[str, str] | None:
    """Load ``manifest.yaml`` from an extensions dir.

    Returns ``None`` when no manifest exists (the allowed-with-warning
    path) and the ``{filename: "sha256:<hex>"}`` mapping otherwise.
    Raises :class:`ManifestError` when the manifest exists but is not
    a mapping of the expected shape — a malformed manifest blocks
    every private extension in the directory (fail closed: an
    unreadable integrity declaration must not degrade to unverified).
    """
    manifest_path = extensions_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(
            f"{manifest_path}: invalid YAML: {exc}"
        ) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("hashes"), dict):
        raise ManifestError(
            f"{manifest_path}: expected a mapping with a 'hashes:' "
            f"section ({{filename: 'sha256:<hex>'}})."
        )
    hashes: dict[str, str] = {}
    for name, value in raw["hashes"].items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ManifestError(
                f"{manifest_path}: hashes entries must map filename "
                f"strings to 'sha256:<hex>' strings."
            )
        hashes[name] = value
    return hashes


def check_extension_integrity(
    extensions_dir: Path, module_path: Path
) -> IntegrityCheck:
    """Verify one private extension file against the directory manifest.

    Called by ``PersonaRegistry`` before the file is executed. Detail
    strings never include file contents or hash preimages — just the
    filename and the expected/actual digests.
    """
    filename = module_path.name
    try:
        manifest = load_manifest(extensions_dir)
    except ManifestError as exc:
        return IntegrityCheck(IntegrityVerdict.MALFORMED, str(exc))
    if manifest is None:
        return IntegrityCheck(
            IntegrityVerdict.UNVERIFIED,
            f"no {MANIFEST_FILENAME} in {extensions_dir}",
        )
    expected = manifest.get(filename)
    if expected is None:
        return IntegrityCheck(
            IntegrityVerdict.UNLISTED,
            f"{filename} is not listed in {extensions_dir / MANIFEST_FILENAME}",
        )
    actual = file_sha256(module_path)
    if actual != _normalize(expected):
        return IntegrityCheck(
            IntegrityVerdict.MISMATCH,
            f"{filename}: manifest declares {_normalize(expected)}, "
            f"file hashes to {actual}",
        )
    return IntegrityCheck(IntegrityVerdict.VERIFIED)


def generate_manifest(extensions_dir: Path) -> dict[str, str]:
    """Hash every ``*.py`` file in an extensions dir and write the manifest.

    Returns the ``{filename: "sha256:<hex>"}`` mapping that was
    written. An existing manifest is overwritten — regeneration is the
    documented operator flow after an intentional extension edit.
    Raises ``FileNotFoundError`` when the directory does not exist.
    """
    if not extensions_dir.is_dir():
        raise FileNotFoundError(
            f"extensions directory does not exist: {extensions_dir}"
        )
    hashes = {
        path.name: file_sha256(path)
        for path in sorted(extensions_dir.glob("*.py"))
    }
    manifest_path = extensions_dir / MANIFEST_FILENAME
    manifest_path.write_text(
        yaml.safe_dump(
            {"version": MANIFEST_VERSION, "hashes": hashes},
            default_flow_style=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return hashes


def _normalize(declared: str) -> str:
    """Accept bare hex digests as well as ``sha256:``-prefixed ones."""
    return (
        declared
        if declared.startswith(_HASH_PREFIX)
        else f"{_HASH_PREFIX}{declared}"
    )
