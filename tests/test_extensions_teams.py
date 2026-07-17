"""Tests for the real ``teams`` extension (wp-teams).

Covers every teams scenario in the ms-extensions spec:

- Tool surface (read + write, dual-format parity).
- Method-level wire shape against ``MockGraphClient`` (paths, params,
  ID URL-encoding).
- ``post_chat_message`` body shape AND ``retry_safe=False`` (D18 — the
  load-bearing assertion that the non-idempotent write never auto-
  retries on transient 5xx, which would otherwise duplicate Teams
  messages).
- Default scopes ``Chat.Read``, ``Chat.ReadWrite``,
  ``ChannelMessage.Read.All`` plus REPLACE override semantics (D24).
- ``HealthStatus`` derivation from the per-extension breaker (P9 +
  ms-extensions "Real extension reports..." scenarios).
- URL-encoding + input validation (D23).
- OPEN-breaker raising ``GraphAPIError(error_code="breaker_open")``
  (D25).
- Factory ``persona=None`` raising actionable ``TypeError``
  (extension-registry D26 / spec scenario "Real factory called with
  persona=None raises actionable TypeError").
- Pagination discipline — list-tools issue at most ``N_pages + 1``
  GraphClient calls regardless of items per page (ms-extensions
  "list_messages does not call Graph per item" applied to
  ``teams.list_chats`` / ``teams.list_channel_messages``).
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from assistant.core.toolspec import ToolSpec

from assistant.core.cloud_client import CloudGraphClient
from assistant.core.resilience import (
    HealthState,
    HealthStatus,
    get_circuit_breaker_registry,
)
from assistant.extensions import teams as teams_module
from assistant.extensions.base import Extension
from assistant.extensions.teams import (
    DEFAULT_SCOPES,
    TeamsExtension,
    create_extension,
)
from tests.mocks.graph_client import MockGraphClient

# ── Helpers ──────────────────────────────────────────────────────────


def _build(
    config: dict[str, Any] | None = None,
    *,
    client: CloudGraphClient | None = None,
) -> TeamsExtension:
    """Construct a ``TeamsExtension`` against a mock client.

    Bypasses the production msal+graph_client wiring by passing
    ``client=...`` directly into the factory; the persona-required
    short-circuit only fires when neither ``client`` nor ``persona`` is
    supplied (per design D26 / extension-registry spec).
    """
    return create_extension(config or {}, client=client or MockGraphClient())


def _reset_registry() -> None:
    """Drop all breakers so each test starts CLOSED.

    The breaker registry is a process-wide singleton; without a reset
    between tests, a prior test that drove ``extension:teams`` into
    OPEN would poison subsequent ``health_check`` / OPEN-tool tests.
    """
    registry = get_circuit_breaker_registry()
    registry._breakers.clear()


@pytest.fixture(autouse=True)
def _autoreset_breakers() -> None:
    _reset_registry()


# ── Tool surface (extension-registry / "ms_graph/teams/sharepoint/
#    outlook no longer return empty tool lists" applied to teams)─────


def test_extension_satisfies_protocol() -> None:
    ext = _build()
    assert isinstance(ext, Extension)


def test_tool_specs_includes_read_and_write_tools() -> None:
    """ms-extensions / "Tool list includes read and write tools" (teams)."""
    ext = _build()
    specs = ext.tool_specs()
    names = {s.name for s in specs}
    expected = {
        "teams.list_chats",
        "teams.list_channel_messages",
        "teams.read_message",
        "teams.post_chat_message",
    }
    assert expected.issubset(names), (
        f"missing teams tool(s): {expected - names}"
    )
    for spec in specs:
        assert isinstance(spec, ToolSpec)


def test_tool_specs_carry_source_and_json_schema() -> None:
    """Every spec carries provenance + a JSON-Schema object surface
    (P17 tool-spec migration — replaces the D11 dual-format parity)."""
    ext = _build()
    specs = ext.tool_specs()
    assert len(specs) >= 4, "expected at least 4 tools"
    for spec in specs:
        assert callable(spec.handler)
        assert spec.source == "extension:teams"
        assert spec.input_schema.get("type") == "object"


# ── list_chats ───────────────────────────────────────────────────────


def test_list_chats_calls_me_chats_and_returns_value_array() -> None:
    """ms-extensions / "list_chats calls /me/chats and returns value array"."""
    mock = MockGraphClient()
    mock.next_paginate_pages = [{"value": [{"id": "c1"}, {"id": "c2"}]}]
    ext = _build(client=mock)

    result = asyncio.run(ext._list_chats(top=25))

    assert result == [{"id": "c1"}, {"id": "c2"}]
    # paginate is the call that was issued (list-tools paginate by
    # default — pagination discipline below ensures the call ledger
    # stays bounded).
    paginate_calls = [c for c in mock.calls if c[0] == "paginate"]
    assert len(paginate_calls) == 1
    _name, args, kwargs = paginate_calls[0]
    assert args == ("/me/chats",)
    assert kwargs["params"] == {"$top": 25}


def test_list_chats_pagination_discipline() -> None:
    """ms-extensions / "list_messages does not call Graph per item"
    applied to ``teams.list_chats``.

    The call ledger size MUST be bounded by the number of pages, NOT by
    the number of items per page.
    """
    mock = MockGraphClient()
    # Five pages, each with ten chats — N_pages = 5, items = 50.
    mock.next_paginate_pages = [
        {"value": [{"id": f"c{p}_{i}"} for i in range(10)]}
        for p in range(5)
    ]
    ext = _build(client=mock)

    asyncio.run(ext._list_chats(top=25))

    # Discipline: a single paginate call regardless of items-per-page.
    # The ledger must NOT scale with the number of items returned.
    non_paginate = [c for c in mock.calls if c[0] not in ("paginate",)]
    assert non_paginate == [], (
        f"list_chats issued per-item Graph calls: {non_paginate!r}"
    )


def test_list_channel_messages_url_encodes_team_and_channel_ids() -> None:
    """D23 — both ``team_id`` and ``channel_id`` are interpolated into
    the path and MUST be URL-encoded as path segments."""
    mock = MockGraphClient()
    mock.next_paginate_pages = [{"value": [{"id": "m1"}]}]
    ext = _build(client=mock)

    # ``19:abc%def`` and ``id with space`` are realistic Teams id
    # shapes that must round-trip safely through ``quote(safe="")``.
    asyncio.run(ext._list_channel_messages(
        team_id="19:abc%def",
        channel_id="id with space",
    ))

    paginate_calls = [c for c in mock.calls if c[0] == "paginate"]
    assert len(paginate_calls) == 1
    path = paginate_calls[0][1][0]
    # Both ids URL-encoded as path segments.
    assert path == (
        "/teams/19%3Aabc%25def/channels/id%20with%20space/messages"
    ), f"unexpected path: {path!r}"


def test_read_message_url_encodes_chat_id_and_message_id() -> None:
    """D23 — ``chat_id`` and ``message_id`` URL-encoded into the path."""
    mock = MockGraphClient()
    mock.next_get_response = {"id": "m1", "body": {"content": "hi"}}
    ext = _build(client=mock)

    result = asyncio.run(ext._read_message(
        chat_id="19:c@thread.v2",
        message_id="abc=def",
    ))

    assert result == {"id": "m1", "body": {"content": "hi"}}
    get_calls = [c for c in mock.calls if c[0] == "get"]
    assert len(get_calls) == 1
    path = get_calls[0][1][0]
    assert path == "/chats/19%3Ac%40thread.v2/messages/abc%3Ddef"


# ── post_chat_message — body shape AND retry_safe=False ──────────────


def test_post_chat_message_body_shape() -> None:
    """ms-extensions / "post_chat_message POSTs to
    /chats/{chatId}/messages".

    The spec scenario mandates the body equals exactly
    ``{"body": {"content": "hello"}}`` and the parameter is named
    ``text``. No ``contentType`` field — Microsoft Graph defaults to
    plain text for chatMessage posts and the spec is the contract.
    """
    mock = MockGraphClient()
    mock.next_post_response = {"id": "msg-123"}
    ext = _build(client=mock)

    result = asyncio.run(ext._post_chat_message(
        chat_id="c1",
        text="hello",
    ))

    assert result == {"id": "msg-123"}

    post_calls = [c for c in mock.calls if c[0] == "post"]
    assert len(post_calls) == 1
    _name, args, kwargs = post_calls[0]
    assert args == ("/chats/c1/messages",)
    assert kwargs["json"] == {"body": {"content": "hello"}}


def test_post_chat_message_passes_retry_safe_false() -> None:
    """D18 — ``post_chat_message`` is non-idempotent and MUST pass
    ``retry_safe=False`` so transient 5xx never auto-retries (which
    would duplicate Teams messages).

    The MockGraphClient call ledger captures the ``retry_safe`` kwarg
    so we can assert this end-to-end.
    """
    mock = MockGraphClient()
    mock.next_post_response = {"id": "msg-1"}
    ext = _build(client=mock)

    asyncio.run(ext._post_chat_message(chat_id="c1", text="hi"))

    post_calls = [c for c in mock.calls if c[0] == "post"]
    assert len(post_calls) == 1
    _path, _args, kwargs = post_calls[0]
    assert kwargs["retry_safe"] is False, (
        "teams.post_chat_message MUST pass retry_safe=False per D18 — "
        f"actual kwargs={kwargs!r}"
    )


def test_post_chat_message_url_encodes_chat_id() -> None:
    """D23 — ``chat_id`` URL-encoded in the POST path."""
    mock = MockGraphClient()
    mock.next_post_response = {}
    ext = _build(client=mock)

    asyncio.run(ext._post_chat_message(
        chat_id="19:c@thread.v2",
        text="hello",
    ))

    post_calls = [c for c in mock.calls if c[0] == "post"]
    path = post_calls[0][1][0]
    assert path == "/chats/19%3Ac%40thread.v2/messages"


# ── Input validation (D23) ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("_list_channel_messages",
         {"team_id": "a/b", "channel_id": "c"}),
        ("_list_channel_messages",
         {"team_id": "a", "channel_id": "c\\d"}),
        ("_list_channel_messages",
         {"team_id": "a", "channel_id": "c\x00d"}),
        ("_read_message", {"chat_id": "c/d", "message_id": "m"}),
        ("_read_message", {"chat_id": "c", "message_id": "m\x1f"}),
        ("_post_chat_message", {"chat_id": "c\\d", "text": "x"}),
    ],
)
def test_invalid_path_segment_raises_value_error_before_http_call(
    method: str,
    kwargs: dict[str, Any],
) -> None:
    """D23 — IDs containing ``/``, ``\\``, or control chars MUST raise
    ``ValueError`` before any HTTP call is made.
    """
    mock = MockGraphClient()
    ext = _build(client=mock)
    fn = getattr(ext, method)

    with pytest.raises(ValueError):
        asyncio.run(fn(**kwargs))

    # No GET / POST / paginate must have occurred — the validation
    # gate is BEFORE the wire call.
    wire_calls = [
        c for c in mock.calls
        if c[0] in {"get", "post", "paginate", "get_bytes"}
    ]
    assert wire_calls == [], (
        "invalid input must be rejected before any GraphClient call; "
        f"got wire calls: {wire_calls!r}"
    )


# ── Default scopes + REPLACE override semantics ──────────────────────


def test_default_scopes_include_chat_and_channel_message_scopes() -> None:
    """ms-extensions / "Default scopes include Chat.Read,
    Chat.ReadWrite, ChannelMessage.Read.All"."""
    ext = _build()
    assert "Chat.Read" in ext.scopes
    assert "Chat.ReadWrite" in ext.scopes
    assert "ChannelMessage.Read.All" in ext.scopes


