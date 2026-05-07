"""Tests for the real Outlook extension.

Spec coverage: ms-extensions / "outlook Extension Real Implementation"
+ all four cross-cutting requirements (URL-encoding, scope override,
breaker-open error, dual-format parity, pagination discipline) +
extension-registry / "Real factory called with persona=None raises
actionable TypeError".

Tests use ``MockGraphClient`` (the wp-foundation-protocols typed
fixture) so this work-package can land in parallel with the
foundation-impls httpx ``GraphClient`` without depending on it.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from assistant.core.resilience import (
    CircuitBreakerRegistry,
    HealthState,
    HealthStatus,
)
from tests.mocks.graph_client import MockGraphClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "graph_responses" / "outlook"
)


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a fixture JSON; the leading ``_comment`` sentinel is preserved
    in the dict but unused at runtime."""
    return json.loads((_FIXTURE_ROOT / f"{name}.json").read_text())


def _make_extension(
    config: dict[str, Any] | None = None,
    *,
    client: MockGraphClient | None = None,
) -> Any:
    """Construct an ``OutlookExtension`` directly (test path).

    Bypasses the public ``create_extension`` factory because the factory
    requires a real persona; the class itself accepts an injected
    ``CloudGraphClient`` per design D6.
    """
    from assistant.extensions.outlook import OutlookExtension

    return OutlookExtension(config or {}, client=client or MockGraphClient())


@pytest.fixture(autouse=True)
def _reset_breaker_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with a fresh breaker registry so OPEN-breaker
    tests do not leak state into the others."""
    import assistant.core.resilience as resilience_mod

    monkeypatch.setattr(resilience_mod, "_REGISTRY", CircuitBreakerRegistry())


# ---------------------------------------------------------------------------
# Tool surface (3.1) + dual-format parity
# ---------------------------------------------------------------------------


def test_as_langchain_tools_returns_six_tools() -> None:
    """Spec: ms-extensions / "Tool list includes read and write tools"."""
    ext = _make_extension()
    tools = ext.as_langchain_tools()
    names = [t.name for t in tools]
    expected = {
        "outlook.list_messages",
        "outlook.read_message",
        "outlook.search_messages",
        "outlook.send_email",
        "outlook.list_calendar_events",
        "outlook.find_free_times",
    }
    assert expected.issubset(set(names)), (
        f"missing tools: {expected - set(names)}"
    )


def test_as_ms_agent_tools_count_matches_langchain() -> None:
    """Spec: ms-extensions / "Tool counts match across formats"."""
    ext = _make_extension()
    lc_tools = ext.as_langchain_tools()
    msaf_tools = ext.as_ms_agent_tools()
    assert len(lc_tools) == len(msaf_tools)


def test_as_ms_agent_tools_names_match_by_index() -> None:
    """Spec: ms-extensions / "Tool names match by index"."""
    ext = _make_extension()
    lc_tools = ext.as_langchain_tools()
    msaf_tools = ext.as_ms_agent_tools()

    for i, lc_tool in enumerate(lc_tools):
        msaf_tool = msaf_tools[i]
        # MSAF tools are wrapped callables; the extension MUST expose a
        # readable name on each, either via __name__ or an explicit
        # attribute set by ai_function (or our fallback wrapper).
        msaf_name = (
            getattr(msaf_tool, "name", None)
            or getattr(msaf_tool, "__name__", None)
        )
        assert msaf_name == lc_tool.name


# ---------------------------------------------------------------------------
# Default scopes (REPLACE semantics — D24)
# ---------------------------------------------------------------------------


def test_default_scopes_include_mail_and_calendar() -> None:
    """Spec: ms-extensions / "Default scopes include Mail.Read,
    Mail.Send, and Calendars.Read"."""
    ext = _make_extension({})
    for required in ("Mail.Read", "Mail.Send", "Calendars.Read"):
        assert required in ext.scopes, (
            f"default scopes missing {required}: {ext.scopes!r}"
        )


def test_persona_scopes_replace_defaults_entirely() -> None:
    """Spec: ms-extensions / "Persona scopes replace defaults entirely"."""
    ext = _make_extension({"scopes": ["Mail.Read"]})
    assert ext.scopes == ["Mail.Read"]


def test_empty_persona_scopes_uses_defaults() -> None:
    """Spec: ms-extensions / "Empty persona scopes uses defaults"."""
    ext = _make_extension({"scopes": []})
    for required in ("Mail.Read", "Mail.Send", "Calendars.Read"):
        assert required in ext.scopes


