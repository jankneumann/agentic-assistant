"""SharePoint extension — read-only Microsoft 365 document tools.

P5 ``ms-graph-extension`` wp-sharepoint deliverable. Replaces the P1
``StubExtension`` with a real implementation that exposes three tools:

- ``sharepoint.search_sites`` — site search via ``GET /sites?$search=…``
- ``sharepoint.list_documents`` — drive-root listing via
  ``GET /sites/{site_id}/drive/root/children``
- ``sharepoint.download_document`` — binary download via
  ``client.get_bytes(/sites/{site_id}/drive/items/{item_id}/content)``
  (D19 — returns metadata dict, NOT raw bytes)

Write tools (list-item create/update, document upload) are explicitly
deferred to the P5b follow-up. This module ships zero write surface.

Design references:
- D6  — Extension internal structure (config, client, breaker, health
        from breaker)
- P17 tool-spec migration — ``tool_specs()`` compiles the private
  async methods into harness-neutral ToolSpecs (replaces the D11
  dual-format authoring)
- D19 — Binary download via ``get_bytes`` (the central novelty for
        SharePoint — returning raw bytes through the agent context
        would overflow LLM serialization on multi-MB PDFs)
- D23 — Tool input URL-encoding and validation (every interpolated ID
        is ``quote(value, safe="")`` before path interpolation; path
        separators / control chars / backslashes are rejected with
        ``ValueError`` before any HTTP call)
- D24 — Scope override REPLACE semantics (persona scopes supersede
        defaults entirely; empty list / missing key yields defaults)
- D25 — Structured ``GraphAPIError(error_code="breaker_open")`` when
        the per-extension breaker is OPEN, instead of a generic
        ``CircuitBreakerOpenError`` (D9 surfacing-via-typed-error)
- D26 — ``create_extension(config, *, persona)`` factory contract;
        ``persona=None`` short-circuits to actionable ``TypeError``
        before any MSALStrategy / GraphClient construction
"""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from assistant.core.cloud_client import CloudGraphClient
from assistant.core.resilience import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    HealthStatus,
    get_circuit_breaker_registry,
    health_status_from_breaker,
)
from assistant.core.toolspec import ToolSpec, tool_spec_from_model
from assistant.extensions.base import ExtensionBase

if TYPE_CHECKING:
    from assistant.core.persona import PersonaConfig


# ---------------------------------------------------------------------------
# Pydantic args schemas — one per tool, drives both StructuredTool.args_schema
# (LangChain) and per-tool parameter validation. Mirrors the pattern used
# by outlook + teams; without these the StructuredTool surface accepts
# any kwargs and skips validation entirely.
# ---------------------------------------------------------------------------


class _SearchSitesArgs(BaseModel):
    query: str = Field(
        ...,
        description="Free-text search; passed via $search parameter.",
    )
    top: int = Field(
        default=25,
        description="Maximum number of sites to return per page.",
    )


class _ListDocumentsArgs(BaseModel):
    site_id: str = Field(
        ...,
        description=(
            "SharePoint site identifier. URL-encoded as a path segment; "
            "rejected if it contains '/', '\\', or control characters."
        ),
    )
    top: int = Field(
        default=25,
        description="Maximum number of documents to return per page.",
    )


class _DownloadDocumentArgs(BaseModel):
    site_id: str = Field(
        ...,
        description=(
            "SharePoint site identifier. URL-encoded as a path segment."
        ),
    )
    item_id: str = Field(
        ...,
        description=(
            "SharePoint drive-item identifier. URL-encoded as a path "
            "segment."
        ),
    )

# ---------------------------------------------------------------------------
# Default scopes — D24: REPLACE semantics. Persona-provided scopes
# entirely supersede this list; an empty persona list or missing key
# falls back to these defaults.
# ---------------------------------------------------------------------------

DEFAULT_SCOPES: tuple[str, ...] = (
    "Sites.Read.All",
    "Files.Read.All",
)

# ---------------------------------------------------------------------------
# Input validation — D23
# ---------------------------------------------------------------------------

# Control characters \x00-\x1f are rejected from any path-segment ID. A
# raw forward slash or backslash would let a caller break out of the
# intended path segment after URL-encoding (the encoded form is fine,
# but the raw form is a sign of caller misuse — the spec asks us to
# reject it explicitly so the agent gets an immediate, structured
# error instead of an opaque 4xx from Graph).
_FORBIDDEN_CONTROL_CHARS = "".join(chr(i) for i in range(0x20))


