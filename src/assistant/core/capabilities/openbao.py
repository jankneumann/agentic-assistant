"""OpenBao credential backend — agent-iam (P25).

Implements the ``CredentialProvider`` protocol (P24 contract 7) against
an OpenBao (Vault-compatible) server as a THIN httpx client — no
``hvac``, no new dependencies (``httpx`` is already pinned for the
model bindings). Per ADR-0006 the OpenBao *server* is a shared
stateful service (already operated for the coding coordinator); only
this client lives here.

Mapping onto the P13 persona-scoped namespace (documented contract):

======================  =============================================
P13 ``.env`` semantics  OpenBao equivalent
======================  =============================================
persona ``.env`` file   KV v2 secrets under ``<mount>/data/<persona>/``
``KEY=VALUE`` entry     secret at ``<mount>/data/<persona>/<REF>``
                        with the credential under data key ``value``
key present wins        HTTP 200 → return ``value`` (even ``""`` —
(even empty = mask)     an empty value still masks the fallback tier)
key absent → process    HTTP 404 → fall through to the layered
env fallback            ``EnvCredentialProvider`` (persona ``.env``
                        first, process env second)
======================  =============================================

Auth is AppRole (``POST /v1/auth/approle/login``): the client token is
cached and proactively re-acquired ``renew_margin_seconds`` before its
lease TTL expires, so no request ever rides an expired token. A lease
duration of ``0`` means a non-expiring token.

Degradation posture (same as memory): an unreachable / misbehaving
OpenBao NEVER breaks persona load or a credential read — the provider
logs one WARNING (re-armed after the next success) and resolves
through the env fallback. A fresh standalone clone with no vault
deployed boots exactly as before.

Persona configuration (``credentials:`` section, validated with the
actionable-error posture)::

    credentials:
      backend: openbao            # or "env" (the default)
      url_env: OPENBAO_ADDR       # env refs — resolved through the
      role_id_env: OPENBAO_ROLE_ID    # persona-scoped env provider,
      secret_id_env: OPENBAO_SECRET_ID  # NEVER raw os.environ
      mount: secret               # optional KV v2 mount (default)

``PersonaRegistry`` consumes :func:`build_credential_provider` at load
time — the ``credential_provider_factory`` injection point P13 left
for exactly this backend; an injected factory still wins unchanged.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from assistant.core.capabilities.credentials import (
    CredentialProvider,
    persona_credential_provider,
)

logger = logging.getLogger(__name__)

#: Default KV v2 mount when the persona omits ``credentials.mount``.
DEFAULT_MOUNT = "secret"

#: Seconds before token TTL expiry at which the client re-authenticates.
DEFAULT_RENEW_MARGIN_SECONDS = 60.0

#: Data key holding the credential inside a KV v2 secret.
SECRET_VALUE_KEY = "value"

_ALLOWED_KEYS = {"backend", "url_env", "role_id_env", "secret_id_env", "mount"}
_VALID_BACKENDS = ("env", "openbao")


class CredentialsConfigError(ValueError):
    """A persona ``credentials:`` section failed validation at load time."""


class OpenBaoError(RuntimeError):
    """A single OpenBao interaction failed (login or read).

    Internal to this module: :meth:`OpenBaoCredentialProvider.
    get_credential` converts it into the WARNING-plus-fallback path;
    it never escapes to callers of the protocol.
    """


@dataclass(frozen=True)
class OpenBaoConfig:
    """Parsed persona ``credentials:`` section for the openbao backend."""

    url_env: str
    role_id_env: str
    secret_id_env: str
    mount: str = DEFAULT_MOUNT


def parse_credentials_config(raw: Any) -> OpenBaoConfig | None:
    """Parse and validate a persona ``credentials:`` section.

    Returns ``None`` for the env backend (including a missing/empty
    section — pre-P25 behavior), an :class:`OpenBaoConfig` for
    ``backend: openbao``. Unknown keys, unknown backends, and missing
    ``*_env`` refs fail with :class:`CredentialsConfigError` naming
    the offender (actionable-error posture, mirrors ``guardrails:``).
    """
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise CredentialsConfigError(
            f"credentials: expected a mapping, got {type(raw).__name__}."
        )
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        raise CredentialsConfigError(
            f"credentials: unknown keys {unknown}. "
            f"Allowed: {sorted(_ALLOWED_KEYS)}."
        )
    backend = raw.get("backend", "env")
    if backend not in _VALID_BACKENDS:
        raise CredentialsConfigError(
            f"credentials: backend {backend!r} is not one of "
            f"{list(_VALID_BACKENDS)}."
        )
    if backend == "env":
        return None
    missing = [
        key
        for key in ("url_env", "role_id_env", "secret_id_env")
        if not isinstance(raw.get(key), str) or not raw.get(key)
    ]
    if missing:
        raise CredentialsConfigError(
            f"credentials: backend 'openbao' requires non-empty {missing} "
            f"(names of the env refs holding the OpenBao address and "
            f"AppRole credentials)."
        )
    mount = raw.get("mount", DEFAULT_MOUNT)
    if not isinstance(mount, str) or not mount:
        raise CredentialsConfigError(
            "credentials: mount must be a non-empty KV v2 mount name."
        )
    return OpenBaoConfig(
        url_env=raw["url_env"],
        role_id_env=raw["role_id_env"],
        secret_id_env=raw["secret_id_env"],
        mount=mount,
    )


class OpenBaoCredentialProvider:
    """KV v2 reads with AppRole auth, layered over an env fallback.

    Satisfies the ``CredentialProvider`` protocol. See the module
    docstring for the persona-namespace mapping and degradation
    posture. ``http_client`` is injectable (e.g. an
    ``httpx.MockTransport``-backed client) so tests never touch the
    network; ``clock`` is injectable for deterministic TTL tests.
    """

    def __init__(
        self,
        *,
        url: str,
        role_id: str,
        secret_id: str,
        persona: str,
        mount: str = DEFAULT_MOUNT,
        fallback: CredentialProvider | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 5.0,
        renew_margin_seconds: float = DEFAULT_RENEW_MARGIN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        from assistant.core.capabilities.credentials import (
            EnvCredentialProvider,
        )

        self._url = url.rstrip("/")
        self._role_id = role_id
        self._secret_id = secret_id
        self._persona = persona
        self._mount = mount.strip("/")
        self._fallback: CredentialProvider = (
            fallback if fallback is not None else EnvCredentialProvider()
        )
        self._client = http_client
        self._timeout = timeout
        self._renew_margin = renew_margin_seconds
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._degraded_warned = False

    # -- protocol surface ------------------------------------------------

    def get_credential(self, ref: str) -> str:
        if not ref:
            return ""
        try:
            found, value = self._read_secret(ref)
        except OpenBaoError as exc:
            if not self._degraded_warned:
                self._degraded_warned = True
                logger.warning(
                    "OpenBao unreachable or failing for persona %r (%s); "
                    "falling back to the env credential tier. Further "
                    "fallbacks are silent until OpenBao recovers.",
                    self._persona,
                    exc,
                )
            return self._fallback.get_credential(ref)
        if self._degraded_warned:
            self._degraded_warned = False  # re-arm after recovery
        if found:
            # Present wins — even an empty value deliberately masks the
            # fallback tier (P13 namespace semantics).
            return value
        return self._fallback.get_credential(ref)

    # -- internals ---------------------------------------------------------

    def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        url = f"{self._url}{path}"
        try:
            if self._client is not None:
                return self._client.request(method, url, **kwargs)
            with httpx.Client(timeout=self._timeout) as client:
                return client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise OpenBaoError(
                f"{method} {path}: {type(exc).__name__}"
            ) from exc

    def _ensure_token(self) -> str:
        now = self._clock()
        if (
            self._token is not None
            and now < self._token_expires_at - self._renew_margin
        ):
            return self._token
        # (Re-)login proactively BEFORE the lease TTL expires — no
        # request ever rides an expired token.
        response = self._request(
            "POST",
            "/v1/auth/approle/login",
            json={"role_id": self._role_id, "secret_id": self._secret_id},
        )
        if response.status_code != 200:
            raise OpenBaoError(
                f"AppRole login failed with HTTP {response.status_code}"
            )
        try:
            auth = response.json()["auth"]
            token = str(auth["client_token"])
            lease = float(auth.get("lease_duration", 0) or 0)
        except (ValueError, KeyError, TypeError) as exc:
            raise OpenBaoError(
                f"AppRole login returned a malformed body "
                f"({type(exc).__name__})"
            ) from exc
        self._token = token
        self._token_expires_at = math.inf if lease <= 0 else now + lease
        return token

    def _read_secret(self, ref: str) -> tuple[bool, str]:
        """KV v2 read at ``<mount>/data/<persona>/<ref>``.

        Returns ``(True, value)`` when the ref exists in the persona's
        vault namespace, ``(False, "")`` when absent (HTTP 404 — the
        caller falls through to the env tier). Anything else raises
        :class:`OpenBaoError`.
        """
        token = self._ensure_token()
        response = self._request(
            "GET",
            f"/v1/{self._mount}/data/{self._persona}/{ref}",
            headers={"X-Vault-Token": token},
        )
        if response.status_code == 404:
            return (False, "")
        if response.status_code != 200:
            raise OpenBaoError(
                f"KV read of ref {ref!r} failed with HTTP "
                f"{response.status_code}"
            )
        try:
            data = response.json()["data"]["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OpenBaoError(
                f"KV read of ref {ref!r} returned a malformed body "
                f"({type(exc).__name__})"
            ) from exc
        if not isinstance(data, dict) or SECRET_VALUE_KEY not in data:
            logger.warning(
                "OpenBao secret for ref %r (persona %r) has no %r data "
                "key; treating the ref as absent from the vault namespace",
                ref,
                self._persona,
                SECRET_VALUE_KEY,
            )
            return (False, "")
        return (True, str(data[SECRET_VALUE_KEY]))


def build_credential_provider(
    persona_name: str,
    persona_dir: Path,
    config: OpenBaoConfig | None,
    *,
    http_client: httpx.Client | None = None,
) -> CredentialProvider:
    """Build the persona's credential provider for a parsed config.

    ``config is None`` (env backend) returns the P13 persona-scoped
    env provider unchanged. For the openbao backend, the bootstrap
    refs (address + AppRole credentials) resolve through that SAME env
    provider — persona ``.env`` first, process env fallback, never raw
    ``os.environ`` — because the vault cannot store its own bootstrap
    secret. Unresolvable bootstrap refs degrade to the env provider
    with a WARNING (never fatal — same posture as an unreachable
    server).
    """
    env_provider = persona_credential_provider(persona_dir)
    if config is None:
        return env_provider
    url = env_provider.get_credential(config.url_env)
    role_id = env_provider.get_credential(config.role_id_env)
    secret_id = env_provider.get_credential(config.secret_id_env)
    unresolved = [
        ref
        for ref, value in (
            (config.url_env, url),
            (config.role_id_env, role_id),
            (config.secret_id_env, secret_id),
        )
        if not value
    ]
    if unresolved:
        logger.warning(
            "Persona %r declares credentials.backend: openbao but %s "
            "resolved empty; falling back to the env credential tier "
            "(set the refs in the persona .env or process environment).",
            persona_name,
            unresolved,
        )
        return env_provider
    return OpenBaoCredentialProvider(
        url=url,
        role_id=role_id,
        secret_id=secret_id,
        persona=persona_name,
        mount=config.mount,
        fallback=env_provider,
        http_client=http_client,
    )


__all__ = [
    "DEFAULT_MOUNT",
    "DEFAULT_RENEW_MARGIN_SECONDS",
    "SECRET_VALUE_KEY",
    "CredentialsConfigError",
    "OpenBaoConfig",
    "OpenBaoCredentialProvider",
    "OpenBaoError",
    "build_credential_provider",
    "parse_credentials_config",
]
