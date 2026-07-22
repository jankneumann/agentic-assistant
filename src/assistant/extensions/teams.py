"""Real ``teams`` extension implementation (P5 — wp-teams).

Replaces the P1 ``StubExtension``-returning shim with the four Teams
tools the work persona needs: ``list_chats``, ``list_channel_messages``,
``read_message`` (read), and ``post_chat_message`` (write).

Wire-shape decisions (see ``openspec/changes/ms-graph-extension``):

- D6: same class structure as the other three real extensions —
  ``__init__(config, client)`` with the ``CloudGraphClient`` injected,
  scopes resolved with REPLACE semantics (D24), private async methods
  (`_list_chats`, `_post_chat_message`, ...) compiled into
  harness-neutral ToolSpecs via ``tool_specs()`` (P17 tool-spec
  migration; replaces the D11 dual-format authoring).
- D18: ``_post_chat_message`` calls ``client.post(..., retry_safe=False)``
  because Teams chat-messages are non-idempotent — auto-replaying a 5xx
  would duplicate the message in the chat.
- D23: every interpolated ID (``team_id``, ``channel_id``, ``chat_id``,
  ``message_id``) is URL-encoded as a path segment via
  ``urllib.parse.quote(value, safe="")`` and validated for path-
  separator / control-char rejection BEFORE any HTTP call. Search
  strings (none in teams today) would pass via ``params=``, never the
  path.
- D25: when the per-extension breaker (``extension:teams``) is OPEN,
  tool invocation raises a structured error with
  ``status_code=None`` and ``error_code="breaker_open"`` so the agent
  surfaces a concrete unavailability message rather than a generic
  Python exception.
- D26: ``create_extension`` accepts a keyword-only ``persona`` and
  raises an actionable ``TypeError`` when neither ``persona`` nor a
  test ``client`` is supplied. The msal_auth + graph_client modules
  are imported lazily inside the factory so this module does not
  depend on wp-foundation-impls at import time.
"""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from assistant.core.resilience import (
    CircuitBreaker,
    HealthStatus,
    get_circuit_breaker_registry,
    health_status_from_breaker,
)
from assistant.core.toolspec import ToolSpec, tool_spec_from_model
from assistant.extensions.base import ExtensionBase

if TYPE_CHECKING:
    from assistant.core.cloud_client import CloudGraphClient
    from assistant.core.persona import PersonaConfig


# ─────────────────────────────────────────────────────────────────────
# Default scopes — REPLACE semantics (D24)
# ─────────────────────────────────────────────────────────────────────


DEFAULT_SCOPES: tuple[str, ...] = (
    "Chat.Read",
    "Chat.ReadWrite",
    "ChannelMessage.Read.All",
)


# Default page ceiling visible in tool descriptions (per task 9.3.4).
# The actual ceiling is enforced inside the GraphClient; this value
# is the documentation contract surfaced to agents.
_DEFAULT_PAGE_CEILING: int = 100


# ─────────────────────────────────────────────────────────────────────
# Input validation (D23)
# ─────────────────────────────────────────────────────────────────────


def _validate_path_segment(name: str, value: str) -> str:
    """Reject IDs with path separators / control characters / backslashes.

    Returns the URL-encoded path segment on success. Raises
    ``ValueError`` BEFORE any HTTP call so the caller's call ledger
    stays empty on rejection (see D23 / spec scenario "Path segment
    with slash is rejected before HTTP call").
    """
    if not isinstance(value, str):
        raise ValueError(
            f"teams: parameter {name!r} must be a string, "
            f"got {type(value).__name__}"
        )
    if "/" in value:
        raise ValueError(
            f"teams: parameter {name!r} must not contain '/' "
            f"(would alter the URL path structure)"
        )
    if "\\" in value:
        raise ValueError(
            f"teams: parameter {name!r} must not contain '\\\\' "
            f"(would alter the URL path structure)"
        )
    for ch in value:
        if ord(ch) < 0x20:
            raise ValueError(
                f"teams: parameter {name!r} must not contain control "
                f"characters (got 0x{ord(ch):02x})"
            )
    return urllib.parse.quote(value, safe="")


# ─────────────────────────────────────────────────────────────────────
# Structured error for OPEN-breaker (D25)
# ─────────────────────────────────────────────────────────────────────


