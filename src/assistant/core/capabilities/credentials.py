"""CredentialProvider seam — model-provider-routing (P19) + security-hardening (P13).

Single lookup seam through which all secret and API-key reads flow
(credential-provider spec, contracted in capability-protocols-v2).
A ``ref`` is an opaque lookup key — today an environment-variable
name; under a vault backend (P25 OpenBao) a vault path/key — never a
secret value itself. Backends swap in via injection without touching
call sites.

P13 adds per-persona credential scoping: each persona may ship a
git-ignored ``.env`` file in its persona directory whose values are
loaded into a persona-SCOPED namespace (never into the process
``os.environ`` — cross-persona isolation is the point). Resolution
order: persona ``.env`` values first, process environment fallback.
A key *present* in the persona ``.env`` always wins, even when its
value is empty — an empty value deliberately masks the process
variable for that persona.

The persona-scoped namespace is designed to map 1:1 onto per-persona
OpenBao mounts when P25 lands: the scoped mapping becomes the
persona's vault mount (``secret/<persona>/<ref>``), and the process
environment remains the standalone/dev fallback tier — same
precedence, different backend, zero call-site changes.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Filename of the optional per-persona credential file, resolved
#: relative to the persona directory. Git-ignored via the persona
#: template's ``.gitignore`` (``.env`` / ``.env.*``).
PERSONA_ENV_FILENAME = ".env"

#: ``KEY=VALUE`` line with optional ``export`` prefix. Keys follow
#: POSIX environment-variable naming; anything else is rejected with
#: a warning naming the line number (never the line content — the
#: content may hold a secret).
_ENV_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


@runtime_checkable
class CredentialProvider(Protocol):
    """Backend-agnostic outbound credential lookup.

    Inbound-vs-outbound credential modeling is explicitly P25 scope —
    this seam covers outbound lookup only.
    """

    def get_credential(self, ref: str) -> str: ...


class EnvCredentialProvider:
    """Default env-var backend preserving the exact ``_env()`` semantics,
    optionally layered over a persona-scoped namespace.

    Without ``scoped`` values this mirrors ``assistant.core.persona._env``:
    ``get_credential(ref)`` returns ``os.environ.get(ref, "")``, and an
    empty or missing ``ref`` returns ``""`` without error — a fresh
    standalone clone stays bootable with no vault deployed.

    With ``scoped`` values (typically loaded from a persona ``.env``
    file via :func:`persona_credential_provider`), a ref present in the
    scoped namespace resolves there FIRST; only refs absent from the
    namespace fall back to the process environment. The scoped mapping
    is copied at construction and never written back to ``os.environ``.
    """

    def __init__(self, scoped: Mapping[str, str] | None = None) -> None:
        self._scoped: dict[str, str] = dict(scoped or {})

    def get_credential(self, ref: str) -> str:
        if not ref:
            return ""
        if ref in self._scoped:
            return self._scoped[ref]
        return os.environ.get(ref, "")


def parse_env_file(text: str, *, source: str = "<env>") -> dict[str, str]:
    """Parse ``.env`` content into a mapping — minimal, dependency-free.

    Supported syntax: blank lines, ``#`` comment lines, ``KEY=VALUE``
    with an optional ``export`` prefix. Values are stripped of
    surrounding whitespace and one pair of matching single or double
    quotes. No interpolation, no multi-line values. Malformed lines
    are skipped with a WARNING that names the line number only —
    never the line content, which may hold a secret.
    """
    values: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE_RE.match(stripped)
        if not match:
            logger.warning(
                "%s: skipping malformed line %d (expected KEY=VALUE)",
                source,
                lineno,
            )
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(path: Path) -> dict[str, str]:
    """Load a ``.env`` file into a mapping; missing file returns ``{}``.

    Never mutates ``os.environ`` — the returned mapping is the
    persona-scoped namespace consumed by :class:`EnvCredentialProvider`.
    """
    if not path.is_file():
        return {}
    return parse_env_file(
        path.read_text(encoding="utf-8"), source=str(path)
    )


def persona_credential_provider(persona_dir: Path) -> EnvCredentialProvider:
    """Build the persona-scoped provider for one persona directory.

    Loads ``<persona_dir>/.env`` (when present) into the scoped
    namespace. Precedence: persona ``.env`` first, process environment
    fallback. Two personas loading different ``.env`` files resolve
    the same ref to different values without either leaking into the
    process environment or into the other persona's namespace.
    """
    return EnvCredentialProvider(
        scoped=load_env_file(Path(persona_dir) / PERSONA_ENV_FILENAME)
    )