def test_persona_scope_override_replaces_defaults_entirely() -> None:
    """ms-extensions / "Persona scopes replace defaults entirely"
    (D24 — REPLACE semantics)."""
    ext = _build({"scopes": ["Chat.Read"]})
    assert ext.scopes == ["Chat.Read"], (
        "REPLACE semantics: persona-supplied scopes MUST entirely "
        f"supersede module defaults; got {ext.scopes!r}"
    )


def test_empty_persona_scopes_uses_defaults() -> None:
    """ms-extensions / "Empty persona scopes uses defaults" (D24)."""
    ext = _build({"scopes": []})
    assert ext.scopes == list(DEFAULT_SCOPES)


def test_missing_persona_scopes_uses_defaults() -> None:
    """ms-extensions / "Missing persona scopes key uses defaults" (D24)."""
    ext = _build({})  # no ``scopes`` key
    assert ext.scopes == list(DEFAULT_SCOPES)


# ── HealthStatus derivation ──────────────────────────────────────────


def test_health_check_reports_ok_when_breaker_closed() -> None:
    """ms-extensions / "Real extension reports OK when breaker is
    CLOSED"."""
    ext = _build()
    status = asyncio.run(ext.health_check())
    assert isinstance(status, HealthStatus)
    assert status.state is HealthState.OK
    assert status.breaker_key == "extension:teams"