def _raise_breaker_open() -> None:
    """Raise the structured ``GraphAPIError(error_code='breaker_open')``.

    Lazy-imports ``GraphAPIError`` from ``core.graph_client`` (delivered
    by wp-foundation-impls) so this module loads cleanly even before
    impls have merged. Falls back to a minimal local class with the
    same attribute shape if the real class is not yet importable —
    the fallback ``status_code`` is always ``None`` to match the
    transport-only-error contract D25 specifies for ``breaker_open``.
    """
    msg = (
        "teams: extension breaker open due to recent consecutive "
        "failures; refusing tool invocation until cooldown elapses"
    )
    real = _resolve_real_graph_api_error()
    if real is not None:
        # Real class signature (foundation-impls):
        # ``GraphAPIError(message, *, request, response, error_code,
        # request_id)`` — ``status_code`` is a derived property that
        # returns ``None`` automatically when ``error_code`` is in the
        # transport-only set (which includes ``"breaker_open"``).
        # mypy can't see the keyword args on the lazy-imported class so
        # we erase to ``Any`` at the call site.
        real_any: Any = real
        raise real_any(msg, error_code="breaker_open")
    raise _FallbackGraphAPIError(
        message=msg,
        error_code="breaker_open",
    )


def _resolve_real_graph_api_error() -> type[Exception] | None:
    try:
        from assistant.core.graph_client import GraphAPIError as _GE
    except ImportError:
        return None
    return _GE


