"""Cloud-graph transport Protocol.

Defines the ``CloudGraphClient`` contract that every cloud-graph-shaped
backend implements: Microsoft Graph in P5 (custom httpx via
``core/graph_client.py``), Google APIs in P14, and any future
SDK-wrapped variant. The Protocol exists to keep the four MS extensions
(and their tests) unbound from any concrete transport — a future
``MsgraphSdkGraphClient`` adapter would be a drop-in replacement
without touching extension code.

Spec: graph-client / "CloudGraphClient Protocol" (design D3, D19).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from assistant.core.resilience import HealthStatus

# Default 50 MiB ceiling for binary downloads (D19). Streaming the body
# to a tempfile and returning a metadata dict avoids LLM context overflow
# on multi-MB attachments; raw bytes never enter agent context.
DEFAULT_GET_BYTES_MAX: int = 50 * 1024 * 1024


@runtime_checkable
class CloudGraphClient(Protocol):
    """Transport interface for any cloud-graph-shaped API.

    Five transport methods cover 100% of the call shapes the four MS
    extensions need (list/read/binary-download/write/health). Three
    lifecycle methods give callers a uniform async-context-manager
    pattern that survives a future P10 lifecycle migration.

    PUT/PATCH/DELETE deferred to P5b — the four MS extensions are
    read-heavy + two narrow writes (``outlook.send_email``,
    ``teams.post_chat_message``), both of which are POSTs.
    """

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Issue an authenticated GET; return the parsed JSON body.

        Empty 202/204 responses MUST return ``{}`` per D16, not raise.
        """
        ...

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_safe: bool = True,
    ) -> dict[str, Any]:
        """Issue an authenticated POST with ``json`` body.

        ``retry_safe=False`` (D18) routes through a non-retrying path so
        non-idempotent writes (``send_email``, ``post_chat_message``)
        never duplicate on transient 5xx. Breaker state is still
        recorded on failure regardless of ``retry_safe``.
        """
        ...

    def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield each page response as a full dict.

        Chases ``@odata.nextLink`` until exhausted. Yields the full page
        dict (including ``value`` array AND any other top-level keys),
        not individual records — caller decides whether to flatten.
        Raises ``GraphAPIError(error_code="page_ceiling_exceeded")`` on
        page-ceiling overflow rather than truncating silently (D19).

        Cross-domain redirect rejection happens here: any
        ``@odata.nextLink`` whose scheme is not ``https`` or whose host
        is not in the trusted-host set is rejected before the bearer is
        attached (D4).
        """
        ...

    async def get_bytes(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        max_bytes: int = DEFAULT_GET_BYTES_MAX,
    ) -> dict[str, Any]:
        """Stream a binary download to a tempfile; return metadata dict.

        Result keys (D19): ``path`` (absolute tempfile path),
        ``size_bytes``, ``content_type``, ``request_id``. Caller is
        responsible for cleanup. Aborts with
        ``GraphAPIError(error_code="size_exceeded")`` once cumulative
        bytes exceed ``max_bytes``; any partial file is deleted before
        the error raises.
        """
        ...

    async def health_check(self) -> HealthStatus:
        """Report transport health; derived from the per-extension breaker."""
        ...

    async def __aenter__(self) -> CloudGraphClient:
        """Open the underlying connection pool; return ``self``."""
        ...

    async def __aexit__(self, *exc: Any) -> None:
        """Await ``aclose``. ``*exc`` is ``(exc_type, exc_val, exc_tb)``."""
        ...

    async def aclose(self) -> None:
        """Explicit close for callers that cannot use the context-manager form.

        Idempotent — calling twice MUST NOT raise, since
        ``PersonaRegistry.load_extensions`` may end up closing a client
        that was already closed by an ``async with`` block.
        """
        ...