def test_health_check_reports_unavailable_when_breaker_open() -> None:
    """ms-extensions / "Real extension reports UNAVAILABLE when
    breaker is OPEN"."""
    registry = get_circuit_breaker_registry()
    breaker = registry.get_breaker("extension:teams")

    async def _drive() -> HealthStatus:
        # Five consecutive failures opens the breaker per default
        # P9 thresholds.
        for _ in range(5):
            await breaker.record_failure("synthetic")
        ext = _build()
        return await ext.health_check()

    status = asyncio.run(_drive())
    assert status.state is HealthState.UNAVAILABLE
    assert status.breaker_key == "extension:teams"


# ── OPEN-breaker tool invocation (D25) ───────────────────────────────


def test_tool_invocation_with_open_breaker_raises_structured_error() -> None:
    """ms-extensions / "Tool invocation with OPEN breaker raises
    structured error".

    The error MUST be a ``GraphAPIError`` (or compatible structured
    error) with ``status_code=None`` and
    ``error_code="breaker_open"``, and the message MUST identify the
    extension by name.
    """
    registry = get_circuit_breaker_registry()
    breaker = registry.get_breaker("extension:teams")

    async def _drive() -> Exception:
        for _ in range(5):
            await breaker.record_failure("synthetic")
        ext = _build()
        try:
            await ext._list_chats()
        except Exception as exc:
            return exc
        raise AssertionError(
            "list_chats with OPEN breaker MUST raise"
        )

    err = asyncio.run(_drive())
    assert getattr(err, "status_code", "missing") is None, (
        f"expected status_code=None, got {getattr(err, 'status_code', '?')!r}"
    )
    assert getattr(err, "error_code", None) == "breaker_open", (
        f"expected error_code='breaker_open', got "
        f"{getattr(err, 'error_code', None)!r}"
    )
    assert "teams" in str(err)


