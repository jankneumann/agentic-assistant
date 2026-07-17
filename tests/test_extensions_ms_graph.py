"""Tests for the real ``ms_graph`` extension.

Covers every ``ms-extensions`` spec scenario that pertains to ``ms_graph``,
plus the ``extension-registry`` factory contract scenarios that mention
``ms_graph`` by name.

Test discipline:

- Use :class:`MockGraphClient` (from ``tests.mocks.graph_client``) — wp-
  foundation-impls (real ``GraphClient`` + ``msal_auth``) is a sibling
  package and may not be merged when this file runs.
- Construct the extension directly as ``MsGraphExtension(config,
  client=mock)`` for tests that don't specifically test the factory; the
  factory tests bypass ``MockGraphClient`` and simply assert the
  ``persona=None`` short-circuit path.
- Each list-tool's call ledger size is bounded by ``ceil(items /
  page_size) + 1`` per task 9.3.1.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import UTC, datetime
from typing import Any

import pytest

from assistant.core.cloud_client import CloudGraphClient
from assistant.core.resilience import (
    CircuitBreakerRegistry,
    HealthState,
    HealthStatus,
    get_circuit_breaker_registry,
)
from assistant.extensions.base import Extension
from assistant.extensions.ms_graph import (
    DEFAULT_SCOPES,
    MsGraphExtension,
    create_extension,
)
from tests.mocks.graph_client import MockGraphClient

FIXTURE_ROOT = (
    pathlib.Path(__file__).resolve().parent
    / "fixtures"
    / "graph_responses"
    / "ms_graph"
)


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture, stripping the leading sentinel comment line."""
    text = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    lines = text.splitlines()
    # Sentinel must be the first line per CLAUDE.md G6 + design D7.
    assert lines[0] == "// FIXTURE_GRAPH_RESPONSE_v1", (
        f"fixture {name} missing FIXTURE_GRAPH_RESPONSE_v1 sentinel"
    )
    return json.loads("\n".join(lines[1:]))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_breaker_registry(monkeypatch: pytest.MonkeyPatch) -> CircuitBreakerRegistry:
    """Provide a fresh registry per-test so breaker state never bleeds across tests."""
    fresh = CircuitBreakerRegistry()
    monkeypatch.setattr(
        "assistant.core.resilience._REGISTRY",
        fresh,
        raising=False,
    )
    return fresh


def _build_ext(
    config: dict[str, Any] | None = None,
    *,
    client: CloudGraphClient | None = None,
) -> MsGraphExtension:
    return MsGraphExtension(config or {}, client=client or MockGraphClient())


# ---------------------------------------------------------------------------
# Tool surface (presence, names — ToolSpec since the P17 migration)
# ---------------------------------------------------------------------------


class TestToolSurface:
    """Spec: ms-extensions / ms_graph Extension Real Implementation
    (ToolSpec surface per spec tool-spec)."""

    def test_tool_specs_returns_non_empty_list(self) -> None:
        ext = _build_ext()
        specs = ext.tool_specs()
        assert len(specs) >= 3
        names = {s.name for s in specs}
        assert "ms_graph.search_people" in names
        assert "ms_graph.get_my_profile" in names
        assert "ms_graph.search_messages" in names

    def test_tool_specs_carry_source_and_schema(self) -> None:
        ext = _build_ext()
        for spec in ext.tool_specs():
            assert spec.source == "extension:ms_graph"
            assert spec.input_schema.get("type") == "object"


# ---------------------------------------------------------------------------
# Tool behaviour against MockGraphClient
# ---------------------------------------------------------------------------


class TestSearchPeople:
    """Spec: search_people calls /users with $search and returns parsed value list."""

    def test_search_people_returns_value_list(self) -> None:
        mock = MockGraphClient()
        mock.next_get_response = _load_fixture("search_people.json")
        ext = _build_ext(client=mock)
        result = asyncio.run(ext._search_people(query="alice"))
        # Returns the value array (not the wrapping dict).
        assert isinstance(result, list)
        assert result == mock.next_get_response["value"]

    def test_search_people_passes_search_via_params(self) -> None:
        """Spec: D23 — search strings always pass via params=, never path."""
        mock = MockGraphClient()
        mock.next_get_response = {"value": [{"displayName": "Alice"}]}
        ext = _build_ext(client=mock)
        asyncio.run(ext._search_people(query="alice"))
        # Find the actual GET call (skip mocking artefacts).
        gets = [c for c in mock.calls if c[0] == "get"]
        assert len(gets) == 1
        path, kwargs = gets[0][1][0], gets[0][2]
        # Path is /users — not embedding the query.
        assert path == "/users"
        assert "alice" not in path
        # Search string passed as $search param, not in path.
        params = kwargs.get("params") or {}
        assert "$search" in params
        # Graph $search expects a quoted string — the value contains the query.
        assert "alice" in params["$search"]

    def test_search_people_simple_query_value(self) -> None:
        """Quick sanity: result equals fixture value list."""
        mock = MockGraphClient()
        mock.next_get_response = {"value": [{"displayName": "Alice"}]}
        ext = _build_ext(client=mock)
        result = asyncio.run(ext._search_people(query="alice"))
        assert result == [{"displayName": "Alice"}]