def _validate_path_segment(name: str, value: str) -> None:
    """Reject path-segment values containing slashes, backslashes, or
    control characters. Raise ``ValueError`` identifying the offending
    parameter before any HTTP call is issued (D23)."""
    if "/" in value:
        raise ValueError(
            f"sharepoint: {name} must not contain '/' "
            f"(got {value!r}); pass IDs as opaque segments only.",
        )
    if "\\" in value:
        raise ValueError(
            f"sharepoint: {name} must not contain '\\' "
            f"(got {value!r}); pass IDs as opaque segments only.",
        )
    for ch in value:
        if ch in _FORBIDDEN_CONTROL_CHARS:
            raise ValueError(
                f"sharepoint: {name} must not contain control characters "
                f"(got byte 0x{ord(ch):02x} in {value!r}).",
            )


def _quote_segment(value: str) -> str:
    """URL-encode a path segment with ``safe=""`` (D23).

    All reserved characters (including ``/``, ``,``, ``:``, ``;``, etc.)
    are percent-encoded so that the value cannot escape its intended
    path segment when interpolated into the Graph URL.
    """
    return urllib.parse.quote(value, safe="")


# ---------------------------------------------------------------------------
# Scope resolution — D24: REPLACE semantics
# ---------------------------------------------------------------------------


def _resolve_scopes(config: dict[str, Any]) -> list[str]:
    """Return the effective scope list.

    Persona-provided ``scopes`` entirely supersedes ``DEFAULT_SCOPES``.
    An empty list or missing key falls back to defaults. There is NO
    merge mode — a persona that wants to extend defaults must declare
    the full desired list.
    """
    persona_scopes = config.get("scopes")
    if persona_scopes:  # non-empty list/tuple — REPLACE
        return list(persona_scopes)
    return list(DEFAULT_SCOPES)


# ---------------------------------------------------------------------------
# Lazy GraphAPIError — wp-foundation-impls owns the canonical class
# ---------------------------------------------------------------------------


def _get_graph_api_error_cls() -> type[BaseException]:
    """Resolve ``GraphAPIError`` lazily so this module imports cleanly
    in environments where ``wp-foundation-impls`` has not yet landed
    (or where ``msal`` / ``httpx`` cannot import for any reason).

    Returns the canonical ``GraphAPIError`` from
    ``assistant.core.graph_client`` if available; otherwise a local
    surrogate that preserves the ``error_code`` / ``status_code``
    contract surface so D25 callers still see a structured error.
    """
    try:
        from assistant.core.graph_client import GraphAPIError
    except ImportError:
        return _GraphAPIErrorSurrogate
    return GraphAPIError


class _GraphAPIErrorSurrogate(Exception):
    """Local fallback used until ``core/graph_client.py`` lands.

    The class name MUST equal ``GraphAPIError`` so consumers that
    ``except GraphAPIError`` (or check ``__name__``) see a coherent
    error surface during the wp-foundation-impls landing window.
    """

    # The ``GraphAPIError`` name lookup happens via the class's
    # ``__name__`` attribute — set explicitly so any error-shape
    # assertions remain stable regardless of whether the impl class
    # has landed yet.
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id


_GraphAPIErrorSurrogate.__name__ = "GraphAPIError"


def _raise_breaker_open_error(extension_name: str) -> None:
    """Raise ``GraphAPIError(error_code="breaker_open")`` (D25).

    Resolves the error class lazily so the surrogate is used until
    ``wp-foundation-impls`` lands the canonical class. Both surfaces
    expose ``status_code=None`` and ``error_code="breaker_open"`` —
    the canonical impl derives ``status_code`` from a transport-only
    error_code set; the surrogate stores it directly.
    """
    cls = _get_graph_api_error_cls()
    msg = (
        f"sharepoint extension breaker open due to recent consecutive "
        f"failures (extension={extension_name!r})"
    )
    if cls is _GraphAPIErrorSurrogate:
        # Surrogate accepts ``status_code`` directly; pass it for
        # parity with the canonical error_code mapping.
        raise cls(
            msg,
            status_code=None,
            error_code="breaker_open",
        )
    # Canonical GraphAPIError derives ``status_code`` from a
    # transport-only error_code set ({"breaker_open", ...}); we pass
    # only ``error_code`` and let the property compute ``None``.
    raise cls(  # type: ignore[call-arg]
        msg,
        error_code="breaker_open",
    )


# ---------------------------------------------------------------------------
# Extension class
# ---------------------------------------------------------------------------


