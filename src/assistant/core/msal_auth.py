"""MSAL strategy abstraction for delegated and unattended Microsoft auth.

Two pluggable strategies (D1) drive the GraphClient bearer-token plumbing:

* ``InteractiveDelegatedStrategy`` — ``msal.PublicClientApplication`` with
  ``acquire_token_interactive`` first run, ``acquire_token_silent`` thereafter,
  optional device-code fallback under ``MSAL_FALLBACK_DEVICE_CODE=1``.
* ``ClientCredentialsStrategy`` — ``msal.ConfidentialClientApplication``
  ``acquire_token_for_client`` for unattended scenarios.

Token cache discipline (D2 / D21 / D22):

* Cache lives at ``personas/<name>/.cache/msal_token_cache.json``.
* Directory mode 0o700, file mode 0o600 — created atomically via
  ``os.open(O_CREAT|O_WRONLY|O_EXCL, 0o600)`` so no umask race window.
* Atomic write via per-process tmp file + ``os.rename``; concurrent
  refreshes use random 8-char suffixes; stale tmp files >5 min are
  swept before rewriting.
* Permission audit (``stat & 0o077 == 0``) AND gitignore-presence check
  fail fast before any write so a tokens-readable-by-other or
  tokens-tracked-in-git outcome is impossible.

Concurrency (D20): every synchronous MSAL call is wrapped in
``asyncio.to_thread`` so concurrent extensions don't serialize behind
one MSAL operation.

Spec: openspec/changes/ms-graph-extension/specs/msal-auth/spec.md
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from assistant.core.resilience import _sanitize_and_truncate

if TYPE_CHECKING:
    from assistant.core.persona import PersonaConfig

logger = logging.getLogger("assistant.msal_auth")

# Sentinel pattern used when the persona's gitignore is checked. We accept
# any of these as evidence that ``.cache/`` is excluded from version
# control. ``personas/<name>/.cache/`` matches a top-level repo gitignore
# entry that names the cache by absolute path inside the persona repo.
_CACHE_GITIGNORE_PATTERNS: tuple[str, ...] = (
    ".cache/",
    ".cache",
    "*.cache/",
    "**/.cache/",
)

# Stale tmp file sweep threshold (msal-auth spec scenario "Concurrent
# refresh handles tmp-file collision via random suffix").
_STALE_TMP_SECONDS: int = 5 * 60


class MSALAuthenticationError(Exception):
    """MSAL strategy or cache failure.

    The exception's ``__str__`` runs the wrapped message through
    ``_sanitize_and_truncate`` (P9 sanitizer) so logged errors never
    contain access tokens, refresh tokens, or other secret-shaped
    substrings — see msal-auth spec scenario "Error string is
    sanitized".
    """

    def __init__(self, message: str) -> None:
        # Sanitize at construction so any subsequent ``str(exc)`` or
        # ``logger.exception`` call sees the redacted form.
        self._sanitized_message = _sanitize_and_truncate(message)
        super().__init__(self._sanitized_message)

    def __str__(self) -> str:  # pragma: no cover - simple delegation
        return self._sanitized_message


@runtime_checkable
class MSALStrategy(Protocol):
    """Single-method async Protocol for MSAL token acquisition (D1).

    Concrete implementations satisfy the Protocol via duck typing —
    ``isinstance(obj, MSALStrategy)`` is ``True`` for any object exposing
    a coroutine-returning ``acquire_token`` method.
    """

    async def acquire_token(
        self,
        scopes: list[str],
        *,
        force_refresh: bool = False,
    ) -> str:
        """Return a bearer access token suitable for ``Authorization: Bearer``.

        ``force_refresh=True`` bypasses any silent / cached path and
        forces a fresh token acquisition (used by GraphClient on 401
        ``invalid_token`` per D9).
        """
        ...


# ---------------------------------------------------------------------------
# Token cache helpers — D2, D21, D22.
# ---------------------------------------------------------------------------


def _gitignore_excludes_cache(cache_dir: Path, persona_root: Path) -> bool:
    """Return True if ``.cache/`` is excluded by the persona repo's gitignore chain.

    Walks every ``.gitignore`` from the cache directory up to (and
    including) the persona repo root. A line matching any
    ``_CACHE_GITIGNORE_PATTERNS`` entry — case-sensitive, fnmatch-glob
    semantics — is sufficient. Comments (``#``) and blank lines are
    skipped; trailing whitespace is trimmed.
    """
    cache_dir = cache_dir.resolve()
    persona_root = persona_root.resolve()
    if not cache_dir.is_relative_to(persona_root):
        # Defensive: if the cache somehow escaped the persona root,
        # refuse to vouch for any external gitignore.
        return False

    # Walk from cache_dir up to persona_root inclusive.
    cur = cache_dir if cache_dir.is_dir() else cache_dir.parent
    while True:
        gi = cur / ".gitignore"
        if gi.exists():
            try:
                lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            for raw in lines:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                for pattern in _CACHE_GITIGNORE_PATTERNS:
                    if fnmatch.fnmatchcase(line, pattern) or line == pattern:
                        return True
                # Also accept "personas/<name>/.cache/" form at top-level.
                if line.endswith(".cache/") or line.endswith(".cache"):
                    return True
        if cur == persona_root:
            break
        parent = cur.parent
        if parent == cur:  # filesystem root sentinel
            break
        cur = parent
    return False


def _audit_directory_mode(cache_dir: Path) -> None:
    """Raise if ``cache_dir`` has any group/other access bits.

    Spec scenario: msal-auth / "Permission audit fails fast on broken
    filesystem state".
    """
    if not cache_dir.exists():
        return
    mode = os.stat(cache_dir).st_mode
    if mode & 0o077 != 0:
        raise MSALAuthenticationError(
            f"chmod 700 the cache dir: mode={oct(mode & 0o777)} on "
            f"{str(cache_dir)!r} has group/other bits."
        )


def _atomic_write_cache(cache_path: Path, data: str) -> None:
    """Write ``data`` to ``cache_path`` atomically with mode 0o600.

    Implementation discipline (D21):

    * Tmp file lives next to the destination so ``os.rename`` is atomic
      on POSIX.
    * Tmp filename carries a random 8-char suffix so concurrent writers
      don't collide on the tmp path; rename races at the destination
      are last-writer-wins.
    * Tmp file is created via ``os.open(... O_CREAT|O_WRONLY|O_EXCL,
      0o600)`` so the file mode is 0o600 from the moment of creation
      (no umask race window).
    * Stale tmp files older than 5 minutes are swept before retrying
      to clean up after crashed processes.
    """
    cache_dir = cache_path.parent
    suffix = secrets.token_hex(4)  # 8 hex chars
    tmp_path = cache_path.with_name(f"{cache_path.name}.{suffix}.tmp")

    # Sweep stale tmp files matching our sibling pattern first. Pattern:
    # ``<cache_filename>.*.tmp``.
    sweep_pattern = f"{cache_path.name}.*.tmp"
    now = time.time()
    for stale in cache_dir.glob(sweep_pattern):
        try:
            mtime = stale.stat().st_mtime
        except OSError:
            continue
        if now - mtime > _STALE_TMP_SECONDS:
            try:
                stale.unlink()
            except OSError:
                # Best-effort sweep — concurrent collector may have
                # gotten there first.
                pass

    # Defensive: if our randomly-chosen tmp path already exists (1-in-4
    # billion collision, but possible after a crash), fall through and
    # let O_EXCL surface a FileExistsError so the caller sees a clean
    # error rather than silently overwriting another writer's tmp.
    fd = os.open(str(tmp_path), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)
    os.rename(str(tmp_path), str(cache_path))


# ---------------------------------------------------------------------------
# Cache lifecycle — load / save shared between strategies.
# ---------------------------------------------------------------------------


def _resolve_cache_dir(persona: PersonaConfig) -> tuple[Path, Path]:
    """Return ``(cache_dir, persona_root)`` for a given persona.

    Persona root is ``personas/<persona.name>`` resolved against the
    registry's persona dir. Cache dir is ``<persona_root>/.cache``.
    """
    # Lazy import keeps a hard PersonaConfig dependency out of the
    # module top — strategies can be tested with a duck-typed config
    # object.
    from assistant.core.persona import PersonaRegistry

    registry = PersonaRegistry()
    persona_root = (registry.personas_dir / persona.name).resolve()
    cache_dir = persona_root / ".cache"
    return cache_dir, persona_root


def _load_serializable_cache(
    cache_path: Path,
) -> Any:
    """Return a ``msal.SerializableTokenCache`` populated from ``cache_path``.

    Missing-file is silently treated as "empty cache" per msal-auth
    spec scenario "Missing cache file yields empty cache without error".
    """
    import msal  # type: ignore[import-untyped]

    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        try:
            cache.deserialize(cache_path.read_text(encoding="utf-8"))
        except Exception:
            # A corrupt cache should not block the user — fall back to
            # empty cache and let the strategy re-acquire interactively.
            logger.warning(
                "msal_auth: failed to deserialize token cache at %s; "
                "starting with empty cache",
                cache_path,
            )
    return cache


def _persist_cache_if_changed(
    cache: Any,
    *,
    cache_dir: Path,
    cache_path: Path,
    persona_root: Path,
) -> None:
    """Persist ``cache`` to disk when it has state changes.

    Performs the gitignore check + permission audit BEFORE any disk
    write, then creates the directory mode-0o700 if missing, then
    invokes the atomic-write helper. No-op when ``cache.has_state_changed``
    is False (avoids writing a tmpfile for read-only acquire_token_silent
    paths).
    """
    if not cache.has_state_changed:
        return

    # D22: gitignore presence first so a missing entry never lets a
    # token get written even once.
    if not _gitignore_excludes_cache(cache_dir, persona_root):
        raise MSALAuthenticationError(
            f"add `.cache/` to {persona_root!s}/.gitignore: "
            f"refusing to write MSAL tokens to a cache directory "
            f"not excluded by the persona repo's .gitignore chain."
        )

    if not cache_dir.exists():
        # Mode 0o700 from creation. ``os.makedirs`` honors the mode
        # argument modulo the process umask, so we explicitly chmod
        # afterward to enforce the spec invariant.
        cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(str(cache_dir), 0o700)

    # D2: permission audit BEFORE the write (catches the case where
    # the dir was created earlier with a permissive umask and never
    # tightened).
    _audit_directory_mode(cache_dir)

    payload = cache.serialize()
    _atomic_write_cache(cache_path, payload)


# ---------------------------------------------------------------------------
# Strategy implementations.
# ---------------------------------------------------------------------------


def _classify_msal_error(result: dict[str, Any]) -> str:
    """Format a sanitized error string from an MSAL token-result dict."""
    err = result.get("error") or "unknown_error"
    desc = result.get("error_description") or ""
    return f"{err}: {desc}"


def _is_auth_failure(result: dict[str, Any]) -> bool:
    """Return True when the MSAL result indicates auth failure (no retry)."""
    if "error" not in result:
        return False
    code = result.get("error", "")
    # Errors that strictly indicate user-credential failure rather than
    # a transient backend issue — these MUST NOT be retried.
    return code in {
        "invalid_grant",
        "interaction_required",
        "consent_required",
        "login_required",
        "invalid_client",
        "unauthorized_client",
        "access_denied",
    }


class InteractiveDelegatedStrategy:
    """Delegated user-token strategy backed by a per-persona JSON cache.

    First-call path acquires interactively (or via device code under
    ``MSAL_FALLBACK_DEVICE_CODE=1``). Subsequent calls prefer
    ``acquire_token_silent``; silent failure falls back to interactive.

    Constructor is intentionally permissive about the ``persona``
    argument — tests pass a ``DuckPersona`` with just ``name`` and an
    optional ``cache_dir`` override; production passes a full
    ``PersonaConfig``.
    """

    def __init__(
        self,
        persona: PersonaConfig,
        *,
        tenant_id: str,
        client_id: str,
        cache_path: Path | None = None,
        persona_root: Path | None = None,
        authority: str | None = None,
    ) -> None:
        self._persona = persona
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._authority = authority or f"https://login.microsoftonline.com/{tenant_id}"

        if cache_path is None or persona_root is None:
            resolved_dir, resolved_root = _resolve_cache_dir(persona)
            self._cache_dir: Path = cache_path.parent if cache_path else resolved_dir
            self._cache_path: Path = (
                cache_path
                if cache_path is not None
                else resolved_dir / "msal_token_cache.json"
            )
            self._persona_root: Path = (
                persona_root if persona_root is not None else resolved_root
            )
        else:
            self._cache_path = cache_path
            self._cache_dir = cache_path.parent
            self._persona_root = persona_root

        self._cache = _load_serializable_cache(self._cache_path)
        self._app: Any | None = None  # lazy-built msal.PublicClientApplication

    def _get_app(self) -> Any:
        """Construct the MSAL ``PublicClientApplication`` lazily.

        Lazy construction lets tests inject a mocked
        ``msal.PublicClientApplication`` via ``monkeypatch`` without
        having to instantiate the strategy under a context manager.
        """
        if self._app is None:
            import msal

            self._app = msal.PublicClientApplication(
                client_id=self._client_id,
                authority=self._authority,
                token_cache=self._cache,
            )
        return self._app

    async def acquire_token(
        self,
        scopes: list[str],
        *,
        force_refresh: bool = False,
    ) -> str:
        """Acquire a delegated token, persisting any cache changes."""
        app = self._get_app()

        if not force_refresh:
            # Try silent first if we have at least one cached account.
            accounts = await asyncio.to_thread(app.get_accounts)
            if accounts:
                result = await asyncio.to_thread(
                    app.acquire_token_silent,
                    scopes,
                    account=accounts[0],
                )
                if result is not None and "access_token" in result:
                    self._maybe_persist()
                    return str(result["access_token"])
                # silent returned None → refresh token expired or revoked
                # → fall through to interactive.

        # Interactive path (first-run, force_refresh, or silent failure).
        if os.environ.get("MSAL_FALLBACK_DEVICE_CODE") == "1":
            flow = await asyncio.to_thread(app.initiate_device_flow, scopes=scopes)
            if "user_code" not in flow:
                raise MSALAuthenticationError(
                    f"device flow init failed: {flow.get('error_description', flow)}"
                )
            # Spec: "device-code prompt MUST be written to stderr".
            print(flow.get("message", ""), file=sys.stderr, flush=True)
            result = await asyncio.to_thread(app.acquire_token_by_device_flow, flow)
        else:
            result = await asyncio.to_thread(
                app.acquire_token_interactive,
                scopes=scopes,
            )

        if _is_auth_failure(result):
            raise MSALAuthenticationError(_classify_msal_error(result))
        if "access_token" not in result:
            raise MSALAuthenticationError(
                f"interactive acquire failed: {_classify_msal_error(result)}"
            )

        self._maybe_persist()
        return str(result["access_token"])

    def _maybe_persist(self) -> None:
        try:
            _persist_cache_if_changed(
                self._cache,
                cache_dir=self._cache_dir,
                cache_path=self._cache_path,
                persona_root=self._persona_root,
            )
        except OSError as exc:
            # Best-effort persistence: the caller already holds a valid
            # token from MSAL. A transient disk/permissions failure
            # should not fail token acquisition — the next acquire will
            # try silent first (re-using the in-memory cache for this
            # process) and re-attempt the persist. The MSALAuthentication
            # Error from the gitignore guard (D22) deliberately remains
            # fatal — that one signals a structural misconfig the
            # operator must fix before tokens can be cached safely.
            logger.warning(
                "msal_auth: token cache persistence failed "
                "(token still valid for this call): %s",
                exc,
            )


class ClientCredentialsStrategy:
    """App-only token strategy for unattended scenarios (D1).

    Uses ``msal.ConfidentialClientApplication`` with a client secret.
    No cache file, no persona_root coupling — the only state is the
    server-side TTL on the issued token (which the SDK manages).
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        authority: str | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._authority = authority or f"https://login.microsoftonline.com/{tenant_id}"
        self._app: Any | None = None

    def _get_app(self) -> Any:
        if self._app is None:
            import msal

            self._app = msal.ConfidentialClientApplication(
                client_id=self._client_id,
                authority=self._authority,
                client_credential=self._client_secret,
            )
        return self._app

    @staticmethod
    def _validate_app_only_scope(scope: str) -> None:
        """Reject delegated user-scoped requests on an app-only strategy.

        Microsoft Graph convention: app-only tokens MUST request scopes
        of the form ``<resource>/.default`` (e.g.,
        ``https://graph.microsoft.com/.default``). Any user-scoped
        permission name (``Mail.Read``, ``User.Read``) would fail
        server-side; we surface that misuse as an actionable error
        before the wire call.
        """
        # Accept ``.default`` suffix in any resource URL form.
        if not scope.endswith("/.default") and scope != ".default":
            raise MSALAuthenticationError(
                f"use `.default` scope or switch to "
                f"InteractiveDelegatedStrategy: client_credentials "
                f"rejects user scope {scope!r}."
            )

    async def acquire_token(
        self,
        scopes: list[str],
        *,
        force_refresh: bool = False,
    ) -> str:
        for scope in scopes:
            self._validate_app_only_scope(scope)

        app = self._get_app()
        kwargs: dict[str, Any] = {}
        if force_refresh:
            # MSAL exposes a ``force_refresh`` kwarg on
            # ``acquire_token_for_client`` (since 1.23) that bypasses
            # the cache lookup. Pass through when requested.
            kwargs["force_refresh"] = True

        result = await asyncio.to_thread(
            app.acquire_token_for_client,
            scopes=scopes,
            **kwargs,
        )

        if _is_auth_failure(result):
            raise MSALAuthenticationError(_classify_msal_error(result))
        if "access_token" not in result:
            raise MSALAuthenticationError(
                f"client_credentials acquire failed: "
                f"{_classify_msal_error(result)}"
            )
        return str(result["access_token"])


# ---------------------------------------------------------------------------
# Factory — D8 / D23 (use persona.raw, not typed PersonaConfig fields).
# ---------------------------------------------------------------------------


def create_msal_strategy(persona: PersonaConfig) -> MSALStrategy:
    """Select the appropriate ``MSALStrategy`` from ``persona.raw["auth"]["ms"]``.

    Reads ``persona.raw`` rather than typed ``PersonaConfig`` fields
    (D23) — the ``auth.ms`` subtree is not yet promoted to a top-level
    field. The factory:

    1. Looks up ``flow`` (``interactive`` or ``client_credentials``).
    2. Resolves env-var-named credentials (``tenant_id_env``,
       ``client_id_env``, optional ``client_secret_env``) via the
       process environment.
    3. Returns the appropriate strategy instance.

    Missing required env vars or unknown ``flow`` raise
    ``MSALAuthenticationError`` with an actionable message naming the
    missing key.
    """
    raw = persona.raw if hasattr(persona, "raw") else {}
    auth_ms = ((raw.get("auth") or {}).get("ms") or {}) if isinstance(raw, dict) else {}
    flow = (auth_ms.get("flow") or "").strip().lower()
    if flow not in {"interactive", "client_credentials"}:
        raise MSALAuthenticationError(
            f"persona {persona.name!r}: auth.ms.flow must be one of "
            f"'interactive' or 'client_credentials' (got {flow!r}). "
            f"Add `auth.ms.flow:` to {persona.name}/persona.yaml."
        )

    tenant_id_env = auth_ms.get("tenant_id_env") or ""
    client_id_env = auth_ms.get("client_id_env") or ""
    tenant_id = os.environ.get(tenant_id_env, "") if tenant_id_env else ""
    client_id = os.environ.get(client_id_env, "") if client_id_env else ""

    if not tenant_id_env or not tenant_id:
        raise MSALAuthenticationError(
            f"persona {persona.name!r}: auth.ms.tenant_id_env "
            f"({tenant_id_env!r}) is unset or resolves to empty. "
            f"Set the environment variable named in "
            f"`auth.ms.tenant_id_env` to the Entra tenant GUID."
        )
    if not client_id_env or not client_id:
        raise MSALAuthenticationError(
            f"persona {persona.name!r}: auth.ms.client_id_env "
            f"({client_id_env!r}) is unset or resolves to empty. "
            f"Set the environment variable named in "
            f"`auth.ms.client_id_env` to the application (client) ID."
        )

    if flow == "interactive":
        return InteractiveDelegatedStrategy(
            persona,
            tenant_id=tenant_id,
            client_id=client_id,
        )

    # client_credentials path — secret env required.
    client_secret_env = auth_ms.get("client_secret_env") or ""
    client_secret = os.environ.get(client_secret_env, "") if client_secret_env else ""
    if not client_secret_env or not client_secret:
        raise MSALAuthenticationError(
            f"persona {persona.name!r}: auth.ms.client_secret_env "
            f"({client_secret_env!r}) is unset or resolves to empty. "
            f"client_credentials flow requires a non-empty client secret. "
            f"Set the environment variable named in "
            f"`auth.ms.client_secret_env` or switch to "
            f"`auth.ms.flow: interactive`."
        )

    return ClientCredentialsStrategy(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


__all__ = [
    "ClientCredentialsStrategy",
    "InteractiveDelegatedStrategy",
    "MSALAuthenticationError",
    "MSALStrategy",
    "create_msal_strategy",
]