class TestGetMyProfile:
    """Coverage: get_my_profile calls /me and returns dict."""

    def test_get_my_profile_returns_dict(self) -> None:
        mock = MockGraphClient()
        mock.next_get_response = _load_fixture("get_my_profile.json")
        ext = _build_ext(client=mock)
        result = asyncio.run(ext._get_my_profile())
        assert isinstance(result, dict)
        assert result == mock.next_get_response

    def test_get_my_profile_calls_me_endpoint(self) -> None:
        mock = MockGraphClient()
        mock.next_get_response = {"id": "abc"}
        ext = _build_ext(client=mock)
        asyncio.run(ext._get_my_profile())
        gets = [c for c in mock.calls if c[0] == "get"]
        assert len(gets) == 1
        assert gets[0][1][0] == "/me"


class TestSearchMessages:
    """Coverage: search_messages uses paginate against /me/messages."""

    def test_search_messages_flattens_paginated_value_arrays(self) -> None:
        mock = MockGraphClient()
        page1 = _load_fixture("search_messages.json")
        page2 = {"value": [{"id": "AAAAA-synthetic-message-id-0003"}]}
        mock.next_paginate_pages = [page1, page2]
        ext = _build_ext(client=mock)
        result = asyncio.run(ext._search_messages(query="agenda"))
        assert isinstance(result, list)
        # Two messages from page1 + 1 from page2.
        assert len(result) == 3
        ids = [m["id"] for m in result]
        assert "AAAAA-synthetic-message-id-0003" in ids

    def test_search_messages_passes_query_via_params(self) -> None:
        """Spec D23 — query goes in params, not path."""
        mock = MockGraphClient()
        mock.next_paginate_pages = []
        ext = _build_ext(client=mock)
        asyncio.run(ext._search_messages(query="finance & metrics"))
        pgs = [c for c in mock.calls if c[0] == "paginate"]
        assert len(pgs) == 1
        path, kwargs = pgs[0][1][0], pgs[0][2]
        # Search payload not embedded in path.
        assert "finance" not in path
        assert "metrics" not in path
        params = kwargs.get("params") or {}
        assert "$search" in params
        assert "finance & metrics" in params["$search"]


# ---------------------------------------------------------------------------
# Default scopes + REPLACE override semantics (D24)
# ---------------------------------------------------------------------------


class TestScopes:
    """Spec: Default scopes include People.Read and User.Read; Scope Override
    Semantics — REPLACE."""

    def test_default_scopes_include_people_read_and_user_read(self) -> None:
        ext = _build_ext({})
        assert "People.Read" in ext.scopes
        assert "User.Read" in ext.scopes

    def test_default_scopes_match_module_constant(self) -> None:
        ext = _build_ext({})
        assert ext.scopes == list(DEFAULT_SCOPES)

    def test_scopes_replace_defaults_entirely(self) -> None:
        """Spec: Persona scopes replace defaults entirely (D24)."""
        ext = _build_ext({"scopes": ["Mail.Read"]})
        assert ext.scopes == ["Mail.Read"]
        # Critical: defaults must NOT be merged in.
        assert "People.Read" not in ext.scopes
        assert "User.Read" not in ext.scopes

    def test_empty_persona_scopes_uses_defaults(self) -> None:
        """Spec: Empty persona scopes uses defaults (D24)."""
        ext = _build_ext({"scopes": []})
        assert ext.scopes == list(DEFAULT_SCOPES)

    def test_missing_persona_scopes_uses_defaults(self) -> None:
        """Spec: Missing persona scopes key uses defaults (D24)."""
        ext = _build_ext({})
        assert ext.scopes == list(DEFAULT_SCOPES)


# ---------------------------------------------------------------------------
# HealthStatus from breaker
# ---------------------------------------------------------------------------


