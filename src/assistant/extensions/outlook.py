"""Real Outlook extension — Microsoft Graph mail + calendar tools.

Replaces the P1 11-line stub. Exposes six tools (four read, two write):
``list_messages``, ``read_message``, ``search_messages``, ``send_email``,
``list_calendar_events``, ``find_free_times``.

Design references:

- D6  — extension internal structure (private async tool methods,
  dual-format wrappers, injected ``CloudGraphClient``).
- D9  — error handling boundaries (lazy import of ``GraphAPIError``).
- D11 — tool format conversion is per-extension (LangChain twin and
  MSAF twin both call the same private async method).
- D18 — per-method retry safety control. ``_send_email`` MUST pass
  ``retry_safe=False`` to ``client.post`` so a transient 5xx never
  duplicates the message.
- D23 — tool input URL-encoding and validation
  (``_validate_path_segment``; same name across outlook/teams/sharepoint
  for cognitive consistency, though signatures differ slightly per
  extension).
- D24 — scope override semantics: REPLACE.
- D25 — OPEN-breaker tool invocation raises
  ``GraphAPIError(error_code="breaker_open")``.
- D26 — factory contract: ``create_extension(config, *, persona)`` and
  ``persona=None`` raises actionable ``TypeError`` before any MSAL or
  GraphClient construction is attempted.

Spec: ms-extensions / "outlook Extension Real Implementation" plus the
four cross-cutting requirements (URL-encoding, scope override,
breaker-open error, dual-format parity).
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from assistant.core.cloud_client import CloudGraphClient
from assistant.core.resilience import (
    HealthStatus,
    get_circuit_breaker_registry,
    health_status_from_breaker,
)

if TYPE_CHECKING:  # pragma: no cover — typing only
    from assistant.core.persona import PersonaConfig

# ---------------------------------------------------------------------------
# Defaults (D24 — REPLACE semantics)
# ---------------------------------------------------------------------------

#: Module-level default scopes; ``persona.extensions.outlook.config.scopes``
#: REPLACES this list entirely (D24). An empty list or absent key falls
#: back to defaults.
DEFAULT_SCOPES: tuple[str, ...] = (
    "Mail.Read",
    "Mail.Send",
    "Calendars.Read",
)

#: Per-tool effective page ceiling. Documented in StructuredTool
#: descriptions per task 9.3.4 so agents know when results may be
#: truncated.
DEFAULT_PAGE_CEILING: int = 100


# ---------------------------------------------------------------------------
# Input validation (D23)
# ---------------------------------------------------------------------------


def _validate_path_segment(value: str, *, parameter: str) -> str:
    """Validate and URL-encode a single Graph API path segment.

    Rejects values containing ``/``, ``\\``, or ASCII control chars
    (``\\x00``-``\\x1f`` plus ``\\x7f``) before any HTTP call. Returns
    the URL-encoded form for safe interpolation into a path.

    Per ms-extensions spec / "Tool Input URL-Encoding and Validation"
    and design D23.
    """
    if not isinstance(value, str):
        raise ValueError(
            f"{parameter}: expected str, got {type(value).__name__}"
        )
    if "/" in value:
        raise ValueError(
            f"{parameter}: path separator '/' is not permitted in id "
            "(it would split the Graph path); reject inputs that look "
            "like paths"
        )
    if "\\" in value:
        raise ValueError(
            f"{parameter}: backslash is not permitted in id"
        )
    for ch in value:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValueError(
                f"{parameter}: control characters are not permitted in id "
                f"(found 0x{ord(ch):02x})"
            )
    return urllib.parse.quote(value, safe="")


# ---------------------------------------------------------------------------
# Scope resolution (D24 — REPLACE semantics)
# ---------------------------------------------------------------------------


def _resolve_scopes(config: dict[str, Any]) -> list[str]:
    """Apply REPLACE semantics to ``config['scopes']``.

    - Persona-provided non-empty list ⇒ use it verbatim.
    - Empty list OR missing key ⇒ use ``DEFAULT_SCOPES``.
    """
    raw = config.get("scopes")
    if raw is None:
        return list(DEFAULT_SCOPES)
    if not isinstance(raw, list):
        raise ValueError(
            f"outlook: scopes must be a list[str]; got {type(raw).__name__}"
        )
    if len(raw) == 0:
        return list(DEFAULT_SCOPES)
    return list(raw)


# ---------------------------------------------------------------------------
# Lazy GraphAPIError — wp-foundation-impls owns the canonical class
# ---------------------------------------------------------------------------


class _GraphAPIErrorSurrogate(Exception):
    """Local fallback used until ``core/graph_client.py`` lands in
    wp-foundation-impls.

    The class name is forced to ``GraphAPIError`` (see ``__name__``
    reassignment below) so consumers that ``except GraphAPIError`` or
    inspect ``__name__`` see a coherent error surface during the
    parallel-execution window where wp-outlook lands before
    wp-foundation-impls. Once the canonical class lands, the lazy
    import switches over and this surrogate is unused.

    Constructor signature mirrors the sibling extensions' surrogates so
    cross-extension test ordering does not matter: positional message,
    kw-only ``status_code``/``error_code``/``request_id``.
    """

    def __init__(
        self,
        message: str = "",
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


def _get_graph_api_error_cls() -> type[BaseException]:
    """Resolve ``GraphAPIError`` lazily.

    Returns the canonical ``GraphAPIError`` from
    ``assistant.core.graph_client`` if available; otherwise the local
    surrogate. Per design D9 (extension-side error mapping) and the
    parallel-package landing window where wp-outlook may land before
    wp-foundation-impls.
    """
    try:
        from assistant.core.graph_client import GraphAPIError
    except ImportError:
        return _GraphAPIErrorSurrogate
    return GraphAPIError


# ---------------------------------------------------------------------------
# Breaker-open guard (D25) — wraps each tool method
# ---------------------------------------------------------------------------


def _raise_breaker_open(extension_name: str) -> BaseException:
    """Construct a ``GraphAPIError(error_code="breaker_open")`` (D25).

    Resolves the error class lazily so the surrogate is used until
    wp-foundation-impls lands the canonical class. The canonical class
    derives ``status_code`` from its response (None for transport-only
    error codes including ``breaker_open``); the surrogate simply
    initializes ``status_code=None`` directly. We pass only ``message``
    and ``error_code`` so the call is compatible with both shapes.
    """
    cls: Any = _get_graph_api_error_cls()
    return cls(
        f"{extension_name}: breaker open due to recent consecutive "
        "failures; tool invocation refused until cooldown elapses",
        error_code="breaker_open",
    )


def _guard_open_breaker(
    fn: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Decorate a private tool method so an OPEN breaker raises a
    structured ``GraphAPIError(error_code="breaker_open")`` per D25.

    The breaker-state probe is non-blocking: we read the publicly
    exposed ``state`` property without awaiting any lock, since this
    decorator is on the synchronous fast-path before the tool's HTTP
    call is even attempted.
    """

    @wraps(fn)
    async def _wrapped(self: OutlookExtension, *args: Any, **kwargs: Any) -> Any:
        if self._breaker.state == "open":
            raise _raise_breaker_open(self.name)
        return await fn(self, *args, **kwargs)

    return _wrapped


