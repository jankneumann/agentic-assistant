"""CredentialProvider seam — model-provider-routing (P19).

Single lookup seam through which all secret and API-key reads flow
(credential-provider spec, contracted in capability-protocols-v2).
A ``ref`` is an opaque lookup key — today an environment-variable
name; under a vault backend (P25 OpenBao) a vault path/key — never a
secret value itself. Backends swap in via injection without touching
call sites.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class CredentialProvider(Protocol):
    """Backend-agnostic outbound credential lookup.

    Inbound-vs-outbound credential modeling is explicitly P25 scope —
    this seam covers outbound lookup only.
    """

    def get_credential(self, ref: str) -> str: ...


class EnvCredentialProvider:
    """Default env-var backend preserving the exact ``_env()`` semantics.

    Mirrors ``assistant.core.persona._env``: ``get_credential(ref)``
    returns ``os.environ.get(ref, "")``, and an empty or missing ``ref``
    returns ``""`` without error — a fresh standalone clone stays
    bootable with no vault deployed.
    """

    def get_credential(self, ref: str) -> str:
        if not ref:
            return ""
        return os.environ.get(ref, "")