# ── Factory contract (extension-registry D26) ────────────────────────


def test_factory_persona_none_raises_actionable_typeerror() -> None:
    """extension-registry / "Real factory called with persona=None
    raises actionable TypeError"."""
    with pytest.raises(TypeError) as exc_info:
        create_extension({}, persona=None)
    msg = str(exc_info.value)
    assert "teams" in msg, "error MUST identify the offending extension"
    assert "extensions.teams" in msg or "extensions.<name>" in msg
    assert "auth.ms" in msg or "auth" in msg, (
        "error MUST cite the auth.ms persona key path"
    )


def test_factory_omitting_persona_raises_typeerror() -> None:
    """``persona`` defaults to ``None`` per the Protocol — calling
    without supplying ``persona`` AND without ``client`` MUST raise.
    """
    with pytest.raises(TypeError):
        create_extension({})


def test_factory_with_client_kwarg_skips_persona_check() -> None:
    """Test path: ``client=mock_client`` constructs the extension
    without requiring a persona. Without this escape hatch the four
    extensions could not be unit-tested.
    """
    ext = create_extension({}, client=MockGraphClient())
    assert isinstance(ext, TeamsExtension)


def test_module_provides_create_extension_function() -> None:
    """extension-registry / "Each remaining stub exports
    create_extension" — applies to the real teams extension too."""
    assert callable(teams_module.create_extension)


def test_factory_signature_accepts_persona_keyword() -> None:
    """extension-registry D26 — factory accepts ``*, persona`` kwarg."""
    sig = inspect.signature(create_extension)
    assert "persona" in sig.parameters
    assert sig.parameters["persona"].kind == inspect.Parameter.KEYWORD_ONLY


# ── Name / scopes attribute exposure ─────────────────────────────────


def test_extension_name_is_teams() -> None:
    ext = _build()
    assert ext.name == "teams"


def test_scopes_are_a_list() -> None:
    ext = _build({"scopes": ["X.Read"]})
    assert isinstance(ext.scopes, list)
    assert ext.scopes == ["X.Read"]