# ---------------------------------------------------------------------------
# MSAF tool wrapper (D11)
# ---------------------------------------------------------------------------


def _msaf_tool(
    name: str, coroutine: Callable[..., Awaitable[Any]]
) -> Callable[..., Awaitable[Any]]:
    """Wrap a coroutine for ``as_ms_agent_tools`` consumption.

    When the ``agent-framework`` SDK is installed (wp-foundation-impls
    adds it via pyproject), ``ai_function`` decorates the coroutine with
    the SDK-required metadata so the MSAF harness can register the tool
    by name. When the SDK is NOT installed (parallel-execution window
    where wp-outlook lands before wp-foundation-impls), we fall back to
    a thin wrapper that exposes the same ``name``/``__name__`` surface
    that ``as_langchain_tools()`` exposes; the dual-format parity test
    still passes, and the MSAF harness will simply re-decorate the
    coroutines once it imports them — but only if the SDK is present.

    Lazy import so ``import assistant.extensions.outlook`` does not
    raise ``ModuleNotFoundError`` when ``agent-framework`` is absent.
    """
    try:  # pragma: no cover — exercised once SDK lands
        # ``agent_framework`` may be installed without ``ai_function``
        # exposed at top-level (early SDK versions); use ``getattr`` so
        # the fall-through path runs cleanly in either case.
        import agent_framework  # type: ignore[import-not-found,unused-ignore]

        ai_function = agent_framework.ai_function  # type: ignore[attr-defined]
        decorated = ai_function(name=name)(coroutine)
        # Preserve a readable ``name`` attribute for the parity test.
        try:
            decorated.name = name
        except (AttributeError, TypeError):
            pass
        return decorated
    except (ImportError, AttributeError):
        # SDK not installed yet; expose a thin name-bearing async
        # wrapper. This wrapper is what MSAF would call; once the SDK
        # is installed, ``as_ms_agent_tools()`` returns the
        # ``ai_function``-decorated form on next process start.
        @wraps(coroutine)
        async def _wrapper(*args: Any, **kwargs: Any) -> Any:
            return await coroutine(*args, **kwargs)

        # Override __name__ so dual-format parity by index works.
        _wrapper.__name__ = name
        try:
            _wrapper.name = name  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            pass
        return _wrapper