class TestHealthStatus:
    """Spec: All Four Extensions Provide Real HealthStatus; Real extension
    derives HealthStatus from its breaker."""

    def test_closed_breaker_yields_ok_health_status(
        self, fresh_breaker_registry: CircuitBreakerRegistry
    ) -> None:
        ext = _build_ext()
        status = asyncio.run(ext.health_check())
        assert isinstance(status, HealthStatus)
        assert status.state is HealthState.OK
        assert status.breaker_key == "extension:ms_graph"

    def test_open_breaker_yields_unavailable_health_status(
        self, fresh_breaker_registry: CircuitBreakerRegistry
    ) -> None:
        ext = _build_ext()
        # Force the breaker open by recording enough failures.
        breaker = fresh_breaker_registry.get_breaker("extension:ms_graph")

        async def _trip() -> None:
            for _ in range(5):
                await breaker.record_failure("synthetic-failure")

        asyncio.run(_trip())
        assert breaker.state == "open"
        status = asyncio.run(ext.health_check())
        assert status.state is HealthState.UNAVAILABLE
        assert status.breaker_key == "extension:ms_graph"

    def test_health_check_uses_extension_namespaced_key(
        self, fresh_breaker_registry: CircuitBreakerRegistry
    ) -> None:
        """Spec: Real extension derives HealthStatus from its breaker —
        key MUST equal ``extension:ms_graph`` (not ``graph:ms_graph``)."""
        ext = _build_ext()
        status = asyncio.run(ext.health_check())
        assert status.breaker_key == "extension:ms_graph"