def test_missing_persona_scopes_uses_defaults() -> None:
    """Spec: ms-extensions / "Missing persona scopes key uses defaults"."""
    ext = _make_extension({})
    for required in ("Mail.Read", "Mail.Send", "Calendars.Read"):
        assert required in ext.scopes


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------


def test_list_messages_calls_paginate_and_returns_value_array() -> None:
    """Spec: ms-extensions / "list_messages calls /me/messages and
    returns value array"."""
    ext = _make_extension()
    fixture = _load_fixture("list_messages")
    ext._client.next_paginate_pages = [fixture]

    result = asyncio.run(ext._list_messages(top=10))

    # Pagination yields one page; the tool flattens to the value array.
    assert isinstance(result, list)
    assert result == fixture["value"]

    # Pagination call was made on /me/messages with $top
    calls = ext._client.calls
    paginate_calls = [c for c in calls if c[0] == "paginate"]
    assert len(paginate_calls) == 1
    _method, args, kwargs = paginate_calls[0]
    assert args == ("/me/messages",)
    params = kwargs.get("params") or {}
    assert params.get("$top") == 10


def test_list_messages_pagination_does_not_call_per_item() -> None:
    """Spec: ms-extensions / "list_messages does not call Graph per item"
    (task 9.3.1).

    With 5 pages of 10 items each, the call ledger MUST be in
    ``[N_pages, N_pages + 1]`` — independent of per-page item count.
    """
    ext = _make_extension()
    pages = [
        {"value": [{"id": f"m{i}-{j}"} for j in range(10)]} for i in range(5)
    ]
    ext._client.next_paginate_pages = pages

    asyncio.run(ext._list_messages(top=50))

    calls = ext._client.calls
    # paginate is invoked once; the iteration yields N pages but the
    # extension MUST NOT issue per-item get/post calls.
    get_or_post = [c for c in calls if c[0] in ("get", "post")]
    assert get_or_post == [], (
        f"list_messages must not issue per-item get/post; got {get_or_post}"
    )


# ---------------------------------------------------------------------------
# read_message
# ---------------------------------------------------------------------------


def test_read_message_calls_me_messages_with_url_encoded_id() -> None:
    """The id is URL-encoded into the path segment per D23."""
    ext = _make_extension()
    fixture = _load_fixture("read_message")
    ext._client.next_get_response = fixture

    # Microsoft message ids contain '+', '/', '=' and similar — but our
    # validator rejects '/' so use a safe-ish synthetic id with chars
    # that need URL-encoding but are not separators.
    msg_id = "AAMkAGI+padding=="
    result = asyncio.run(ext._read_message(message_id=msg_id))
    assert result == fixture

    calls = ext._client.calls
    get_calls = [c for c in calls if c[0] == "get"]
    assert len(get_calls) == 1
    _method, args, _kwargs = get_calls[0]
    path = args[0]
    # Encoded form: '+' → '%2B', '=' → '%3D'
    assert "%2B" in path or "AAMkAGI" in path
    assert "%3D" in path
    # Original unsafe characters MUST NOT appear unencoded.
    assert "+" not in path
    assert "==" not in path


def test_read_message_rejects_path_separator() -> None:
    """Spec: ms-extensions / "Path segment with slash is rejected before
    HTTP call"."""
    ext = _make_extension()

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(ext._read_message(message_id="a/b"))
    assert "message_id" in str(exc_info.value)

    # No HTTP call must have been issued.
    assert ext._client.calls == []


def test_read_message_rejects_control_character() -> None:
    """Spec: ms-extensions / "Path segment with control character is
    rejected"."""
    ext = _make_extension()

    with pytest.raises(ValueError):
        asyncio.run(ext._read_message(message_id="abc\x00def"))
    with pytest.raises(ValueError):
        asyncio.run(ext._read_message(message_id="abc\x1fdef"))

    assert ext._client.calls == []


def test_read_message_rejects_backslash() -> None:
    ext = _make_extension()

    with pytest.raises(ValueError):
        asyncio.run(ext._read_message(message_id="abc\\def"))
    assert ext._client.calls == []


# ---------------------------------------------------------------------------
# search_messages
# ---------------------------------------------------------------------------