# ---------------------------------------------------------------------------
# LangChain args-schemas (one per tool)
# ---------------------------------------------------------------------------


class _ListMessagesArgs(BaseModel):
    top: int = Field(
        25,
        description="Maximum number of messages to return per page.",
    )


class _ReadMessageArgs(BaseModel):
    message_id: str = Field(
        ..., description="Microsoft Graph message id (URL-encoded if needed)."
    )


class _SearchMessagesArgs(BaseModel):
    query: str = Field(
        ..., description="Free-text search; passed via $search parameter."
    )
    top: int = Field(
        25, description="Maximum number of messages to return per page."
    )


class _SendEmailArgs(BaseModel):
    to: list[str] = Field(
        ...,
        description=(
            "Recipient email addresses. Per ms-extensions spec scenario "
            "'send_email POSTs to /me/sendMail with the expected body "
            "shape', this is a list — pass `[\"a@b.com\"]` for a single "
            "recipient. Each address becomes one `toRecipients[].address` "
            "entry in the Graph payload."
        ),
    )
    subject: str = Field(..., description="Email subject line.")
    body: str = Field(..., description="Plain-text email body.")


class _ListCalendarEventsArgs(BaseModel):
    top: int = Field(
        25, description="Maximum number of events to return per page."
    )


class _FindFreeTimesArgs(BaseModel):
    start: str = Field(
        ..., description="ISO8601 start of the time window to search."
    )
    end: str = Field(
        ..., description="ISO8601 end of the time window to search."
    )
    attendees: list[str] = Field(
        default_factory=list,
        description="Attendee email addresses (required attendees).",
    )


# ---------------------------------------------------------------------------
# OutlookExtension
# ---------------------------------------------------------------------------