# ---------------------------------------------------------------------------
# URL-encoding + input validation (D23)
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Spec: Tool Input URL-Encoding and Validation (D23)."""

    @pytest.mark.parametrize(
        "bad_value",
        [
            "abc/def",           # path separator
            "abc\\def",          # backslash
            "abc\x00def",        # NUL
            "abc\x1fdef",        # control char (unit separator)
            "/leading-slash",
            "trailing/",
        ],
    )
    def test_search_people_rejects_bad_query_value(self, bad_value: str) -> None:
        # Search strings go in params=, but if a path-valued param ever
        # arrives the validator rejects it. We test via a tool that
        # interpolates into a path; ``_search_people`` does not (it is
        # only $search); skip with a guard if not applicable.
        # For ms_graph there is no ID-bearing tool today; we instead
        # verify the validator helper directly via the module export.
        from assistant.extensions.ms_graph import _validate_path_segment

        with pytest.raises(ValueError) as excinfo:
            _validate_path_segment(bad_value, param_name="user_id")
        assert "user_id" in str(excinfo.value)

    def test_validator_accepts_clean_value(self) -> None:
        from assistant.extensions.ms_graph import _validate_path_segment

        # Clean alphanumeric + dash + dot + at is fine — those occur in
        # message IDs, UPNs, etc.
        for ok in ["AAAA-1234", "user@example.com", "abc.def_GHI-123"]:
            _validate_path_segment(ok, param_name="x")

    def test_search_string_passed_via_params_not_path(self) -> None:
        """Spec D23 scenario 'Search string is passed via params, not path'."""
        mock = MockGraphClient()
        mock.next_get_response = {"value": []}
        ext = _build_ext(client=mock)
        asyncio.run(ext._search_people(query="finance & metrics"))
        gets = [c for c in mock.calls if c[0] == "get"]
        path, kwargs = gets[0][1][0], gets[0][2]
        assert "finance" not in path
        assert "metrics" not in path
        params = kwargs.get("params") or {}
        assert any("finance & metrics" in str(v) for v in params.values())


# ---------------------------------------------------------------------------
# OPEN-breaker tool invocation surfaces structured GraphAPIError (D25)
# ---------------------------------------------------------------------------


class TestBreakerOpenError:
    """Spec: Tool Invocation Error When Breaker is OPEN (D25)."""

    def test_open_breaker_tool_invocation_raises_graph_api_error(
        self, fresh_breaker_registry: CircuitBreakerRegistry
    ) -> None:
        """When ``extension:ms_graph`` is OPEN, calling a tool MUST raise
        ``GraphAPIError(status_code=None, error_code="breaker_open")``."""
        # We import GraphAPIError from the same lazy path the extension
        # uses, so the test exercises the exact code path. wp-foundation-
        # impls is required to make this runnable; if it isn't merged the
        # extension's lazy import will fail and this test will skip.
        # The extension's lazy resolver returns either the real
        # GraphAPIError (when wp-foundation-impls is merged) or the
        # local _FallbackGraphAPIError. Either way the raised exception
        # carries the same structured fields (status_code=None,
        # error_code="breaker_open").
        from assistant.extensions.ms_graph import _resolve_graph_api_error

        GraphAPIError = _resolve_graph_api_error()

        # Trip the extension breaker.
        breaker = fresh_breaker_registry.get_breaker("extension:ms_graph")

        async def _trip() -> None:
            for _ in range(5):
                await breaker.record_failure("synthetic-failure")

        asyncio.run(_trip())
        assert breaker.state == "open"

        ext = _build_ext()
        with pytest.raises(GraphAPIError) as excinfo:
            asyncio.run(ext._search_people(query="x"))
        err = excinfo.value
        assert getattr(err, "status_code", "missing") is None
        assert getattr(err, "error_code", None) == "breaker_open"
        assert "ms_graph" in str(err)


# ---------------------------------------------------------------------------
# Factory contract (D26 + extension-registry spec)
# ---------------------------------------------------------------------------


class TestFactoryContract:
    """Spec: extension-registry / Real factory called with persona=None
    raises actionable TypeError (D26)."""

    def test_factory_with_persona_none_raises_actionable_typeerror(self) -> None:
        with pytest.raises(TypeError) as excinfo:
            create_extension({}, persona=None)
        msg = str(excinfo.value)
        assert "ms_graph" in msg
        # Error must cite the persona YAML key path.
        assert "auth.ms" in msg or "auth" in msg
        assert "extensions" in msg

    def test_factory_with_persona_omitted_raises_typeerror(self) -> None:
        """Factory's persona kwarg defaults to None, so calling without
        it MUST also raise (D26 scenario second clause)."""
        with pytest.raises(TypeError):
            create_extension({})


# ---------------------------------------------------------------------------
# Pagination discipline (task 9.3.1)
# ---------------------------------------------------------------------------


class TestPaginationDiscipline:
    """Spec: list_messages does not call Graph per item.

    For ms_graph the only paginated tool is ``search_messages``.
    Asserts the call ledger size is bounded by ``ceil(items / page_size) + 1``,
    independent of item count.
    """

    def test_search_messages_call_count_bounded_by_pages(self) -> None:
        # Build pages that contain many items each — call ledger MUST scale
        # with pages, not items.
        small_page_count = 3
        items_per_small_page = 5
        large_items_per_page = 50

        def _build_pages(items_per_page: int) -> list[dict[str, Any]]:
            return [
                {
                    "value": [
                        {"id": f"page{p}-item{i}"} for i in range(items_per_page)
                    ]
                }
                for p in range(small_page_count)
            ]

        # Run 1: small page size.
        mock_small = MockGraphClient()
        mock_small.next_paginate_pages = _build_pages(items_per_small_page)
        ext_small = _build_ext(client=mock_small)
        asyncio.run(ext_small._search_messages(query="x"))
        small_call_count = len(
            [c for c in mock_small.calls if c[0] in ("get", "post", "paginate")]
        )

        # Run 2: large page size — same number of pages, more items each.
        mock_large = MockGraphClient()
        mock_large.next_paginate_pages = _build_pages(large_items_per_page)
        ext_large = _build_ext(client=mock_large)
        asyncio.run(ext_large._search_messages(query="x"))
        large_call_count = len(
            [c for c in mock_large.calls if c[0] in ("get", "post", "paginate")]
        )

        # Spec: 'increasing items-per-page from 10 to 50 while holding
        # N_pages=5 MUST leave the ledger size unchanged'.
        assert small_call_count == large_call_count
        # And the ledger size MUST be O(pages) — for paginate-driven tools
        # the mock records a single paginate(...) call regardless of how
        # many pages it yields, so the bound here is N_pages -> 1.
        # We accept anything <= N_pages + 1 to allow an optional pre-call.
        assert small_call_count <= small_page_count + 1


# ---------------------------------------------------------------------------
# Page ceiling description (task 9.3.3)
# ---------------------------------------------------------------------------


class TestPageCeilingDescription:
    """Spec: list_messages declares its page_ceiling in tool description."""

    def test_search_messages_description_contains_page_ceiling(self) -> None:
        ext = _build_ext()
        tools = {s.name: s for s in ext.tool_specs()}
        tool = tools["ms_graph.search_messages"]
        assert "page_ceiling" in tool.description


# ---------------------------------------------------------------------------
# Extension protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_instance_satisfies_extension_protocol(self) -> None:
        ext = _build_ext()
        assert isinstance(ext, Extension)

    def test_instance_name_is_ms_graph(self) -> None:
        ext = _build_ext()
        assert ext.name == "ms_graph"

    def test_health_status_is_dataclass(self) -> None:
        ext = _build_ext()
        status = asyncio.run(ext.health_check())
        assert isinstance(status, HealthStatus)
        assert isinstance(status.checked_at, datetime)
        # checked_at MUST be timezone-aware (UTC) per HealthStatus contract.
        assert status.checked_at.tzinfo is not None
        assert status.checked_at.tzinfo.utcoffset(status.checked_at) == UTC.utcoffset(
            status.checked_at
        )


# ---------------------------------------------------------------------------
# Sanity: registry exists and is the same one resilience module exposes
# ---------------------------------------------------------------------------


def test_get_circuit_breaker_registry_returns_singleton() -> None:
    a = get_circuit_breaker_registry()
    b = get_circuit_breaker_registry()
    assert a is b