class SharepointExtension(ExtensionBase):
    """Real SharePoint extension — read-only document tools.

    Construction is via ``create_extension(config, *, persona)`` in
    production; tests instantiate directly with a ``MockGraphClient``.
    """

    name: str = "sharepoint"

    def __init__(
        self,
        config: dict[str, Any],
        client: CloudGraphClient,
    ) -> None:
        self.config = config
        self.scopes: list[str] = _resolve_scopes(config)
        self._client: CloudGraphClient = client
        # Per-extension breaker (D6); the GraphClient owns its own
        # ``graph:sharepoint`` breaker for transport-level failures —
        # the ``extension:sharepoint`` breaker tracked here is the one
        # that ``health_check`` reports against.
        registry: CircuitBreakerRegistry = get_circuit_breaker_registry()
        self._breaker: CircuitBreaker = registry.get_breaker(
            f"extension:{self.name}"
        )

    # ── Tool surface (ToolSpec — spec tool-spec / P17) ──────────────

    def tool_specs(self) -> list[ToolSpec]:
        """Return the three read-only harness-neutral ToolSpecs.

        Per-harness adapters render these; every rendering invokes the
        same private async method.
        """
        source = f"extension:{self.name}"
        return [
            tool_spec_from_model(
                handler=self._search_sites,
                name="sharepoint.search_sites",
                description=(
                    "Search SharePoint sites by free-text query. Returns "
                    "the parsed `value` array of site objects. "
                    "page_ceiling=100 applies to nextLink chasing; "
                    "narrow the query if results would exceed it."
                ),
                args_model=_SearchSitesArgs,
                source=source,
            ),
            tool_spec_from_model(
                handler=self._list_documents,
                name="sharepoint.list_documents",
                description=(
                    "List documents at the root of a SharePoint site's "
                    "default document library. Returns the parsed `value` "
                    "array of driveItem objects (files and folders). "
                    "page_ceiling=100; narrow by site or use $top to "
                    "avoid truncation. <= ceil(items / page_size) Graph "
                    "calls per invocation."
                ),
                args_model=_ListDocumentsArgs,
                source=source,
            ),
            tool_spec_from_model(
                handler=self._download_document,
                name="sharepoint.download_document",
                description=(
                    "Download a SharePoint document by site_id + item_id. "
                    "Streams the binary content to a tempfile and returns "
                    "a metadata dict {path, size_bytes, content_type, "
                    "request_id}. The caller is responsible for cleanup. "
                    "Default size ceiling: 50 MiB."
                ),
                args_model=_DownloadDocumentArgs,
                source=source,
            ),
        ]

    # ── Health ─────────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        """Derive status from the extension-scoped breaker (D6)."""
        return health_status_from_breaker(
            self._breaker, key=f"extension:{self.name}"
        )

    # ── Lifecycle (P10 extension-lifecycle) ────────────────────────
    # ``initialize()`` stays the inherited no-op: eager token
    # acquisition would trigger an interactive MSAL prompt at persona
    # load for the delegated flow (design D7).

    async def shutdown(self) -> None:
        """Close the injected client's connection pool.

        ``CloudGraphClient.aclose()`` is idempotent by contract, so a
        double shutdown (explicit + atexit) is safe.
        """
        await self._client.aclose()

    async def refresh_credentials(self) -> None:
        """Proactively refresh MSAL credentials via the client.

        Delegates to the injected client's ``refresh_credentials()``
        when it exposes one (the real ``GraphClient`` does); mock or
        third-party ``CloudGraphClient`` implementations without the
        method degrade to a no-op (design D6).
        """
        refresh = getattr(self._client, "refresh_credentials", None)
        if callable(refresh):
            await refresh()

    # ── Breaker-state guard ────────────────────────────────────────

    def _check_breaker_open(self) -> None:
        """Raise ``GraphAPIError(error_code="breaker_open")`` if the
        per-extension breaker is OPEN (D25). HALF-OPEN is allowed
        through — a single probe is admitted by the resilience layer
        downstream."""
        if self._breaker.state == "open":
            _raise_breaker_open_error(self.name)

    # ── Tool methods ───────────────────────────────────────────────

    async def _search_sites(
        self,
        query: str,
        top: int = 25,
    ) -> list[dict[str, Any]]:
        """Search SharePoint sites by free-text query.

        Calls ``GET /sites?$search=<query>``. The query is passed via
        ``params`` (D23) so httpx applies query-string encoding;
        nothing is interpolated into the path. Returns the parsed
        ``value`` array. <= ``ceil(items / page_size)`` Graph calls
        per invocation (pagination discipline).
        """
        self._check_breaker_open()
        params: dict[str, Any] = {"$search": query, "$top": top}
        response = await self._client.get("/sites", params=params)
        return list(response.get("value", []))

    async def _list_documents(
        self,
        site_id: str,
        top: int = 25,
    ) -> list[dict[str, Any]]:
        """List documents at the root of a site's default doc library.

        Endpoint: ``GET /sites/{site_id}/drive/root/children``. The
        site_id is URL-encoded as a path segment via
        ``urllib.parse.quote(value, safe="")`` (D23). Returns the
        parsed ``value`` array. <= ``ceil(items / page_size)`` Graph
        calls per invocation (no per-item enrichment).
        """
        self._check_breaker_open()
        _validate_path_segment("site_id", site_id)
        encoded_site = _quote_segment(site_id)
        path = f"/sites/{encoded_site}/drive/root/children"
        response = await self._client.get(path, params={"$top": top})
        return list(response.get("value", []))

    async def _download_document(
        self,
        site_id: str,
        item_id: str,
    ) -> dict[str, Any]:
        """Download a document by site_id + item_id.

        Uses ``client.get_bytes(...)`` (D19) — the response body is
        streamed to a tempfile and a metadata dict is returned with
        keys ``path``, ``size_bytes``, ``content_type``, ``request_id``.
        Raw bytes never enter the agent context. The caller is
        responsible for cleanup of the tempfile.

        Endpoint: ``GET /sites/{site_id}/drive/items/{item_id}/content``.
        Both IDs are URL-encoded as path segments (D23).
        """
        self._check_breaker_open()
        _validate_path_segment("site_id", site_id)
        _validate_path_segment("item_id", item_id)
        encoded_site = _quote_segment(site_id)
        encoded_item = _quote_segment(item_id)
        path = (
            f"/sites/{encoded_site}/drive/items/{encoded_item}/content"
        )
        # ``client.get_bytes`` returns the metadata dict per D19.
        return await self._client.get_bytes(path)