class OutlookExtension:
    """Real Outlook (Microsoft Graph) extension.

    Constructed with a config dict and an injected ``CloudGraphClient``
    per D6; the class is transport-agnostic so tests can pass
    ``MockGraphClient`` and production wires the real
    ``GraphClient`` from wp-foundation-impls.
    """

    name: str = "outlook"

    def __init__(
        self,
        config: dict[str, Any],
        *,
        client: CloudGraphClient,
    ) -> None:
        self.config = config
        self.scopes: list[str] = _resolve_scopes(config)
        self._client: CloudGraphClient = client
        # Per-extension breaker namespace (D4-style). Note this is the
        # extension-level breaker (key ``extension:outlook``), NOT the
        # transport-level breaker (``graph:outlook``); they are
        # separate per design.
        self._breaker = get_circuit_breaker_registry().get_breaker(
            f"extension:{self.name}"
        )

    # ----- LangChain tool surface ------------------------------------

    def as_langchain_tools(self) -> list[StructuredTool]:
        """Return six ``StructuredTool``s, one per tool method."""
        return [
            StructuredTool.from_function(
                coroutine=self._list_messages,
                name="outlook.list_messages",
                description=(
                    "List recent messages from the user's mailbox "
                    f"(/me/messages). page_ceiling={DEFAULT_PAGE_CEILING}; "
                    "results larger than this raise "
                    "GraphAPIError(error_code=\"page_ceiling_exceeded\"); "
                    "narrow the query if you need more."
                ),
                args_schema=_ListMessagesArgs,
            ),
            StructuredTool.from_function(
                coroutine=self._read_message,
                name="outlook.read_message",
                description=(
                    "Read a single message by id (/me/messages/{id})."
                ),
                args_schema=_ReadMessageArgs,
            ),
            StructuredTool.from_function(
                coroutine=self._search_messages,
                name="outlook.search_messages",
                description=(
                    "Search the user's mailbox via $search "
                    f"(/me/messages). page_ceiling={DEFAULT_PAGE_CEILING}; "
                    "results larger than this raise "
                    "GraphAPIError(error_code=\"page_ceiling_exceeded\")."
                ),
                args_schema=_SearchMessagesArgs,
            ),
            StructuredTool.from_function(
                coroutine=self._send_email,
                name="outlook.send_email",
                description=(
                    "Send an email via Microsoft Graph (/me/sendMail). "
                    "Non-idempotent — retry-safe disabled to prevent "
                    "duplicates on transient 5xx."
                ),
                args_schema=_SendEmailArgs,
            ),
            StructuredTool.from_function(
                coroutine=self._list_calendar_events,
                name="outlook.list_calendar_events",
                description=(
                    "List the user's calendar events (/me/events). "
                    f"page_ceiling={DEFAULT_PAGE_CEILING}; results "
                    "larger than this raise GraphAPIError"
                    "(error_code=\"page_ceiling_exceeded\")."
                ),
                args_schema=_ListCalendarEventsArgs,
            ),
            StructuredTool.from_function(
                coroutine=self._find_free_times,
                name="outlook.find_free_times",
                description=(
                    "Find common free time across attendees "
                    "(/me/findMeetingTimes)."
                ),
                args_schema=_FindFreeTimesArgs,
            ),
        ]

    # ----- MSAF tool surface (D11) -----------------------------------

    def as_ms_agent_tools(self) -> list[Callable[..., Awaitable[Any]]]:
        """Return MSAF-compatible callables.

        Each callable bears the same canonical name as its LangChain
        twin (``outlook.<verb>``) so harness consumers see identical
        tool surfaces — see ms-extensions / "Tool counts match across
        formats" and "Tool names match by index".
        """
        return [
            _msaf_tool("outlook.list_messages", self._list_messages),
            _msaf_tool("outlook.read_message", self._read_message),
            _msaf_tool("outlook.search_messages", self._search_messages),
            _msaf_tool("outlook.send_email", self._send_email),
            _msaf_tool(
                "outlook.list_calendar_events", self._list_calendar_events
            ),
            _msaf_tool("outlook.find_free_times", self._find_free_times),
        ]

    # ----- Health (extension-registry / "Real extension derives ...") --

    async def health_check(self) -> HealthStatus:
        return health_status_from_breaker(
            self._breaker, key=f"extension:{self.name}"
        )

    # ─────────────────────────────────────────────────────────────────
    # Private tool methods — single canonical implementation per D11.
    # Both LangChain and MSAF wrappers call the same coroutine.
    # ─────────────────────────────────────────────────────────────────

    @_guard_open_breaker
    async def _list_messages(self, top: int = 25) -> list[dict[str, Any]]:
        """List recent messages.

        Pagination discipline (task 9.3.1): exactly one ``paginate``
        call; never per-item ``get``. Upper bound on Graph API calls is
        ``ceil(items / page_size)`` — strictly the page count.
        """
        items: list[dict[str, Any]] = []
        async for page in self._client.paginate(
            "/me/messages",
            params={"$top": top},
        ):
            items.extend(page.get("value", []))
        return items

    @_guard_open_breaker
    async def _read_message(self, message_id: str) -> dict[str, Any]:
        """Read a single message by id."""
        encoded = _validate_path_segment(message_id, parameter="message_id")
        return await self._client.get(f"/me/messages/{encoded}")

    @_guard_open_breaker
    async def _search_messages(
        self, query: str, top: int = 25
    ) -> list[dict[str, Any]]:
        """Search the mailbox via ``$search``.

        Per D23, the query is passed via ``params=`` so httpx applies
        query-string encoding correctly; it is never interpolated into
        the path.

        Microsoft Graph's ``$search`` requires the query to be wrapped
        in double quotes when it contains spaces or special characters.
        """
        # Always wrap in double quotes for consistency with Graph's
        # $search semantics.
        wrapped = f'"{query}"'
        items: list[dict[str, Any]] = []
        async for page in self._client.paginate(
            "/me/messages",
            params={"$search": wrapped, "$top": top},
        ):
            items.extend(page.get("value", []))
        return items

    @_guard_open_breaker
    async def _send_email(
        self, to: list[str], subject: str, body: str
    ) -> dict[str, Any]:
        """Send an email via ``/me/sendMail``.

        ``to`` is a list of recipient addresses per ms-extensions spec
        scenario "send_email POSTs to /me/sendMail with the expected
        body shape" — each entry becomes one ``toRecipients[]`` element.

        D18 (per-method retry safety): ``retry_safe=False`` is passed to
        ``client.post`` so the resilience layer does NOT auto-retry on
        transient 5xx — Microsoft Graph has no idempotency-key protocol
        for ``sendMail``, so an auto-retry would duplicate the message.
        """
        if not to:
            raise ValueError(
                "outlook.send_email: `to` must contain at least one "
                "recipient address"
            )
        message_body: dict[str, Any] = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body,
                },
                "toRecipients": [
                    {"emailAddress": {"address": addr}} for addr in to
                ],
            },
        }
        return await self._client.post(
            "/me/sendMail",
            json=message_body,
            retry_safe=False,
        )

    @_guard_open_breaker
    async def _list_calendar_events(
        self, top: int = 25
    ) -> list[dict[str, Any]]:
        """List calendar events.

        Pagination discipline matches ``_list_messages``: one paginate
        call, no per-item fetches.
        """
        items: list[dict[str, Any]] = []
        async for page in self._client.paginate(
            "/me/events",
            params={"$top": top},
        ):
            items.extend(page.get("value", []))
        return items

    @_guard_open_breaker
    async def _find_free_times(
        self, start: str, end: str, attendees: list[str]
    ) -> dict[str, Any]:
        """Find common free time across attendees via
        ``/me/findMeetingTimes``.

        This is a POST on Graph but it is idempotent (the same input
        always returns the same suggestions, modulo calendar mutations)
        so we DO NOT pass ``retry_safe=False`` — transient 5xx may safely
        retry.
        """
        body: dict[str, Any] = {
            "attendees": [
                {
                    "type": "Required",
                    "emailAddress": {"address": addr},
                }
                for addr in attendees
            ],
            "timeConstraint": {
                "timeslots": [
                    {
                        "start": {"dateTime": start, "timeZone": "UTC"},
                        "end": {"dateTime": end, "timeZone": "UTC"},
                    },
                ],
            },
            "meetingDuration": "PT30M",
        }
        return await self._client.post("/me/findMeetingTimes", json=body)


