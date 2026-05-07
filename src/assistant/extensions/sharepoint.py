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
- D6  — Extension internal structure (config, client, breaker, dual
        wrappers, health from breaker)
- D11 — Per-extension tool format conversion (LangChain + MSAF authored
        twice from the same private async method)
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

from assistant.core.cloud_client import CloudGraphClient
from assistant.core.resilience import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    HealthStatus,
    get_circuit_breaker_registry,
    health_status_from_breaker,
)

if TYPE_CHECKING:
    from assistant.core.persona import PersonaConfig

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
# Lazy MSAF decorator resolution — agent-framework lives in the optional
# ``ms`` extras and the package's top-level ``__init__`` may shadow names
# at install time (the package landed as 1.0 with API churn from beta).
# Resolve via importlib so mypy's static check does not trip on the
# decorator name; the runtime fallback returns ``None`` and the caller
# treats it as "extras not installed".
# ---------------------------------------------------------------------------


def _resolve_ai_function() -> Any:
    """Return the ``ai_function`` decorator if importable, else None.

    Per design D5 + D11 the MSAF harness consumes ``as_ms_agent_tools()``
    output decorated with ``@ai_function(name=...)``. The decorator
    lives in ``agent-framework``; if that package is not installed (or
    cannot be imported in the current environment), return None and let
    the caller fall back to bare callables.
    """
    import importlib

    try:
        module = importlib.import_module("agent_framework")
    except ImportError:
        return None
    return getattr(module, "ai_function", None)


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


class SharepointExtension:
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

    # ── Tool wrappers (LangChain + MSAF) ────────────────────────────

    def as_langchain_tools(self) -> list[Any]:
        """Return the three read-only StructuredTool instances.

        Tool format conversion is per-extension (D11) — the MSAF list
        is authored independently from the same private async methods.
        """
        from langchain_core.tools import StructuredTool

        return [
            StructuredTool.from_function(
                coroutine=self._search_sites,
                name="sharepoint.search_sites",
                description=(
                    "Search SharePoint sites by free-text query. Returns "
                    "the parsed `value` array of site objects. "
                    "page_ceiling=100 applies to nextLink chasing; "
                    "narrow the query if results would exceed it."
                ),
            ),
            StructuredTool.from_function(
                coroutine=self._list_documents,
                name="sharepoint.list_documents",
                description=(
                    "List documents at the root of a SharePoint site's "
                    "default document library. Returns the parsed `value` "
                    "array of driveItem objects (files and folders). "
                    "page_ceiling=100; narrow by site or use $top to "
                    "avoid truncation. <= ceil(items / page_size) Graph "
                    "calls per invocation."
                ),
            ),
            StructuredTool.from_function(
                coroutine=self._download_document,
                name="sharepoint.download_document",
                description=(
                    "Download a SharePoint document by site_id + item_id. "
                    "Streams the binary content to a tempfile and returns "
                    "a metadata dict {path, size_bytes, content_type, "
                    "request_id}. The caller is responsible for cleanup. "
                    "Default size ceiling: 50 MiB."
                ),
            ),
        ]

    def as_ms_agent_tools(self) -> list[Any]:
        """Return MSAF-compatible callables (one per tool, D11).

        Each callable's ``__name__`` matches the LangChain tool name so
        the dual-format parity scenario in ms-extensions holds.
        """
        ai_function = _resolve_ai_function()

        bindings: list[tuple[str, Any]] = [
            ("sharepoint.search_sites", self._search_sites),
            ("sharepoint.list_documents", self._list_documents),
            ("sharepoint.download_document", self._download_document),
        ]

        result: list[Any] = []
        for tool_name, fn in bindings:
            if ai_function is not None:
                decorated: Any = ai_function(name=tool_name)(fn)
            else:
                # Without ``agent-framework``, return the bound method
                # but rename it so name-parity checks still pass. The
                # MSAF harness consumes ``as_ms_agent_tools()``; if the
                # extras are missing, the harness raises before tool
                # execution — so a renamed method is sufficient.
                decorated = fn
            try:
                decorated.__name__ = tool_name
            except (AttributeError, TypeError):
                # Some decorated callables forbid attribute assignment;
                # fall back to a tiny wrapper carrying the right
                # __name__.
                async def _bound(*args: Any, _fn: Any = decorated, **kwargs: Any) -> Any:
                    return await _fn(*args, **kwargs)

                _bound.__name__ = tool_name
                decorated = _bound
            result.append(decorated)
        return result

    # ── Health ─────────────────────────────────────────────────────

    async def health_check(self) -> HealthStatus:
        """Derive status from the extension-scoped breaker (D6)."""
        return health_status_from_breaker(
            self._breaker, key=f"extension:{self.name}"
        )

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
) -> SharepointExtension:
    """Construct a ``SharepointExtension`` for the given persona.

    Per D26, the factory accepts a keyword-only ``persona`` (defaults
    to None for the Protocol shape but every real-extension factory
    short-circuits with TypeError when persona is missing — calling
    a real MS-365 extension without persona-driven auth is a
    misconfiguration that we want to surface immediately, not at
    first Graph call).

    The factory:
    1. Short-circuits with actionable ``TypeError`` if persona is None.
    2. Lazy-imports ``create_msal_strategy`` + ``GraphClient`` from
       wp-foundation-impls (so this module imports cleanly even if
       impls have not yet landed).
    3. Builds the per-extension MSAL strategy + GraphClient.
    4. Constructs and returns the ``SharepointExtension``.
    """
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
    client = GraphClient(
        extension_name="sharepoint",
        strategy=strategy,
        scopes=scopes,
    )
    return SharepointExtension(config, client)
