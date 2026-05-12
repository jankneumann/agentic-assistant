"""Real ``ms_graph`` extension — generic Microsoft Graph tools.

Per OpenSpec change ``ms-graph-extension`` (P5), spec
``ms-extensions / ms_graph Extension Real Implementation``. Replaces the
P1 11-line stub with the canonical extension shape (D6, D11):

- One ``MsGraphExtension`` class with the seven-method ``Extension``
  contract.
- A canonical private async method per tool (``_search_people``,
  ``_get_my_profile``, ``_search_messages``); ``as_langchain_tools()`` and
  ``as_ms_agent_tools()`` each wrap the same private method, so behaviour
  is identical at the wire level regardless of harness.
- ``health_check()`` derived from the per-extension circuit breaker
  (``extension:ms_graph``) via :func:`health_status_from_breaker`.
- ``create_extension(config, *, persona)`` factory that short-circuits
  with an actionable :class:`TypeError` when ``persona is None`` (D26).
- All user-supplied path-segment values pass through
  :func:`_validate_path_segment` (D23) before any HTTP call. Search
  strings flow via ``params={"$search": ...}`` — never embedded in a
  path — so httpx applies query-string encoding correctly.
- OPEN-breaker tool invocation surfaces as
  ``GraphAPIError(error_code="breaker_open")`` (D25).

Tool wiring is intentionally minimal: this extension currently exposes
three GET-shaped read tools and no IDs are interpolated into paths
today. The :func:`_validate_path_segment` helper is exported for symmetry
with the sibling extensions (and to make D23 testable here even before
the path-bearing tools land in P5b).
"""

from __future__ import annotations

import unicodedata
import urllib.parse
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from assistant.core.cloud_client import CloudGraphClient
from assistant.core.resilience import (
    CircuitBreakerRegistry,
    HealthStatus,
    get_circuit_breaker_registry,
    health_status_from_breaker,
)

if TYPE_CHECKING:
    from assistant.core.persona import PersonaConfig

# Module-level default scopes per design D24 (REPLACE semantics) and the
# ms-extensions spec scenario "Default scopes include People.Read and
# User.Read".
DEFAULT_SCOPES: list[str] = ["People.Read", "User.Read"]

# Effective page ceiling exposed in tool descriptions (task 9.3.3). 100
# matches the GraphClient default (graph-client / "Page Ceiling Configurable")
# so this extension has no override of its own; the value is documented in
# the tool description so agents know when they will be truncated-via-error
# rather than silently.
_PAGE_CEILING: int = 100


# ---------------------------------------------------------------------------
# Input validation helper (D23)
# ---------------------------------------------------------------------------


def _validate_path_segment(value: str, *, param_name: str) -> str:
    """Reject values that cannot safely interpolate into a Graph path.

    Path separators (``/``), backslashes, and ASCII control characters
    (``\\x00``-``\\x1f``) are rejected with :class:`ValueError` BEFORE any
    HTTP call is issued. Returns the URL-encoded form on success so
    callers can drop the result straight into a path string.

    Per the ``ms-extensions`` spec scenario "Path segment with slash is
    rejected before HTTP call" and "Path segment with control character
    is rejected".
    """
    if not isinstance(value, str):  # defensive against agent payloads
        raise ValueError(
            f"Parameter {param_name!r} must be a string; got {type(value).__name__}."
        )
    if "/" in value or "\\" in value:
        raise ValueError(
            f"Parameter {param_name!r} must not contain path separators "
            "('/' or '\\\\'); embed IDs as discrete arguments, not paths."
        )
    for ch in value:
        # Reject ASCII control chars; Unicode separators are also caught
        # (Cc category) for defence-in-depth.
        if ord(ch) < 0x20 or unicodedata.category(ch) == "Cc":
            raise ValueError(
                f"Parameter {param_name!r} contains control character "
                f"U+{ord(ch):04X}."
            )
    return urllib.parse.quote(value, safe="")


# ---------------------------------------------------------------------------
# Scope resolution (D24)
# ---------------------------------------------------------------------------


def _resolve_scopes(config: dict[str, Any]) -> list[str]:
    """REPLACE-semantics scope resolution per D24.

    - Missing ``scopes`` key → defaults.
    - Empty list ``[]`` → defaults (treats empty as "no override").
    - Populated list → entirely replaces defaults; no merge.
    """
    raw = config.get("scopes")
    if not raw:  # None or empty list → defaults
        return list(DEFAULT_SCOPES)
    return list(raw)