def test_search_messages_passes_query_via_params_not_path() -> None:
    """Spec: ms-extensions / "Search string is passed via params, not
    path"."""
    ext = _make_extension()
    fixture = _load_fixture("search_messages")
    ext._client.next_paginate_pages = [fixture]

    asyncio.run(ext._search_messages(query="finance & metrics", top=25))

    calls = ext._client.calls
    paginate_calls = [c for c in calls if c[0] == "paginate"]
    assert len(paginate_calls) == 1
    _method, args, kwargs = paginate_calls[0]
    path = args[0]
    # Query MUST NOT appear inside the path string.
    assert "finance" not in path
    assert "metrics" not in path
    # Query MUST be carried in params.
    params = kwargs.get("params") or {}
    assert params.get("$search") == '"finance & metrics"' or params.get(
        "$search"
    ) == "finance & metrics"


# ---------------------------------------------------------------------------
# send_email — D18 retry_safe=False is critical
# ---------------------------------------------------------------------------


def test_send_email_post_body_shape() -> None:
    """Spec: ms-extensions / "send_email POSTs to /me/sendMail with the
    expected body shape"."""
    ext = _make_extension()
    ext._client.next_post_response = {}

    asyncio.run(
        ext._send_email(
            to="recipient@example.invalid",
            subject="hi",
            body="hello",
        )
    )

    calls = ext._client.calls
    post_calls = [c for c in calls if c[0] == "post"]
    assert len(post_calls) == 1
    _method, args, kwargs = post_calls[0]
    assert args == ("/me/sendMail",)

    body = kwargs.get("json")
    assert body is not None
    # Microsoft Graph sendMail body shape:
    # {"message": {"subject": ..., "body": {"contentType": "Text",
    #                                       "content": ...},
    #              "toRecipients": [{"emailAddress": {"address": ...}}]}}
    message = body["message"]
    assert message["subject"] == "hi"
    assert message["body"]["contentType"] == "Text"
    assert message["body"]["content"] == "hello"
    recipients = message["toRecipients"]
    assert isinstance(recipients, list)
    assert len(recipients) == 1
    assert recipients[0]["emailAddress"]["address"] == "recipient@example.invalid"


def test_send_email_passes_retry_safe_false() -> None:
    """Spec: graph-client / "retry_safe=False bypasses P9 retry"
    (consumer side, D18). MUST be False on send_email so transient 5xx
    can never duplicate the message."""
    ext = _make_extension()
    ext._client.next_post_response = {}

    asyncio.run(
        ext._send_email(
            to="recipient@example.invalid",
            subject="hi",
            body="hello",
        )
    )

    calls = ext._client.calls
    post_calls = [c for c in calls if c[0] == "post"]
    assert len(post_calls) == 1
    _method, _args, kwargs = post_calls[0]
    assert kwargs.get("retry_safe") is False, (
        f"send_email MUST pass retry_safe=False to prevent duplicates "
        f"on transient 5xx; got kwargs={kwargs}"
    )


def test_other_post_tools_use_default_retry_safe_true() -> None:
    """Idempotent operations (find_free_times) MUST rely on the default
    retry_safe=True so transient 5xx auto-retries succeed."""
    ext = _make_extension()
    ext._client.next_post_response = _load_fixture("find_free_times")

    asyncio.run(
        ext._find_free_times(
            start="2026-05-07T09:00:00",
            end="2026-05-07T17:00:00",
            attendees=["fixture-attendee-1@example.invalid"],
        )
    )

    calls = ext._client.calls
    post_calls = [c for c in calls if c[0] == "post"]
    assert len(post_calls) == 1
    _method, _args, kwargs = post_calls[0]
    # Default value of retry_safe is True; the extension should not pass
    # retry_safe explicitly OR pass True. Either is acceptable.
    rs = kwargs.get("retry_safe", True)
    assert rs is True


# ---------------------------------------------------------------------------
# list_calendar_events
# ---------------------------------------------------------------------------


def test_list_calendar_events_calls_me_events() -> None:
    ext = _make_extension()
    fixture = _load_fixture("list_calendar_events")
    ext._client.next_paginate_pages = [fixture]

    result = asyncio.run(ext._list_calendar_events(top=10))
    assert result == fixture["value"]

    calls = ext._client.calls
    paginate_calls = [c for c in calls if c[0] == "paginate"]
    assert len(paginate_calls) == 1
    _method, args, kwargs = paginate_calls[0]
    assert args == ("/me/events",)
    params = kwargs.get("params") or {}
    assert params.get("$top") == 10


# ---------------------------------------------------------------------------
# find_free_times
# ---------------------------------------------------------------------------


