"""Auth-header resolution for persona-configured HTTP tool sources.

Accepts the structured form ``{type, env, header?}`` (the canonical
P3 shape) and the legacy flat-string shortcut (treated as a bearer
token value) for robustness — see design decision D11.

P13 security-hardening: the credential named by ``env`` resolves
through the ``CredentialProvider`` seam (persona-scoped ``.env``
first, process environment fallback) rather than a direct
``os.environ`` read. Callers pass the persona's provider; omitting it
falls back to the process-env default so standalone use keeps
working.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from assistant.core.capabilities.credentials import (
    CredentialProvider,
    EnvCredentialProvider,
)


class AuthHeaderConfig(TypedDict):
    """Structured auth header config as stored in a persona's tool_sources."""

    type: Literal["bearer", "api-key"]
    env: str
    header: NotRequired[str]


AuthHeaderInput = AuthHeaderConfig | str | None


def resolve_auth_header(
    config: AuthHeaderInput,
    credentials: CredentialProvider | None = None,
) -> dict[str, str]:
    """Return HTTP headers to attach to requests to a source.

    - ``None`` → empty dict (no auth).
    - ``str`` (legacy flat form) → ``{"Authorization": f"Bearer {value}"}``.
      The string is treated as the *token value*, not a credential ref.
    - ``AuthHeaderConfig`` dict → resolves the ref named by ``env``
      through ``credentials`` (default: process environment) and
      builds a ``{"Authorization": "Bearer ..."}`` or
      ``{"X-API-Key": ...}`` (or custom header) dict.

    Raises:
        KeyError: if ``config['env']`` names a ref that resolves to an
            empty value (unset variable, or absent from the persona
            ``.env`` and the process environment). The exception
            message includes the ref name so callers can surface it.
        ValueError: if the structured ``type`` is not ``"bearer"`` or
            ``"api-key"``.
    """
    if config is None:
        return {}
    if isinstance(config, str):
        return {"Authorization": f"Bearer {config}"}

    provider = credentials or EnvCredentialProvider()
    env_name = config["env"]
    value = provider.get_credential(env_name)
    if not value:
        raise KeyError(env_name)

    auth_type = config["type"]
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {value}"}
    if auth_type == "api-key":
        header_name = config.get("header", "X-API-Key")
        return {header_name: value}

    raise ValueError(f"unsupported auth_header type: {auth_type!r}")