# ---------------------------------------------------------------------------
# OPEN-breaker error surfacing (D25)
# ---------------------------------------------------------------------------


class _FallbackGraphAPIError(Exception):
    """Local fallback for ``GraphAPIError`` until wp-foundation-impls.

    The real ``GraphAPIError`` lives in ``assistant.core.graph_client``,
    which is owned by wp-foundation-impls and may not be merged when
    this extension is exercised in isolation. Making the breaker-open
    code path require the impls package would force every extension
    test that trips the breaker to depend on impls — defeating the
    purpose of the protocols/impls split (D28). The fallback class
    carries the same fields (``status_code``, ``error_code``,
    ``request_id``, ``message``) and constructor shape as the real
    class, so callers see a consistent structured error either way.

    Real-class signature (graph-client / "Error Sanitization on
    GraphAPIError"):
        ``GraphAPIError(message, *, request=None, response=None,
                        error_code=None, request_id=None)``
    Real ``.status_code`` derives from ``response.status_code`` — or
    is ``None`` for transport-tier errors (timeout, breaker_open,
    invalid_redirect, size_exceeded).
    """

    def __init__(
        self,
        message: str,
        *,
        request: Any = None,
        response: Any = None,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.request_id = request_id
        # Mirror the real class: status_code is None for transport-tier
        # errors (no response).
        self.status_code: int | None = (
            getattr(response, "status_code", None) if response is not None else None
        )
        super().__init__(message)


def _resolve_graph_api_error() -> type[Exception]:
    """Resolve the GraphAPIError class — lazy because wp-foundation-impls
    delivers the canonical class but may not be merged yet.
    """
    try:
        from assistant.core.graph_client import GraphAPIError as _GE
    except ImportError:
        return _FallbackGraphAPIError
    return _GE


def _raise_breaker_open_error(
    extension_name: str,
    breaker_state: str,
) -> None:
    """Raise ``GraphAPIError(error_code='breaker_open')`` (D25)."""
    err_cls: Any = _resolve_graph_api_error()
    raise err_cls(
        f"Extension {extension_name!r} is unavailable: breaker open "
        f"due to recent consecutive failures (state={breaker_state}).",
        error_code="breaker_open",
    )


# ---------------------------------------------------------------------------
# MSAF tool decoration (D11) — gated behind try/except per the briefing.
# ---------------------------------------------------------------------------


try:  # pragma: no cover — exercised at import time only
    from agent_framework import ai_function as _real_ai_function  # type: ignore[attr-defined]

    def _ai_function_wrapper(name: str, description: str) -> Callable[..., Any]:
        def _decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            # Wrap in a free async function so the SDK decorator and any
            # custom attributes can attach without colliding with bound-
            # method machinery (you can't set attributes on a bound method).
            async def _async_proxy(**kwargs: Any) -> Any:
                return await fn(**kwargs)

            _async_proxy.__name__ = name.replace(".", "_")
            decorated: Callable[..., Any] = _real_ai_function(
                name=name, description=description
            )(_async_proxy)
            decorated.__ai_name__ = name  # type: ignore[attr-defined]
            decorated.__ai_description__ = description  # type: ignore[attr-defined]
            return decorated

        return _decorate

except ImportError:
    # SDK not installed — fall back to a thin wrapper that records the
    # tool name on the free callable so dual-format parity tests still
    # work. Real MSAF integration lights up when ``agent-framework`` lands.
    def _ai_function_wrapper(name: str, description: str) -> Callable[..., Any]:
        def _decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            async def _async_proxy(**kwargs: Any) -> Any:
                return await fn(**kwargs)

            _async_proxy.__name__ = name.replace(".", "_")
            _async_proxy.__ai_name__ = name  # type: ignore[attr-defined]
            _async_proxy.__ai_description__ = description  # type: ignore[attr-defined]
            return _async_proxy

        return _decorate


# ---------------------------------------------------------------------------
# LangChain args schemas
# ---------------------------------------------------------------------------


class _SearchPeopleArgs(BaseModel):
    query: str = Field(
        ..., description="Free-text search string matched against people names/emails."
    )
    top: int = Field(
        25,
        ge=1,
        le=100,
        description="Maximum number of people to return (Graph $top).",
    )


class _GetMyProfileArgs(BaseModel):
    pass


class _SearchMessagesArgs(BaseModel):
    query: str = Field(
        ..., description="Free-text search string matched against message body/subject."
    )
    top: int = Field(
        25,
        ge=1,
        le=100,
        description="Page size hint (Graph $top); pagination handles overflow.",
    )


# ---------------------------------------------------------------------------
# Extension class
# ---------------------------------------------------------------------------


class MsGraphExtension:
    """Generic Microsoft Graph tools (people search, profile, message search).

    Spec ms-extensions / "ms_graph Extension Real Implementation".
    """

    name: str = "ms_graph"

    def __init__(
        self,
        config: dict[str, Any],
        *,
        client: CloudGraphClient,
    ) -> None:
        self.config = config
        self.scopes = _resolve_scopes(config)
        self._client = client
        # Use the extension-namespaced breaker key per the modified
        # extension-registry requirement: ``extension:ms_graph`` (NOT
        # ``graph:ms_graph`` which is graph-client's transport-tier key).
        registry: CircuitBreakerRegistry = get_circuit_breaker_registry()
        self._breaker = registry.get_breaker(f"extension:{self.name}")

    # ----- Health -----

    async def health_check(self) -> HealthStatus:
        return health_status_from_breaker(
            self._breaker, key=f"extension:{self.name}"
        )

    # ----- Tool surfaces -----

    def as_langchain_tools(self) -> list[StructuredTool]:
        return [
            self._build_lc_tool(
                name="ms_graph.search_people",
                description=(
                    "Search Microsoft 365 People (the active user's relevance-"
                    "ranked contacts and colleagues). Returns a list of "
                    "person dicts. Search string is sent via Graph $search "
                    f"and never embedded in the request path. (max "
                    f"page_ceiling={_PAGE_CEILING}; raises page_ceiling_exceeded "
                    "above. Narrow your query to stay within bounds.)"
                ),
                args_schema=_SearchPeopleArgs,
                coroutine=self._search_people,
            ),
            self._build_lc_tool(
                name="ms_graph.get_my_profile",
                description=(
                    "Read the active user's Microsoft Graph profile (/me). "
                    "Returns the user dict (displayName, mail, jobTitle, "
                    "userPrincipalName, etc.). Single GET, no pagination."
                ),
                args_schema=_GetMyProfileArgs,
                coroutine=self._get_my_profile,
            ),
            self._build_lc_tool(
                name="ms_graph.search_messages",
                description=(
                    "Cross-mailbox search of the active user's messages "
                    "(/me/messages with $search). Returns a flat list of "
                    "message dicts across all paginated results. Bounded by "
                    f"<= ceil(items / page_size) Graph calls — no per-item "
                    f"fetches. (max page_ceiling={_PAGE_CEILING}; raises "
                    "page_ceiling_exceeded above. Narrow your query to stay "
                    "within bounds.)"
                ),
                args_schema=_SearchMessagesArgs,
                coroutine=self._search_messages,
            ),
        ]

    def as_ms_agent_tools(self) -> list[Callable[..., Any]]:
        # Author the MSAF wrappers in the same order as the LangChain
        # tools so dual-format parity tests can compare by index (D11).
        sp = _ai_function_wrapper(
            name="ms_graph.search_people",
            description="Search Microsoft 365 People; returns person dicts.",
        )(self._search_people)
        gp = _ai_function_wrapper(
            name="ms_graph.get_my_profile",
            description="Read the active user's /me profile.",
        )(self._get_my_profile)
        sm = _ai_function_wrapper(
            name="ms_graph.search_messages",
            description=(
                "Cross-mailbox message search via /me/messages (paginated)."
            ),
        )(self._search_messages)
        return [sp, gp, sm]

    # ----- Private canonical impls -----

    async def _search_people(self, query: str, top: int = 25) -> list[dict[str, Any]]:
        """Search the active user's People (relevance-ranked).

        Wire shape: ``GET /users?$search="<query>"&$top=<top>``. Search
        string passes through ``params=`` so httpx applies query-string
        encoding (D23).

        Pagination upper bound: <= 1 Graph call per invocation (single
        page). Larger result sets require an explicit follow-up tool call.
        """
        await self._raise_if_breaker_open()
        # Graph $search expects a quoted string — see Microsoft Graph
        # /users $search docs.
        params: dict[str, Any] = {"$search": f'"{query}"', "$top": top}
        body = await self._client.get("/users", params=params)
        value = body.get("value")
        if not isinstance(value, list):
            return []
        return value

    async def _get_my_profile(self) -> dict[str, Any]:
        """Read the active user's profile.

        Wire shape: ``GET /me``. Single call.
        """
        await self._raise_if_breaker_open()
        body = await self._client.get("/me")
        return body

    async def _search_messages(
        self, query: str, top: int = 25
    ) -> list[dict[str, Any]]:
        """Cross-mailbox message search.

        Wire shape: ``paginate(/me/messages)`` with ``$search`` in params.
        Pagination upper bound: ``<= ceil(items / page_size) + 1`` Graph
        calls; per-item fetches are forbidden (task 9.3.2).
        """
        await self._raise_if_breaker_open()
        params: dict[str, Any] = {"$search": f'"{query}"', "$top": top}
        flattened: list[dict[str, Any]] = []
        async for page in self._client.paginate("/me/messages", params=params):
            value = page.get("value")
            if isinstance(value, list):
                flattened.extend(value)
        return flattened

    # ----- Internals -----

    async def _raise_if_breaker_open(self) -> None:
        """Surface OPEN-breaker state as a structured ``GraphAPIError``.

        Per D25 / spec ms-extensions "Tool Invocation Error When Breaker
        is OPEN" — the agent receives a typed error, not a generic
        ``BreakerOpen`` exception, so the harness can render unavailability
        in a structured way.
        """
        if self._breaker.state == "open":
            _raise_breaker_open_error(self.name, self._breaker.state)

    def _build_lc_tool(
        self,
        *,
        name: str,
        description: str,
        args_schema: type[BaseModel],
        coroutine: Callable[..., Any],
    ) -> StructuredTool:
        # StructuredTool.from_function wires args_schema through Pydantic
        # validation before invoking the coroutine, so input validation
        # for typed kwargs (top: int) is free; the path-segment
        # validator (D23) covers the rest at the per-tool boundary.
        return StructuredTool.from_function(
            coroutine=coroutine,
            name=name,
            description=description,
            args_schema=args_schema,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_extension(
    config: dict[str, Any],
    *,
    persona: PersonaConfig | None = None,
    client: CloudGraphClient | None = None,
) -> MsGraphExtension:
    """Construct ``MsGraphExtension`` for production load (D26).

    Two construction modes (mirrors outlook/teams/sharepoint factory
    symmetry — all four real-extension factories share the same shape):

    1. **Production** — ``create_extension(config, persona=persona)``.
       Builds an MSAL strategy and ``GraphClient`` from the persona's
       ``auth.ms`` block. Lazy imports defer the
       ``msal_auth``/``graph_client`` dependency until persona is
       validated.
    2. **Test** — ``create_extension(config, client=mock_client)``.
       The persona-required short-circuit is skipped; the supplied
       ``CloudGraphClient`` is used directly.

    A call with neither ``persona`` nor ``client`` raises ``TypeError``
    per extension-registry / "Real factory called with persona=None
    raises actionable TypeError".
    """
    if client is not None:
        return MsGraphExtension(config, client=client)

    if persona is None:
        raise TypeError(
            "Extension 'ms_graph' requires a non-None persona argument. "
            "Real Microsoft 365 extensions cannot be constructed without "
            "auth.ms configuration on the persona — set "
            "extensions.ms_graph.enabled=true and auth.ms.flow=interactive "
            "(or client_credentials) on the persona's persona.yaml, then "
            "let PersonaRegistry.load_extensions pass persona=<the persona> "
            "into this factory. See docs/gotchas.md for the migration recipe."
        )

    # Deferred imports: these modules land in ``wp-foundation-impls``
    # which may not be merged when extension packages are being
    # implemented in parallel (per work-packages.yaml DAG).
    from assistant.core.graph_client import GraphClient
    from assistant.core.msal_auth import create_msal_strategy

    strategy = create_msal_strategy(persona)
    scopes = _resolve_scopes(config)
    real_client: CloudGraphClient = GraphClient(
        extension_name="ms_graph",
        strategy=strategy,
        scopes=scopes,
    )
    return MsGraphExtension(config, client=real_client)
