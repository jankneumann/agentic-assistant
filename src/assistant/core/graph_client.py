"""``GraphClient`` — custom httpx implementation of ``CloudGraphClient``.

Implements the Protocol declared in ``core/cloud_client.py`` against the
Microsoft Graph v1.0 API. The class is constructed once per extension
(per-extension breaker namespace, D4) and consumed via async context
manager. All transport methods (``get``, ``post``, ``paginate``,
``get_bytes``, ``health_check``) compose with P9
``@resilient_http`` for retry + circuit-breaker behavior; non-idempotent
writes (``send_email``, ``post_chat_message``) opt out of retry via
``retry_safe=False`` (D18).

Security discipline:

* ``follow_redirects=False`` on the underlying ``httpx.AsyncClient`` so
  3xx never auto-follows with the bearer token attached (D4).
* ``trusted_hosts`` validated on every ``@odata.nextLink`` BEFORE the
  bearer is attached (D4 / spec "Cross-Domain Redirect Rejection").
* 401 ``invalid_token`` triggers exactly one ``force_refresh=True``
  retry; second 401 propagates as ``MSALAuthenticationError`` (D9).
* ``GraphAPIError`` subclasses ``httpx.HTTPStatusError`` so P9's
  classifier matches and 429/5xx retry naturally (D17).

Spec: openspec/changes/ms-graph-extension/specs/graph-client/spec.md
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import os
import re
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from assistant.core.cloud_client import DEFAULT_GET_BYTES_MAX
from assistant.core.msal_auth import MSALAuthenticationError
from assistant.core.resilience import (
    CircuitBreakerOpenError,
    HealthStatus,
    _sanitize_and_truncate,
    current_retry_attempt,
    get_circuit_breaker_registry,
    health_status_from_breaker,
    resilient_http,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from assistant.core.msal_auth import MSALStrategy

logger = logging.getLogger("assistant.graph_client")

DEFAULT_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_TRUSTED_HOSTS: tuple[str, ...] = (
    "graph.microsoft.com",
    "graph.microsoft.us",
    "microsoftgraph.chinacloudapi.cn",
)
DEFAULT_PAGE_CEILING = 100

DEFAULT_TIMEOUT: httpx.Timeout = httpx.Timeout(
    connect=10.0,
    read=30.0,
    write=30.0,
    pool=5.0,
)

# Path-segment redaction shape for trace_graph_call (D15). A segment is
# considered an "ID" if it is longer than 20 chars OR is a 32-char
# hex / GUID-like token (drive item ID), OR is a base64-y "AAMk..." or
# "AQMk..." Outlook ID. The redaction maps it to ``{message_id}`` —
# the literal placeholder name doesn't matter because dashboards filter
# by request_id + status, not by path-segment identity.
_ID_SEGMENT_RE = re.compile(
    r"^("
    r"[A-Za-z0-9_\-=+/]{20,}"  # long opaque ids (> 20 chars)
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # GUID
    r"|AAMk[A-Za-z0-9_\-]{10,}"  # outlook ids
    r"|AQMk[A-Za-z0-9_\-]{10,}"
    r")$"
)

# UPN local-part redaction for the parent-class ``__str__`` of
# ``GraphAPIError`` (spec scenario "Parent-class URL is sanitized in
# error string"). A UPN is ``<local>@<domain>`` where the local part
# is PII; the domain is a tenant identifier and may stay.
_UPN_LOCAL_RE = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9._%+\-]{0,63})@([A-Za-z0-9][A-Za-z0-9.\-]{0,253}\.[A-Za-z]{2,})\b"
)

# Mapping httpx.TransportError subclass names to a stable error_code
# string used in GraphAPIError + observability spans. Module-scoped so
# both _send_with_auth_retry and _get_bytes_inner reference the same
# table — adding a new subclass means one edit, not two.
_TRANSPORT_ERROR_CODE_MAP: dict[str, str] = {
    "ConnectError": "connect_error",
    "ConnectTimeout": "connect_timeout",
    "ReadTimeout": "read_timeout",
    "ReadError": "read_error",
    "WriteTimeout": "write_timeout",
    "WriteError": "write_error",
    "CloseError": "close_error",
    "PoolTimeout": "pool_timeout",
    "RemoteProtocolError": "protocol_error",
    "LocalProtocolError": "local_protocol_error",
    "ProxyError": "proxy_error",
    "UnsupportedProtocol": "unsupported_protocol",
}


def _redact_upn_local(text: str) -> str:
    """Replace ``<local>@<domain>`` with ``<upn_local>@<domain>``."""
    return _UPN_LOCAL_RE.sub(r"<upn_local>@\2", text)


def _normalize_path(path: str) -> str:
    """Redact ID-shaped segments in ``path`` to ``{message_id}`` placeholders.

    Spec scenario "Path normalization redacts message_id-shaped
    segments" (D15). Only the path component is processed; query
    parameters never appear on the trace_graph_call ``path`` attribute.
    """
    # Strip query string defensively.
    just_path = path.split("?", 1)[0]
    parts = just_path.split("/")
    normalized: list[str] = []
    for seg in parts:
        if not seg:
            normalized.append(seg)
            continue
        if _ID_SEGMENT_RE.match(seg):
            normalized.append("{message_id}")
        else:
            normalized.append(seg)
    return "/".join(normalized)


# ---------------------------------------------------------------------------
# Error type — D17: subclass of httpx.HTTPStatusError so P9 retries
# classify Graph errors via the existing predicate.
# ---------------------------------------------------------------------------


class GraphAPIError(httpx.HTTPStatusError):
    """Microsoft Graph error wrapper. Subclasses ``httpx.HTTPStatusError``.

    Carries typed Graph fields (``error_code``, ``request_id``) on top
    of the inherited ``request`` / ``response`` attributes.
    ``status_code`` exposes ``response.status_code`` — except in the
    transport-error path (read timeout, size_exceeded, breaker_open,
    invalid_redirect) where ``response`` is None and ``status_code``
    is None.

    ``__str__`` runs the full parent-class message (which includes the
    request URL by default) through ``_sanitize_and_truncate`` AND a
    UPN local-part redactor so logged errors never expose tokens or PII
    even when httpx's default formatting includes them.
    """

    def __init__(
        self,
        message: str,
        *,
        request: httpx.Request | None = None,
        response: httpx.Response | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self._extra_message = message
        self.error_code: str | None = error_code
        self.request_id: str | None = request_id
        self.message: str = message

        # Build a synthetic request when none is provided so the
        # parent class's invariants (it expects request + response) are
        # satisfied. Used by transport-error and protocol-error paths
        # (read timeout, size_exceeded, breaker_open, invalid_redirect).
        if request is None:
            request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/")
        if response is None:
            # status_code=599 (transport error) is a non-standard
            # convention; the public ``status_code`` property below
            # returns None for non-real-response cases.
            response = httpx.Response(599, request=request)
        super().__init__(message, request=request, response=response)

    @property
    def status_code(self) -> int | None:
        """Return the wire status code, or None for transport-only errors.

        Transport-error error_codes (``size_exceeded``, ``breaker_open``,
        ``invalid_redirect``, ``read_timeout``, ``page_ceiling_exceeded``)
        all carry ``status_code=None``; consumers use ``error_code`` to
        discriminate.
        """
        transport_only = {
            "size_exceeded",
            "breaker_open",
            "invalid_redirect",
            "read_timeout",
            "page_ceiling_exceeded",
            "connect_error",
        }
        if self.error_code in transport_only:
            return None
        # Fall through to the wire status code. The synthetic 599 used
        # in the transport-error path above is filtered out by the set
        # above, so a 599 here would be a legitimate upstream value.
        return self.response.status_code

    def __str__(self) -> str:
        # Compose the FULL formatted string the way ``httpx`` would if
        # it included the URL by default — the spec scenario
        # "Parent-class URL is sanitized in error string" exists
        # precisely to ensure that whatever the parent-class formatting
        # eventually contains is run through the sanitizer + UPN
        # redactor. Today httpx's ``HTTPStatusError.__str__`` only
        # echoes the message, but we explicitly include URL + status so
        # operators see the full context AND the sanitizer is exercised
        # against any PII-bearing URL.
        try:
            url = str(self.request.url)
        except Exception:
            url = ""
        sc_str: str
        try:
            sc_str = str(self.response.status_code)
        except Exception:
            sc_str = "?"
        combined = (
            f"{self._extra_message} | "
            f"status={sc_str} url={url}"
        )
        return _sanitize_and_truncate(_redact_upn_local(combined))


# ---------------------------------------------------------------------------
# Retry-After parsing — D13.
# ---------------------------------------------------------------------------


def _parse_retry_after(header_value: str | None) -> float | None:
    """Return seconds-to-wait from a ``Retry-After`` header value.

    Returns ``None`` for absent, malformed, or past-date values; a
    structured warning is logged for malformed inputs (D13 / spec
    scenario "Malformed Retry-After is logged and ignored"). The
    header value is sanitized to a bounded length before logging to
    prevent log-injection.
    """
    if not header_value:
        return None

    raw = header_value.strip()
    # Delta-seconds form: an integer.
    try:
        delta = int(raw)
    except (TypeError, ValueError):
        delta = None
    if delta is not None:
        if delta < 0:
            return None
        return float(delta)

    # HTTP-date form (RFC 7231).
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        delta_s = (parsed - datetime.now(UTC)).total_seconds()
        if delta_s <= 0:
            # Past dates fall through to default backoff.
            return None
        return delta_s

    # Malformed — log a sanitized warning and return None so the caller
    # falls through to default backoff.
    bounded = raw[:64].replace("\r", "?").replace("\n", "?")
    logger.warning(
        "graph_client: malformed Retry-After header value=%r; falling "
        "back to default backoff",
        bounded,
    )
    return None


# ---------------------------------------------------------------------------
# Observability emission helper.
# ---------------------------------------------------------------------------


def _emit_graph_call_span(
    *,
    extension_name: str,
    method: str,
    path: str,
    status_code: int | None,
    duration_ms: float,
    breaker_key: str,
    request_id: str | None,
    retry_attempt: int,
    bytes_streamed: int | None = None,
    error: str | None = None,
) -> None:
    """Emit one ``trace_graph_call`` span via the active observability provider.

    Best-effort: any provider exception is swallowed so telemetry
    failures never crash a Graph call.
    """
    try:
        from assistant.telemetry.factory import get_observability_provider

        provider = get_observability_provider()
    except Exception:
        return
    try:
        provider.trace_graph_call(
            extension_name=extension_name,
            method=method,
            path=_normalize_path(path),
            status_code=status_code,
            duration_ms=duration_ms,
            breaker_key=breaker_key,
            request_id=request_id,
            retry_attempt=retry_attempt,
            bytes_streamed=bytes_streamed,
            error=error,
        )
    except Exception:
        logger.debug("trace_graph_call emission failed", exc_info=True)


# ---------------------------------------------------------------------------
# GraphClient.
# ---------------------------------------------------------------------------


class GraphClient:
    """Custom httpx-based ``CloudGraphClient`` for Microsoft Graph v1.0."""

    def __init__(
        self,
        *,
        extension_name: str,
        strategy: MSALStrategy,
        scopes: list[str] | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: httpx.Timeout | None = None,
        page_ceiling: int = DEFAULT_PAGE_CEILING,
        trusted_hosts: list[str] | None = None,
        max_retry_after_seconds: float = 60.0,
    ) -> None:
        self.extension_name = extension_name
        self._strategy = strategy
        self._scopes: list[str] = list(scopes) if scopes else []
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self._page_ceiling = page_ceiling
        self._trusted_hosts: tuple[str, ...] = (
            tuple(trusted_hosts) if trusted_hosts else DEFAULT_TRUSTED_HOSTS
        )
        # Upper bound on Retry-After waits. Prevents a malicious or
        # mis-configured upstream from pinning the event loop on a
        # large header value while still letting persona configs
        # raise the bound for high-traffic accounts that hit
        # legitimate multi-minute throttle responses.
        self._max_retry_after_seconds = max_retry_after_seconds
        self._breaker_key = f"graph:{extension_name}"
        # P9 registry returns the same breaker on second lookup, so
        # multiple GraphClient(extension_name=X) share state.
        self._breaker = get_circuit_breaker_registry().get_breaker(self._breaker_key)
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,  # D4
        )
        self._closed = False

    # ── Lifecycle ──────────────────────────────────────────────────

    async def __aenter__(self) -> GraphClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._client.aclose()
        except Exception:
            logger.debug("graph_client: aclose suppressed", exc_info=True)

    # ── Helpers ────────────────────────────────────────────────────

    async def _bearer_token(self, *, force_refresh: bool = False) -> str:
        return await self._strategy.acquire_token(
            self._scopes,
            force_refresh=force_refresh,
        )

    def _full_url(self, path: str) -> str:
        """Resolve ``path`` to an absolute Graph URL.

        Two accepted shapes:

        - Absolute https URL (any scheme starting with ``http://`` or
          ``https://``) — returned verbatim. ``paginate`` uses this for
          ``@odata.nextLink`` continuation, which is already validated
          against ``_trusted_hosts`` before reaching here.
        - Relative path — prepended to ``self._base_url``. Must NOT
          contain ``..`` segments; relative parent traversal would
          allow a caller to escape the Graph version prefix
          (``/v1.0``) and is rejected with ``ValueError`` before any
          HTTP call.
        """
        if path.startswith(("http://", "https://")):
            return path
        if ".." in path.split("/"):
            raise ValueError(
                f"graph_client: relative path {path!r} contains '..' "
                "segment; parent-directory traversal is not permitted"
            )
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._base_url}{path}"

    def _validate_redirect_target(self, url: str) -> None:
        """Reject untrusted scheme/host BEFORE attaching bearer (D4)."""
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise GraphAPIError(
                message=(
                    f"refusing to follow nextLink with non-https scheme "
                    f"{parsed.scheme!r} (host={parsed.hostname!r})"
                ),
                error_code="invalid_redirect",
            )
        host = (parsed.hostname or "").lower()
        if host not in {h.lower() for h in self._trusted_hosts}:
            raise GraphAPIError(
                message=(
                    f"refusing to follow nextLink to untrusted host "
                    f"{host!r}; allowed hosts: {sorted(self._trusted_hosts)}"
                ),
                error_code="invalid_redirect",
            )

    @staticmethod
    def _request_id_of(response: httpx.Response | None) -> str | None:
        if response is None:
            return None
        return (
            response.headers.get("request-id")
            or response.headers.get("client-request-id")
        )

    @staticmethod
    def _parse_body_for_error(response: httpx.Response) -> tuple[str | None, str | None]:
        """Return ``(error_code, message)`` from a Graph error body."""
        try:
            body = response.json()
        except Exception:
            return None, response.text or response.reason_phrase or "graph error"
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            err = body["error"]
            return err.get("code"), err.get("message") or response.reason_phrase
        return None, response.text or response.reason_phrase

    @staticmethod
    def _is_empty_body_response(response: httpx.Response) -> bool:
        """D16: 202/204/empty-body 200 returns ``{}`` rather than parsing."""
        if response.status_code in (202, 204):
            return True
        # Some Graph endpoints return 200 with zero-length body and a
        # JSON content-type. Treating those as empty-dict avoids the
        # JSON-parse error for the caller.
        if response.status_code == 200 and not response.content:
            return True
        return False

    @staticmethod
    def _parse_json_body(response: httpx.Response) -> dict[str, Any]:
        if GraphClient._is_empty_body_response(response):
            return {}
        try:
            data = response.json()
        except Exception:
            return {}
        if isinstance(data, dict):
            return data
        # Some endpoints can return a list at the top level; wrap so the
        # consumer's ``dict[str, Any]`` annotation holds.
        return {"value": data} if isinstance(data, list) else {}

    async def _send_with_auth_retry(
        self,
        request: httpx.Request,
        *,
        retry_attempt: int | None = None,
    ) -> tuple[httpx.Response, int]:
        """Send ``request`` with bearer; on 401 ``invalid_token``, force-refresh once.

        Returns ``(response, final_retry_attempt)``. When called
        directly the caller can pass ``retry_attempt`` explicitly; when
        called from inside a ``resilient_http`` retry loop, the default
        ``None`` reads the current attempt from
        ``current_retry_attempt`` (the resilience-layer ContextVar) so
        per-attempt spans attribute correctly to the P9 retry index
        rather than always reporting attempt 0. The auth-refresh replay
        increments the counter by one further so dashboards can
        distinguish a P9 retry from an auth-refresh retry.
        """
        if retry_attempt is None:
            retry_attempt = current_retry_attempt.get()
        token = await self._bearer_token()
        request.headers["Authorization"] = f"Bearer {token}"

        start_t = time.perf_counter()
        try:
            response = await self._client.send(request)
        except httpx.TransportError as exc:
            duration_ms = (time.perf_counter() - start_t) * 1000.0
            exc_name = type(exc).__name__
            _emit_graph_call_span(
                extension_name=self.extension_name,
                method=request.method,
                path=request.url.path,
                status_code=None,
                duration_ms=duration_ms,
                breaker_key=self._breaker_key,
                request_id=None,
                retry_attempt=retry_attempt,
                error=exc_name,
            )
            # Map all transport-level errors to GraphAPIError so P9's
            # classifier sees a single error type and the caller's
            # except-clause stays compact. ``httpx.TransportError`` is
            # the base of ConnectError/ReadError/WriteError/Timeouts/
            # ProtocolErrors/ProxyError/UnsupportedProtocol — the full
            # transport-tier surface. Distinct error_code per class so
            # dashboards can break down by failure mode.
            raise GraphAPIError(
                message=(
                    f"{exc_name} during Graph request "
                    f"({request.method} {request.url.path}): {exc}"
                ),
                request=request,
                error_code=_TRANSPORT_ERROR_CODE_MAP.get(
                    exc_name, "transport_error"
                ),
            ) from exc

        duration_ms = (time.perf_counter() - start_t) * 1000.0
        request_id = self._request_id_of(response)

        # Auth refresh path (D9 / spec "Authentication Token Refresh
        # on 401").
        if response.status_code == 401:
            www_auth = response.headers.get("WWW-Authenticate", "")
            if 'error="invalid_token"' in www_auth:
                _emit_graph_call_span(
                    extension_name=self.extension_name,
                    method=request.method,
                    path=request.url.path,
                    status_code=401,
                    duration_ms=duration_ms,
                    breaker_key=self._breaker_key,
                    request_id=request_id,
                    retry_attempt=retry_attempt,
                    error="GraphAPIError",
                )
                # Force-refresh exactly once.
                start_t2 = time.perf_counter()
                try:
                    fresh = await self._bearer_token(force_refresh=True)
                    request.headers["Authorization"] = f"Bearer {fresh}"
                    response2 = await self._client.send(request)
                except Exception as exc:
                    # Auth-refresh attempt itself failed (token endpoint
                    # down, transport error, MSAL exception). Emit a
                    # span with status_code=None so the failed refresh
                    # round-trip is visible in dashboards before we
                    # propagate. Without this, the only signal is the
                    # bare exception — error rate metrics would miss it.
                    duration_ms_2 = (time.perf_counter() - start_t2) * 1000.0
                    _emit_graph_call_span(
                        extension_name=self.extension_name,
                        method=request.method,
                        path=request.url.path,
                        status_code=None,
                        duration_ms=duration_ms_2,
                        breaker_key=self._breaker_key,
                        request_id=None,
                        retry_attempt=retry_attempt + 1,
                        error=type(exc).__name__,
                    )
                    raise
                duration_ms_2 = (time.perf_counter() - start_t2) * 1000.0
                request_id_2 = self._request_id_of(response2)
                _emit_graph_call_span(
                    extension_name=self.extension_name,
                    method=request.method,
                    path=request.url.path,
                    status_code=response2.status_code,
                    duration_ms=duration_ms_2,
                    breaker_key=self._breaker_key,
                    request_id=request_id_2,
                    retry_attempt=retry_attempt + 1,
                    error=(
                        None
                        if response2.is_success or response2.status_code in (202, 204)
                        else "GraphAPIError"
                    ),
                )
                if response2.status_code == 401:
                    raise MSALAuthenticationError(
                        f"persistent 401 invalid_token after force_refresh "
                        f"on {request.method} {request.url.path}"
                    )
                return response2, retry_attempt + 1
            # 401 without invalid_token marker — treat as a regular auth
            # error and surface as MSALAuthenticationError so
            # @resilient_http does NOT retry.
            _emit_graph_call_span(
                extension_name=self.extension_name,
                method=request.method,
                path=request.url.path,
                status_code=401,
                duration_ms=duration_ms,
                breaker_key=self._breaker_key,
                request_id=request_id,
                retry_attempt=retry_attempt,
                error="MSALAuthenticationError",
            )
            raise MSALAuthenticationError(
                f"401 unauthorized on {request.method} {request.url.path}"
            )

        # Normal path — emit span, surface 4xx-other / 5xx as
        # GraphAPIError so P9 classifier sees retriable / non-retriable
        # status codes.
        is_error = not response.is_success and not self._is_empty_body_response(response)
        _emit_graph_call_span(
            extension_name=self.extension_name,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            breaker_key=self._breaker_key,
            request_id=request_id,
            retry_attempt=retry_attempt,
            error="GraphAPIError" if is_error else None,
        )
        if is_error:
            await self._honor_retry_after(response)
            error_code, msg = self._parse_body_for_error(response)
            raise GraphAPIError(
                message=msg or response.reason_phrase or "graph error",
                request=request,
                response=response,
                error_code=error_code,
                request_id=request_id,
            )
        return response, retry_attempt

    async def _honor_retry_after(self, response: httpx.Response) -> None:
        """If a 429/503 carries Retry-After, sleep that long before raising.

        D13: Retry-After supersedes generic exponential backoff for
        these status codes. The actual retry decision is made by P9 —
        we only ensure the caller-visible wait is at least the
        Retry-After value before P9's wait_strategy is invoked. Past
        and malformed values fall through to default backoff.
        """
        if response.status_code not in (429, 503):
            return
        wait_s = _parse_retry_after(response.headers.get("Retry-After"))
        if wait_s is None or wait_s <= 0:
            return
        # Cap the wait to a sane bound so a malicious Retry-After:
        # 1000000 doesn't pin the event loop. The cap is configurable
        # via GraphClient(max_retry_after_seconds=...) for personas
        # that legitimately need to honor longer throttles.
        bounded = min(wait_s, self._max_retry_after_seconds)
        await asyncio.sleep(bounded)

    # ── Transport methods ──────────────────────────────────────────

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET ``path``; return parsed JSON or ``{}`` on 202/204.

        Wrapped with ``@resilient_http`` via ``_get_impl``.
        """
        return await self._get_impl(path, params=params, headers=headers)

    @resilient_http(breaker_key="graph:_dispatch")
    async def _get_impl_decorated(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Internal retried path; the breaker_key here is OVERRIDDEN by
        the per-instance dispatch (see ``_get_impl``)."""
        # Unreachable in practice — the per-instance dispatch redirects
        # before this runs. Kept for documentation.
        return await self._get_inner(path, params=params, headers=headers)

    async def _get_inner(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self._full_url(path)
        request = self._client.build_request(
            "GET",
            url,
            params=params,
            headers=headers,
        )
        response, _ = await self._send_with_auth_retry(request)
        return self._parse_json_body(response)

    async def _get_impl(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Per-instance retried entry point.

        We can't decorate the bound method directly with
        ``@resilient_http(breaker_key=f"graph:{name}")`` at class-body
        time because ``self.extension_name`` isn't known yet. Instead,
        we wrap a closure each call so the breaker key matches this
        instance.
        """
        wrapped = resilient_http(breaker_key=self._breaker_key)(self._get_inner)
        try:
            return await wrapped(path, params=params, headers=headers)
        except CircuitBreakerOpenError as exc:
            raise GraphAPIError(
                message=f"breaker {self._breaker_key} is open: {exc}",
                error_code="breaker_open",
            ) from exc

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_safe: bool = True,
    ) -> dict[str, Any]:
        """POST JSON body; route through retrying or non-retrying path (D18)."""
        if retry_safe:
            return await self._post_retrying(
                path, json=json, params=params, headers=headers
            )
        return await self._post_no_retry(
            path, json=json, params=params, headers=headers
        )

    async def _post_retrying(
        self,
        path: str,
        *,
        json: dict[str, Any],
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        wrapped = resilient_http(breaker_key=self._breaker_key)(self._post_inner)
        try:
            return await wrapped(path, json=json, params=params, headers=headers)
        except CircuitBreakerOpenError as exc:
            raise GraphAPIError(
                message=f"breaker {self._breaker_key} is open: {exc}",
                error_code="breaker_open",
            ) from exc

    async def _post_no_retry(
        self,
        path: str,
        *,
        json: dict[str, Any],
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        """Non-retrying POST path (D18 / spec "Per-Method Retry Safety Control").

        Breaker state is still recorded on availability failures —
        ``retry_safe=False`` only opts out of the retry layer, not out
        of the circuit-breaker accounting that protects sibling calls.
        """
        try:
            async with self._breaker.acquire_admission():
                try:
                    result = await self._post_inner(
                        path, json=json, params=params, headers=headers
                    )
                except Exception as exc:
                    # Mirror P9's ``_is_availability_failure`` logic
                    # (httpx HTTPStatusError on retriable status, transport
                    # exceptions). Without the retry layer we record
                    # directly here.
                    if isinstance(exc, GraphAPIError):
                        sc = exc.status_code
                        if sc in (408, 425, 429, 500, 502, 503, 504):
                            await self._breaker.record_failure(exc)
                    elif isinstance(exc, httpx.TransportError):
                        await self._breaker.record_failure(exc)
                    raise
                # Success: record so a HALF_OPEN breaker can close (the
                # @resilient_http path records via tenacity's success
                # hook, but _post_no_retry bypasses that path entirely
                # for D18 retry-safe=False writes — without an explicit
                # record_success here, send_email and post_chat_message
                # leave a probing breaker stuck in HALF_OPEN forever).
                await self._breaker.record_success()
                return result
        except CircuitBreakerOpenError as exc:
            raise GraphAPIError(
                message=f"breaker {self._breaker_key} is open: {exc}",
                error_code="breaker_open",
            ) from exc

    async def _post_inner(
        self,
        path: str,
        *,
        json: dict[str, Any],
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        url = self._full_url(path)
        request = self._client.build_request(
            "POST",
            url,
            json=json,
            params=params,
            headers=headers,
        )
        response, _ = await self._send_with_auth_retry(request)
        return self._parse_json_body(response)

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield successive pages of ``@odata.nextLink`` results.

        Page-ceiling discipline (D19): on the (N+1)-th request when
        ``page_ceiling=N`` is exceeded, ``GraphAPIError(error_code=
        "page_ceiling_exceeded")`` is raised after a warning log
        rather than truncating silently. Cross-domain rejection (D4)
        validates each ``@odata.nextLink`` BEFORE attaching the bearer.
        """
        first_url = self._full_url(path)
        next_url: str | None = first_url
        next_params: dict[str, Any] | None = params
        page_count = 0
        while next_url is not None:
            if page_count >= self._page_ceiling:
                logger.warning(
                    "graph_client: page_ceiling=%d exceeded for path=%r; "
                    "raising rather than truncating",
                    self._page_ceiling,
                    path,
                )
                raise GraphAPIError(
                    message=(
                        f"pagination exceeded page_ceiling={self._page_ceiling} "
                        f"for path {path!r}"
                    ),
                    error_code="page_ceiling_exceeded",
                )

            page = await self._paginate_one_page(next_url, next_params)
            page_count += 1
            yield page

            link = page.get("@odata.nextLink")
            if not link or not isinstance(link, str):
                break
            # Validate before the next iteration so the bearer attached
            # to the next request is only attached after the host check.
            self._validate_redirect_target(link)
            next_url = link
            next_params = None  # nextLink already encodes its params

    async def _paginate_one_page(
        self,
        url: str,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Fetch a single page (used by ``paginate``)."""
        # Each page goes through the resilience+breaker stack.
        async def _fetch() -> dict[str, Any]:
            request = self._client.build_request("GET", url, params=params)
            response, _ = await self._send_with_auth_retry(request)
            return self._parse_json_body(response)

        wrapped = resilient_http(breaker_key=self._breaker_key)(_fetch)
        try:
            return await wrapped()
        except CircuitBreakerOpenError as exc:
            raise GraphAPIError(
                message=f"breaker {self._breaker_key} is open: {exc}",
                error_code="breaker_open",
            ) from exc

    async def get_bytes(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        max_bytes: int = DEFAULT_GET_BYTES_MAX,
    ) -> dict[str, Any]:
        """Stream binary download to a tempfile; return metadata dict.

        D19: result keys are ``path``, ``size_bytes``, ``content_type``,
        ``request_id``. Aborts with
        ``GraphAPIError(error_code="size_exceeded")`` once cumulative
        bytes exceed ``max_bytes``; partial file is deleted before raise.
        """
        wrapped = resilient_http(breaker_key=self._breaker_key)(
            self._get_bytes_inner
        )
        try:
            return await wrapped(
                path,
                params=params,
                headers=headers,
                max_bytes=max_bytes,
            )
        except CircuitBreakerOpenError as exc:
            raise GraphAPIError(
                message=f"breaker {self._breaker_key} is open: {exc}",
                error_code="breaker_open",
            ) from exc

    async def _get_bytes_inner(
        self,
        path: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        max_bytes: int,
    ) -> dict[str, Any]:
        """Stream a binary download with 401-refresh and one-hop redirect.

        Two non-trivial protocol behaviors that get/post handle via
        ``_send_with_auth_retry`` but that streaming downloads must
        handle inline because we cannot buffer the body before deciding
        whether to retry:

        - **401 invalid_token**: per graph-client spec "Authentication
          Token Refresh on 401", a single ``force_refresh=True`` retry
          must be attempted before raising. Without this, a stale-cache
          token at the start of a long-running session would fail every
          download even though the next get/post would succeed.

        - **302/307 redirect**: SharePoint's
          ``/sites/{id}/drive/items/{id}/content`` returns a 302 to a
          pre-signed download URL on Azure storage rather than serving
          bytes inline. With ``follow_redirects=False`` set on the
          client (D4 — pagination redirect-rejection), we must follow
          this exactly once, validate the target is HTTPS, and **strip
          the Authorization header** before issuing the follow-up
          request: pre-signed URLs embed their own auth in query
          parameters, and forwarding the bearer to a non-Graph host
          would leak it.

        Both branches are bounded to one attempt each so a hostile
        upstream cannot construct a redirect/refresh loop.
        """
        token = await self._bearer_token()
        merged_headers = dict(headers or {})
        merged_headers["Authorization"] = f"Bearer {token}"
        url = self._full_url(path)
        request_params = params

        fd, tmp_path = tempfile.mkstemp(prefix="graph_dl_", suffix=".bin")
        os.close(fd)

        cumulative: int = 0
        request_id: str | None = None
        content_type: str = "application/octet-stream"
        emitted_path = path
        method = "GET"
        # Two separate counters:
        # - ``auth_refreshes``/``redirect_follows`` (0 or 1 each) gate
        #   the once-only auth-refresh and once-only redirect-follow
        #   behaviors below.
        # - ``base_attempt`` reports the P9 resilient_http retry index
        #   to observability so spans attribute to the correct attempt
        #   even when this method is invoked under retry.
        auth_refreshes = 0
        redirect_follows = 0
        base_attempt = current_retry_attempt.get()

        try:
            while True:
                start_t = time.perf_counter()
                async with self._client.stream(
                    "GET",
                    url,
                    params=request_params,
                    headers=merged_headers,
                ) as response:
                    request_id = self._request_id_of(response)
                    content_type = response.headers.get(
                        "Content-Type", "application/octet-stream"
                    )
                    emitted_path = response.request.url.path

                    # 401 invalid_token → exactly one force_refresh retry.
                    # Only allowed BEFORE a redirect: after we follow a
                    # 302/307 we have stripped Authorization (the
                    # pre-signed URL embeds its own auth in URL params).
                    # A 401 from the redirect target does NOT mean our
                    # Graph bearer is stale; force-refreshing and
                    # re-attaching the Graph bearer to a non-Graph host
                    # would leak the token (same D4 principle that
                    # motivates the strip-Authorization step on
                    # redirect).
                    if (
                        response.status_code == 401
                        and auth_refreshes == 0
                        and redirect_follows == 0
                    ):
                        www_auth = response.headers.get("WWW-Authenticate", "")
                        if 'error="invalid_token"' in www_auth:
                            duration_ms = (time.perf_counter() - start_t) * 1000.0
                            _emit_graph_call_span(
                                extension_name=self.extension_name,
                                method=method,
                                path=emitted_path,
                                status_code=401,
                                duration_ms=duration_ms,
                                breaker_key=self._breaker_key,
                                request_id=request_id,
                                retry_attempt=(
                                    base_attempt
                                    + auth_refreshes
                                    + redirect_follows
                                ),
                                bytes_streamed=0,
                                error="GraphAPIError",
                            )
                            auth_refreshes += 1
                            try:
                                fresh = await self._bearer_token(
                                    force_refresh=True
                                )
                            except Exception as exc:
                                # Auth-refresh attempt itself failed —
                                # emit span before propagating so the
                                # failure is visible in dashboards.
                                _emit_graph_call_span(
                                    extension_name=self.extension_name,
                                    method=method,
                                    path=emitted_path,
                                    status_code=None,
                                    duration_ms=(
                                        time.perf_counter() - start_t
                                    ) * 1000.0,
                                    breaker_key=self._breaker_key,
                                    request_id=None,
                                    retry_attempt=(
                                        base_attempt
                                        + auth_refreshes
                                        + redirect_follows
                                    ),
                                    error=type(exc).__name__,
                                )
                                raise
                            merged_headers["Authorization"] = f"Bearer {fresh}"
                            continue

                    # 302/307 redirect → exactly one hop, strip Auth
                    if (
                        response.status_code in (302, 307)
                        and redirect_follows == 0
                    ):
                        location = response.headers.get("Location", "")
                        if not location.startswith("https://"):
                            duration_ms = (time.perf_counter() - start_t) * 1000.0
                            _emit_graph_call_span(
                                extension_name=self.extension_name,
                                method=method,
                                path=emitted_path,
                                status_code=response.status_code,
                                duration_ms=duration_ms,
                                breaker_key=self._breaker_key,
                                request_id=request_id,
                                retry_attempt=(
                                    base_attempt
                                    + auth_refreshes
                                    + redirect_follows
                                ),
                                bytes_streamed=0,
                                error="GraphAPIError",
                            )
                            raise GraphAPIError(
                                message=(
                                    f"download redirect Location must be "
                                    f"https://; got {location!r}"
                                ),
                                request=response.request,
                                response=response,
                                error_code="redirect_invalid",
                                request_id=request_id,
                            )
                        duration_ms = (time.perf_counter() - start_t) * 1000.0
                        _emit_graph_call_span(
                            extension_name=self.extension_name,
                            method=method,
                            path=emitted_path,
                            status_code=response.status_code,
                            duration_ms=duration_ms,
                            breaker_key=self._breaker_key,
                            request_id=request_id,
                            retry_attempt=(
                                base_attempt
                                + auth_refreshes
                                + redirect_follows
                            ),
                            bytes_streamed=0,
                            error=None,
                        )
                        redirect_follows += 1
                        url = location
                        request_params = None  # Location URL embeds its own params
                        # Strip Authorization: pre-signed URLs use SAS
                        # tokens in the URL itself; forwarding our bearer
                        # to a non-Graph host would leak it.
                        merged_headers.pop("Authorization", None)
                        continue

                    if not response.is_success:
                        duration_ms = (time.perf_counter() - start_t) * 1000.0
                        _emit_graph_call_span(
                            extension_name=self.extension_name,
                            method=method,
                            path=emitted_path,
                            status_code=response.status_code,
                            duration_ms=duration_ms,
                            breaker_key=self._breaker_key,
                            request_id=request_id,
                            retry_attempt=(
                                base_attempt
                                + auth_refreshes
                                + redirect_follows
                            ),
                            bytes_streamed=0,
                            error="GraphAPIError",
                        )
                        await response.aread()
                        error_code, msg = self._parse_body_for_error(response)
                        raise GraphAPIError(
                            message=msg or response.reason_phrase or "graph error",
                            request=response.request,
                            response=response,
                            error_code=error_code,
                            request_id=request_id,
                        )

                    with open(tmp_path, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            cumulative += len(chunk)
                            if cumulative > max_bytes:
                                duration_ms = (
                                    time.perf_counter() - start_t
                                ) * 1000.0
                                _emit_graph_call_span(
                                    extension_name=self.extension_name,
                                    method=method,
                                    path=emitted_path,
                                    status_code=response.status_code,
                                    duration_ms=duration_ms,
                                    breaker_key=self._breaker_key,
                                    request_id=request_id,
                                    retry_attempt=(
                                        base_attempt
                                        + auth_refreshes
                                        + redirect_follows
                                    ),
                                    bytes_streamed=cumulative,
                                    error="GraphAPIError",
                                )
                                f.close()
                                try:
                                    os.unlink(tmp_path)
                                except OSError:
                                    pass
                                raise GraphAPIError(
                                    message=(
                                        f"download exceeded max_bytes={max_bytes} "
                                        f"(read {cumulative} bytes)"
                                    ),
                                    error_code="size_exceeded",
                                )
                            f.write(chunk)
                    duration_ms = (time.perf_counter() - start_t) * 1000.0
                    _emit_graph_call_span(
                        extension_name=self.extension_name,
                        method=method,
                        path=emitted_path,
                        status_code=200,
                        duration_ms=duration_ms,
                        breaker_key=self._breaker_key,
                        request_id=request_id,
                        retry_attempt=(
                            base_attempt
                            + auth_refreshes
                            + redirect_follows
                        ),
                        bytes_streamed=cumulative,
                        error=None,
                    )
                    return {
                        "path": tmp_path,
                        "size_bytes": cumulative,
                        "content_type": content_type,
                        "request_id": request_id,
                    }
        except httpx.TransportError as exc:
            # Connect/read/write/protocol failure during the streaming
            # round-trip OR during context-manager entry. Emit a span
            # before mapping to GraphAPIError so the failure is visible
            # in dashboards — same observability shape as
            # _send_with_auth_retry's transport-error handler.
            duration_ms = (time.perf_counter() - start_t) * 1000.0
            exc_name = type(exc).__name__
            _emit_graph_call_span(
                extension_name=self.extension_name,
                method=method,
                path=emitted_path,
                status_code=None,
                duration_ms=duration_ms,
                breaker_key=self._breaker_key,
                request_id=None,
                retry_attempt=(
                    base_attempt + auth_refreshes + redirect_follows
                ),
                bytes_streamed=cumulative,
                error=exc_name,
            )
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise GraphAPIError(
                message=(
                    f"{exc_name} during get_bytes "
                    f"({method} {emitted_path}): {exc}"
                ),
                error_code=_TRANSPORT_ERROR_CODE_MAP.get(
                    exc_name, "transport_error"
                ),
            ) from exc
        except GraphAPIError:
            try:
                if cumulative == 0 and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise

    async def health_check(self) -> HealthStatus:
        """Map the per-extension breaker state to a ``HealthStatus``."""
        return health_status_from_breaker(self._breaker, key=self._breaker_key)


# ---------------------------------------------------------------------------
# Convenience helpers — used by extension factories.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def graph_client_context(
    *,
    extension_name: str,
    strategy: MSALStrategy,
    scopes: list[str] | None = None,
) -> AsyncIterator[GraphClient]:
    """Async-context-manager helper for ad-hoc GraphClient lifetimes."""
    client = GraphClient(
        extension_name=extension_name,
        strategy=strategy,
        scopes=scopes,
    )
    try:
        yield client
    finally:
        await client.aclose()


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_PAGE_CEILING",
    "DEFAULT_TIMEOUT",
    "DEFAULT_TRUSTED_HOSTS",
    "GraphAPIError",
    "GraphClient",
    "graph_client_context",
]
