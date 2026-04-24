"""Auth-header resolution for persona-configured HTTP tool sources.

Accepts the structured form ``{type, env, header?}`` (the canonical
P3 shape) and the legacy flat-string shortcut (treated as a bearer
token value) for robustness — see design decision D11.
"""

from __future__ import annotations

import os
from typing import Literal, NotRequired, TypedDict


class AuthHeaderConfig(TypedDict):
    """Structured auth header config as stored in a persona's tool_sources."""

    type: Literal["bearer", "api-key"]
    env: str
    header: NotRequired[str]


AuthHeaderInput = AuthHeaderConfig | str | None


def resolve_auth_header(config: AuthHeaderInput) -> dict[str, str]:
    """Return HTTP headers to attach to requests to a source.

    - ``None`` → empty dict (no auth).
    - ``str`` (legacy flat form) → ``{"Authorization": f"Bearer {value}"}``.
      The string is treated as the *token value*, not an env var name.
    - ``AuthHeaderConfig`` dict → reads the env var named by ``env`` and
      builds a ``{"Authorization": "Bearer ..."}`` or
      ``{"X-API-Key": ...}`` (or custom header) dict.

    Raises:
        KeyError: if ``config['env']`` names an env var that is not set.
            The exception message includes the variable name so callers
            can surface it.
        ValueError: if the structured ``type`` is not ``"bearer"`` or
            ``"api-key"``.
    """
    if config is None:
        return {}
    if isinstance(config, str):
        return {"Authorization": f"Bearer {config}"}

    env_name = config["env"]
    if env_name not in os.environ:
        raise KeyError(env_name)
    value = os.environ[env_name]

    auth_type = config["type"]
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {value}"}
    if auth_type == "api-key":
        header_name = config.get("header", "X-API-Key")
        return {header_name: value}

    raise ValueError(f"unsupported auth_header type: {auth_type!r}")