class _FallbackGraphAPIError(Exception):
    """Local fallback for ``GraphAPIError`` until wp-foundation-impls.

    Carries the same structured shape that the real class will expose
    (``status_code``, ``error_code``, ``message``) so OPEN-breaker
    consumers (and tests) can assert against attributes rather than
    error message substrings. wp-integration's harmonization step is
    where the fallback drops out as dead code.
    """

    def __init__(
        self,
        *,
        message: str,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code: int | None = None  # transport-only error
        self.error_code = error_code
        self.message = message
        self.request_id = request_id
        super().__init__(message)


# ─────────────────────────────────────────────────────────────────────
# Pydantic args schemas — one per tool, drives both LangChain
# ``StructuredTool.args_schema`` and parameter validation.
# ─────────────────────────────────────────────────────────────────────


class _ListChatsArgs(BaseModel):
    top: int = Field(
        default=25,
        description="Maximum chats to fetch per page (Graph $top).",
    )


class _ListChannelMessagesArgs(BaseModel):
    team_id: str = Field(
        ...,
        description=(
            "Microsoft Graph team identifier. URL-encoded as a path "
            "segment; reject if it contains '/', '\\', or control chars."
        ),
    )
    channel_id: str = Field(
        ...,
        description=(
            "Microsoft Graph channel identifier (often shaped "
            "'19:...@thread.tacv2'). URL-encoded as a path segment."
        ),
    )
    top: int = Field(
        default=25,
        description="Maximum messages to fetch per page (Graph $top).",
    )


class _ReadMessageArgs(BaseModel):
    chat_id: str = Field(
        ...,
        description="Chat identifier; URL-encoded as a path segment.",
    )
    message_id: str = Field(
        ...,
        description="Message identifier; URL-encoded as a path segment.",
    )


class _PostChatMessageArgs(BaseModel):
    chat_id: str = Field(
        ...,
        description="Chat identifier; URL-encoded as a path segment.",
    )
    text: str = Field(
        ...,
        description=(
            "Message text to post. Sent as the `body.content` field of "
            "the Graph chatMessage payload exactly as specified by the "
            "ms-extensions spec scenario `post_chat_message POSTs to "
            "/chats/{chatId}/messages`."
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# TeamsExtension
# ─────────────────────────────────────────────────────────────────────


class TeamsExtension(ExtensionBase):
    """Real Microsoft Teams extension (P5 — replaces ``StubExtension``)."""

    name: str = "teams"

    def __init__(
        self,
        config: dict[str, Any],
        client: CloudGraphClient,
    ) -> None:
        self.config = config
        self.scopes: list[str] = _resolve_scopes(config)
        self._client = client
        self._breaker: CircuitBreaker = (
            get_circuit_breaker_registry().get_breaker(f"extension:{self.name}")
        )

    # ── Tool surface (ToolSpec — spec tool-spec / P17) ─────────────

    def tool_specs(self) -> list[ToolSpec]:
        """Return harness-neutral ToolSpecs; one per tool method.

        Per-harness adapters (``assistant.harnesses.tool_adapters``)
        render these to each harness's native shape; every rendering
        invokes the same private async method (e.g. ``_list_chats``).
        """
        source = f"extension:{self.name}"
        return [
            tool_spec_from_model(
                handler=self._list_chats,
                name="teams.list_chats",
                description=_LIST_CHATS_DESCRIPTION,
                args_model=_ListChatsArgs,
                source=source,
            ),
            tool_spec_from_model(
                handler=self._list_channel_messages,
                name="teams.list_channel_messages",
                description=_LIST_CHANNEL_MESSAGES_DESCRIPTION,
                args_model=_ListChannelMessagesArgs,
                source=source,
            ),
            tool_spec_from_model(
                handler=self._read_message,
                name="teams.read_message",
                description=_READ_MESSAGE_DESCRIPTION,
                args_model=_ReadMessageArgs,
                source=source,
            ),
            tool_spec_from_model(
                handler=self._post_chat_message,
                name="teams.post_chat_message",
                description=_POST_CHAT_MESSAGE_DESCRIPTION,
                args_model=_PostChatMessageArgs,
                source=source,
            ),
        ]

    async def health_check(self) -> HealthStatus:
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

    # ── Tool methods ───────────────────────────────────────────────

    async def _list_chats(self, top: int = 25) -> list[dict[str, Any]]:
        """List the signed-in user's chats.

        Wire shape: ``GET /me/chats?$top=N`` then chase
        ``@odata.nextLink`` via ``CloudGraphClient.paginate``. Returns
        the flattened ``value`` arrays from each page — list-tools may
        flatten because the page shape is uniform here.

        Pagination discipline (ms-extensions / "list_messages does not
        call Graph per item"): exactly one ``paginate`` call per
        invocation; no per-item ``get`` calls. Effective Graph API
        upper bound: ``ceil(items / page_size)`` calls, page_ceiling
        ``100``.
        """
        await self._raise_if_breaker_open()
        out: list[dict[str, Any]] = []
        async for page in self._client.paginate(
            "/me/chats", params={"$top": top}
        ):
            value = page.get("value")
            if isinstance(value, list):
                out.extend(value)
        return out

    async def _list_channel_messages(
        self,
        team_id: str,
        channel_id: str,
        top: int = 25,
    ) -> list[dict[str, Any]]:
        """List messages in a Teams channel.

        Wire shape: ``GET
        /teams/{team_id}/channels/{channel_id}/messages?$top=N``.
        Both IDs URL-encoded as path segments per D23. Pagination
        discipline matches ``_list_chats`` — single ``paginate``
        call, page_ceiling ``100``.
        """
        await self._raise_if_breaker_open()
        team_seg = _validate_path_segment("team_id", team_id)
        channel_seg = _validate_path_segment("channel_id", channel_id)
        path = f"/teams/{team_seg}/channels/{channel_seg}/messages"
        out: list[dict[str, Any]] = []
        async for page in self._client.paginate(path, params={"$top": top}):
            value = page.get("value")
            if isinstance(value, list):
                out.extend(value)
        return out

    async def _read_message(
        self,
        chat_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        """Read a single chat message.

        Wire shape: ``GET /chats/{chat_id}/messages/{message_id}``;
        both IDs URL-encoded as path segments (D23).
        """
        await self._raise_if_breaker_open()
        chat_seg = _validate_path_segment("chat_id", chat_id)
        msg_seg = _validate_path_segment("message_id", message_id)
        return await self._client.get(
            f"/chats/{chat_seg}/messages/{msg_seg}"
        )

    async def _post_chat_message(
        self,
        chat_id: str,
        text: str,
    ) -> dict[str, Any]:
        """Post a message into a chat (non-idempotent write).

        Wire shape: ``POST /chats/{chat_id}/messages`` with body
        ``{"body": {"content": <text>}}`` — exactly as the
        ms-extensions spec scenario "post_chat_message POSTs to
        /chats/{chatId}/messages" mandates. No ``contentType`` field
        is sent; Microsoft Graph defaults to plain text and the spec
        is the contract of record.

        D18: ``retry_safe=False`` — Teams chat messages are non-
        idempotent; auto-replaying a transient 5xx would duplicate the
        message in the chat. The breaker still records the failure so
        a flapping Teams endpoint trips the breaker after the
        configured threshold; only the resilience-layer auto-retry is
        suppressed.
        """
        await self._raise_if_breaker_open()
        chat_seg = _validate_path_segment("chat_id", chat_id)
        body = {"body": {"content": text}}
        return await self._client.post(
            f"/chats/{chat_seg}/messages",
            json=body,
            retry_safe=False,  # D18 — non-idempotent write
        )

    # ── Internal helpers ───────────────────────────────────────────

    async def _raise_if_breaker_open(self) -> None:
        """Raise ``GraphAPIError(error_code='breaker_open')`` if the
        ``extension:teams`` breaker is OPEN (D25).

        We surface a structured error eagerly (before going to the
        client) so the agent sees a concrete "extension unavailable"
        rather than the GraphClient's own ``CircuitBreakerOpenError``,
        which would be a different exception type and unfriendlier
        message. Half-open admits are deliberately allowed through —
        a probe is the whole point of half-open.
        """
        if self._breaker.state == "open":
            _raise_breaker_open()


# ─────────────────────────────────────────────────────────────────────
# Tool-description constants — declarative so tests can pin them.
# ─────────────────────────────────────────────────────────────────────


_LIST_CHATS_DESCRIPTION = (
    "List the signed-in user's Microsoft Teams chats. Returns the "
    "flattened `value` arrays across paginated responses; each item "
    "is a chat resource (id, topic, chatType, timestamps). "
    f"page_ceiling {_DEFAULT_PAGE_CEILING} — results larger than "
    "this many pages will raise GraphAPIError("
    "error_code='page_ceiling_exceeded'); narrow the query if needed."
)

_LIST_CHANNEL_MESSAGES_DESCRIPTION = (
    "List recent messages in a Teams channel by team_id + channel_id. "
    "Both IDs MUST NOT contain '/', '\\', or control characters; they "
    "are URL-encoded as path segments. Returns the flattened `value` "
    "arrays across pages. "
    f"page_ceiling {_DEFAULT_PAGE_CEILING}."
)

_READ_MESSAGE_DESCRIPTION = (
    "Read a single Teams chat message by chat_id + message_id. Both "
    "IDs MUST NOT contain '/', '\\', or control characters; they are "
    "URL-encoded as path segments."
)

_POST_CHAT_MESSAGE_DESCRIPTION = (
    "Post a plain-text message into a Teams chat (non-idempotent write). "
    "chat_id MUST NOT contain '/', '\\', or control characters; it is "
    "URL-encoded as a path segment. The resilience layer DOES NOT "
    "auto-retry this call on transient 5xx so a duplicate message is "
    "never created — the agent is responsible for confirming success "
    "from the returned message id."
)


# ─────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────


def _resolve_scopes(config: dict[str, Any]) -> list[str]:
    """REPLACE semantics (D24).

    Persona-supplied scopes entirely supersede module defaults. Empty
    list or absent key falls back to defaults. There is no merge
    mode.
    """
    if "scopes" not in config:
        return list(DEFAULT_SCOPES)
    raw = config.get("scopes")
    if not raw:  # empty list or None
        return list(DEFAULT_SCOPES)
    if not isinstance(raw, list):
        raise ValueError(
            f"teams: 'scopes' config must be a list of strings, "
            f"got {type(raw).__name__}"
        )
    return list(raw)


# ─────────────────────────────────────────────────────────────────────
# Factory (extension-registry D26)
# ─────────────────────────────────────────────────────────────────────


def create_extension(
    config: dict[str, Any],
    *,
    persona: PersonaConfig | None = None,
    client: CloudGraphClient | None = None,
) -> TeamsExtension:
    """Construct a real ``TeamsExtension``.

    Accepts two construction modes:

    1. **Production** — ``create_extension(config, persona=persona)``.
       The factory resolves the persona's ``auth.ms`` configuration,
       builds an ``MSALStrategy`` via ``create_msal_strategy(persona)``,
       and constructs a per-extension ``GraphClient(extension_name=
       'teams', strategy=...)`` to inject. ``msal_auth`` and
       ``graph_client`` are imported lazily so this module loads
       cleanly before wp-foundation-impls has merged.

    2. **Test** — ``create_extension(config, client=mock_client)``.
       The persona-required short-circuit is skipped; the supplied
       transport is used directly. This is the path every unit test
       in ``tests/test_extensions_teams.py`` takes.

    A call with neither ``persona`` nor ``client`` (the legacy
    ``create_extension(config)`` shape, used by P1 stubs) MUST raise
    ``TypeError`` per extension-registry D26 — the message points the
    operator at the persona key path so the failure is actionable
    rather than mysterious.
    """
    if client is not None:
        return TeamsExtension(config, client)

    if persona is None:
        raise TypeError(
            "Extension 'teams': real Microsoft 365 extensions require "
            "a non-None persona argument carrying auth.ms configuration. "
            "Got persona=None — set extensions.teams.enabled=true and "
            "auth.ms (tenant_id_env / client_id_env / flow) in your "
            "persona YAML, then wire the factory through "
            "PersonaRegistry.load_extensions which passes "
            "persona=<the persona> automatically. "
            "See openspec ms-graph-extension extension-registry spec "
            "(D26) for the full migration recipe."
        )

    # Lazy imports so this module does not depend on wp-foundation-impls
    # at import time; the production load path arrives only AFTER impls
    # has shipped.
    from assistant.core.graph_client import GraphClient
    from assistant.core.msal_auth import create_msal_strategy

    strategy = create_msal_strategy(persona)
    scopes = _resolve_scopes(config)
    graph_client: CloudGraphClient = GraphClient(
        extension_name="teams",
        strategy=strategy,
        scopes=scopes,
    )
    return TeamsExtension(config, graph_client)