def test_find_free_times_posts_to_findMeetingTimes() -> None:
    ext = _make_extension()
    fixture = _load_fixture("find_free_times")
    ext._client.next_post_response = fixture

    result = asyncio.run(
        ext._find_free_times(
            start="2026-05-07T09:00:00",
            end="2026-05-07T17:00:00",
            attendees=["fixture-attendee-1@example.invalid"],
        )
    )
    # Returned dict should equal the fixture (the tool returns the raw
    # Microsoft Graph findMeetingTimes response).
    assert result == fixture

    calls = ext._client.calls
    post_calls = [c for c in calls if c[0] == "post"]
    assert len(post_calls) == 1
    _method, args, kwargs = post_calls[0]
    assert args == ("/me/findMeetingTimes",)
    body = kwargs.get("json")
    assert body is not None
    # Body shape per Microsoft Graph: meetingDuration/timeConstraint/etc.
    # The exact body shape is implementation-defined; we just assert the
    # critical attendee plumbing went through.
    assert "attendees" in body or "meetingDuration" in body


# ---------------------------------------------------------------------------
# Health check (D9)
# ---------------------------------------------------------------------------


def test_health_check_returns_health_status_ok_when_breaker_closed() -> None:
    """Spec: ms-extensions / "Real extension reports OK when breaker is
    CLOSED"."""
    ext = _make_extension()

    status = asyncio.run(ext.health_check())
    assert isinstance(status, HealthStatus)
    assert status.state is HealthState.OK
    assert status.breaker_key == "extension:outlook"


def test_health_check_returns_unavailable_when_breaker_open() -> None:
    """Spec: ms-extensions / "Real extension reports UNAVAILABLE when
    breaker is OPEN"."""
    ext = _make_extension()

    # Trip the breaker by recording enough consecutive failures.
    breaker = ext._breaker
    for _ in range(breaker._failure_threshold):
        asyncio.run(breaker.record_failure("synthetic failure"))
    assert breaker.state == "open"

    status = asyncio.run(ext.health_check())
    assert status.state is HealthState.UNAVAILABLE
    assert status.breaker_key == "extension:outlook"


# ---------------------------------------------------------------------------
# OPEN breaker → structured GraphAPIError on tool invocation (D25)
# ---------------------------------------------------------------------------


def _trip_breaker(ext: Any) -> None:
    breaker = ext._breaker
    for _ in range(breaker._failure_threshold):
        asyncio.run(breaker.record_failure("synthetic failure"))
    assert breaker.state == "open"


def test_tool_invocation_with_open_breaker_raises_structured_error() -> None:
    """Spec: ms-extensions / "Tool invocation with OPEN breaker raises
    structured error" (D25).

    The extension's in-module ``_GraphAPIErrorSurrogate`` is named
    ``GraphAPIError`` and carries the ``status_code``/``error_code``
    contract surface, so we assert by ``__class__.__name__`` rather
    than by ``isinstance`` — this keeps the test agnostic to whether
    wp-foundation-impls has landed (canonical class) or not
    (surrogate).
    """
    ext = _make_extension()
    _trip_breaker(ext)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(ext._list_messages(top=10))

    err = exc_info.value
    assert err.__class__.__name__ == "GraphAPIError", (
        f"expected GraphAPIError-named exception, got "
        f"{type(err).__name__}: {err!r}"
    )
    assert getattr(err, "status_code", "missing") is None
    assert getattr(err, "error_code", None) == "breaker_open"
    assert "outlook" in str(err)


# ---------------------------------------------------------------------------
# Factory contract — D26 + persona=None TypeError
# ---------------------------------------------------------------------------


def test_factory_persona_none_raises_actionable_typeerror() -> None:
    """Spec: extension-registry / "Real factory called with persona=None
    raises actionable TypeError"."""
    from assistant.extensions.outlook import create_extension

    with pytest.raises(TypeError) as exc_info:
        create_extension({})  # persona defaults to None

    msg = str(exc_info.value)
    # Must identify the offending extension name.
    assert "outlook" in msg
    # Must cite the persona YAML key path so the operator can fix.
    assert "auth.ms" in msg
    # Must mention extensions.<name> path.
    assert "extensions.outlook" in msg or "extensions" in msg


def test_factory_persona_explicit_none_raises_actionable_typeerror() -> None:
    from assistant.extensions.outlook import create_extension

    with pytest.raises(TypeError):
        create_extension({}, persona=None)


# ---------------------------------------------------------------------------
# Module export sanity
# ---------------------------------------------------------------------------


def test_outlook_module_exports_create_extension_and_class() -> None:
    mod = importlib.import_module("assistant.extensions.outlook")
    assert callable(mod.create_extension)
    assert hasattr(mod, "OutlookExtension")