# ---------------------------------------------------------------------------
# Factory (D26)
# ---------------------------------------------------------------------------


def create_extension(
    config: dict[str, Any],
    *,
    persona: PersonaConfig | None = None,
    client: CloudGraphClient | None = None,
) -> OutlookExtension:
    """Construct an ``OutlookExtension`` for the given persona.

    Two construction modes (mirrors teams.create_extension symmetry —
    the four real-extension factories all accept the same shape):

    1. **Production** — ``create_extension(config, persona=persona)``.
       Builds an MSAL strategy and ``GraphClient`` from the persona's
       ``auth.ms`` block. Lazy imports defer the
       ``msal_auth``/``graph_client`` dependency until persona is
       validated (so module import stays cheap even before
       wp-foundation-impls lands).
    2. **Test** — ``create_extension(config, client=mock_client)``.
       The persona-required short-circuit is skipped; the supplied
       ``CloudGraphClient`` is used directly.

    Per extension-registry / "Real factory called with persona=None
    raises actionable TypeError" (D26): a call with neither
    ``persona`` nor ``client`` raises ``TypeError`` with the persona
    YAML key path so the operator can fix the persona config.
    """
    if client is not None:
        return OutlookExtension(config, client=client)

    if persona is None:
        raise TypeError(
            "outlook: real extension requires a non-None `persona` argument; "
            "configure auth.ms in the persona YAML and ensure "
            "extensions.outlook is enabled. See docs/gotchas.md for the "
            "migration recipe."
        )

    # Deferred imports — both modules live in wp-foundation-impls, which
    # may land after wp-outlook in parallel execution. Lazy import keeps
    # ``import assistant.extensions.outlook`` cheap and free of hard
    # cross-package dependencies at module-load time.
    from assistant.core.graph_client import GraphClient
    from assistant.core.msal_auth import create_msal_strategy

    strategy = create_msal_strategy(persona)
    scopes = _resolve_scopes(config)
    real_client = GraphClient(
        extension_name="outlook",
        strategy=strategy,
        scopes=scopes,
    )
    return OutlookExtension(config, client=real_client)