# ---------------------------------------------------------------------------
# Factory (D26)
# ---------------------------------------------------------------------------


def create_extension(
    config: dict[str, Any],
    *,
    persona: PersonaConfig | None = None,
    client: CloudGraphClient | None = None,
) -> SharepointExtension:
    """Construct a ``SharepointExtension`` for the given persona.

    Two construction modes (mirrors teams.create_extension symmetry —
    the four real-extension factories all accept the same shape):

    1. **Production** — ``create_extension(config, persona=persona)``.
       Builds an MSAL strategy and ``GraphClient`` from the persona's
       ``auth.ms`` block. Lazy imports defer the
       ``msal_auth``/``graph_client`` dependency until persona is
       validated (so this module imports cleanly even if impls have
       not yet landed).
    2. **Test** — ``create_extension(config, client=mock_client)``.
       The persona-required short-circuit is skipped; the supplied
       ``CloudGraphClient`` is used directly.

    A call with neither ``persona`` nor ``client`` raises ``TypeError``
    per extension-registry D26 (the persona YAML key path is named so
    the operator can fix the misconfiguration without grep).
    """
    if client is not None:
        return SharepointExtension(config, client)

    if persona is None:
        raise TypeError(
            "Extension 'sharepoint' requires a non-None persona argument "
            "carrying auth.ms configuration. The real Microsoft 365 "
            "SharePoint extension cannot be constructed without an MSAL "
            "strategy + GraphClient — those are built from the persona's "
            "auth.ms.{tenant_id_env, client_id_env, ...} block. Fix the "
            "persona YAML at extensions.sharepoint and auth.ms, or pass "
            "persona=<the loaded PersonaConfig> explicitly when "
            "constructing the extension. (See "
            "openspec/changes/ms-graph-extension/specs/extension-registry/"
            "spec.md scenario 'Real factory called with persona=None "
            "raises actionable TypeError'.)"
        )

    # Defer wp-foundation-impls imports until persona-validated. This
    # keeps the module importable in test environments that have not
    # yet installed msal / agent-framework.
    from assistant.core.graph_client import GraphClient
    from assistant.core.msal_auth import create_msal_strategy

    scopes = _resolve_scopes(config)
    strategy = create_msal_strategy(persona)
    real_client = GraphClient(
        extension_name="sharepoint",
        strategy=strategy,
        scopes=scopes,
    )
    return SharepointExtension(config, real_client)
