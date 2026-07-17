"""Tests for the real ``sharepoint`` extension (P5 wp-sharepoint).

Covers every sharepoint scenario in the ms-extensions and
extension-registry deltas of the ``ms-graph-extension`` change:

- Tool surface — read-only (no write tools), correct names, dual format
  parity (LangChain + MSAF) (D6, D11)
- Method behavior against ``MockGraphClient`` (search_sites,
  list_documents, download_document via ``get_bytes``)
- Default scopes (``Sites.Read.All``, ``Files.Read.All``) (D24)
- Scope override REPLACE semantics (D24)
- HealthStatus derivation from per-extension breaker (D6)
- URL-encoding + input validation for path-segment IDs (D23)
- Structured ``GraphAPIError(error_code="breaker_open")`` when breaker
  is OPEN (D25)
- Factory ``persona=None`` short-circuit raises actionable
  ``TypeError`` (D26)
- Pagination discipline — list_documents call ledger bounded by pages,
  not items (ms-extensions / Pagination Discipline)

The download_document tests use ``mock.next_get_bytes_metadata`` so the
test asserts the metadata dict round-trips through the extension —
matching D19 (binary download streams to a tempfile; raw bytes never
enter agent context).
"""

from __future__ import annotations

import json
from importlib import import_module, reload
from pathlib import Path
from typing import Any

import pytest

from assistant.core.resilience import (
    CircuitBreakerRegistry,
    HealthState,
    get_circuit_breaker_registry,
)
from tests.mocks.graph_client import MockGraphClient

FIXTURES = Path(__file__).parent / "fixtures" / "graph_responses" / "sharepoint"


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture, stripping the leading sentinel comment."""
    raw = (FIXTURES / name).read_text()
    # Strip the leading ``// FIXTURE_GRAPH_RESPONSE_v1`` line that the
    # privacy guard requires on every fixture in this tree.
    body = "\n".join(
        line for line in raw.splitlines() if not line.startswith("//")
    )
    return json.loads(body)


@pytest.fixture(autouse=True)
def _reset_breaker_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets a fresh ``CircuitBreakerRegistry`` so OPEN/CLOSED state
    set by one test does not leak into another's HealthStatus assertions."""
    fresh = CircuitBreakerRegistry()
    monkeypatch.setattr(
        "assistant.core.resilience._REGISTRY", fresh, raising=False
    )
    # Force the module-level singleton accessor to pick the fresh instance.
    # ``get_circuit_breaker_registry`` reads the global, so monkeypatching
    # ``_REGISTRY`` is enough.
    _ = get_circuit_breaker_registry()
    # Also reload the sharepoint module so its module-level
    # CircuitBreakerRegistry references stay coherent in case the module
    # caches the registry (it shouldn't, but defensive).


# ── Module import + factory ──────────────────────────────────────────


def _import_sharepoint() -> Any:
    """Import (or reload) the sharepoint extension module fresh per test."""
    mod = import_module("assistant.extensions.sharepoint")
    return reload(mod)


def _make_extension(
    config: dict[str, Any] | None = None,
    *,
    client: MockGraphClient | None = None,
) -> Any:
    """Construct the SharepointExtension directly with a mock client.

    Bypasses the factory so tests can stub the GraphClient. Production
    construction goes through ``create_extension(config, persona=p)``.
    """
    mod = _import_sharepoint()
    return mod.SharepointExtension(config or {}, client or MockGraphClient())


# ── Tool surface — read-only ────────────────────────────────────────


def test_tool_list_contains_only_read_tools() -> None:
    """spec: ms-extensions / "Tool list contains only read tools".

    SharepointExtension MUST expose exactly three read tools and MUST
    NOT expose any tool with a name starting with ``sharepoint.create``
    or ``sharepoint.upload`` (write surface deferred to P5b).
    """
    ext = _make_extension()
    tools = ext.tool_specs()
    names = {t.name for t in tools}
    assert names == {
        "sharepoint.search_sites",
        "sharepoint.list_documents",
        "sharepoint.download_document",
    }, f"unexpected tool surface: {names}"

    # Read-only assertion: no write-shaped tool names.
    for name in names:
        assert not name.startswith("sharepoint.create"), name
        assert not name.startswith("sharepoint.upload"), name

    # Exactly 3 tools (read-only confirmed via count).
    assert len(tools) == 3


def test_tool_specs_returns_three_specs_with_handlers() -> None:
    """ToolSpec surface MUST expose 3 read tools with async handlers
    (P17 tool-spec migration — replaces the D11 dual-format parity)."""
    ext = _make_extension()
    specs = ext.tool_specs()
    assert len(specs) == 3
    for spec in specs:
        assert callable(spec.handler)
        assert spec.source == "extension:sharepoint"
        assert spec.input_schema.get("type") == "object"


# ── search_sites ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_sites_calls_sites_with_search_param() -> None:
    """spec: ms-extensions / "search_sites calls /sites with $search"."""
    mock = MockGraphClient()
    mock.next_get_response = _load_fixture("search_sites.json")
    ext = _make_extension(client=mock)

    result = await ext._search_sites(query="finance")

    assert len(mock.calls) == 1
    method, args, kwargs = mock.calls[0]
    assert method == "get"
    # path is /sites (search via params, not embedded in path) — D23.
    assert args == ("/sites",)
    assert kwargs["params"]["$search"] == "finance"
    # Returned value is the parsed value list from the response.
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["displayName"] == "Synthetic Finance"


@pytest.mark.asyncio
async def test_search_sites_passes_query_via_params_not_path() -> None:
    """spec: ms-extensions / "Search string is passed via params, not path".

    D23: free-text search values MUST flow through ``params=``; they
    MUST NOT appear in the request path string.
    """
    mock = MockGraphClient()
    mock.next_get_response = {"value": []}
    ext = _make_extension(client=mock)

    await ext._search_sites(query="finance & metrics")

    method, args, kwargs = mock.calls[0]
    assert method == "get"
    assert "finance" not in args[0], (
        f"search query leaked into path: {args[0]!r}"
    )
    assert kwargs["params"]["$search"] == "finance & metrics"


@pytest.mark.asyncio
async def test_search_sites_top_passes_through() -> None:
    mock = MockGraphClient()
    mock.next_get_response = {"value": []}
    ext = _make_extension(client=mock)

    await ext._search_sites(query="ops", top=10)

    _, _, kwargs = mock.calls[0]
    assert kwargs["params"]["$top"] == 10


# ── list_documents ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_documents_calls_drive_root_children() -> None:
    """list_documents MUST call the drive root children endpoint.

    Endpoint: ``/sites/{site_id}/drive/root/children``. The site_id is
    URL-encoded as a path segment per D23.
    """
    mock = MockGraphClient()
    mock.next_get_response = _load_fixture("list_documents.json")
    ext = _make_extension(client=mock)

    site_id = "synth-tenant.sharepoint.com,00000000-0000-0000-0000-000000000001"
    result = await ext._list_documents(site_id=site_id)

    assert len(mock.calls) == 1
    method, args, _kwargs = mock.calls[0]
    assert method == "get"
    # site_id is URL-encoded — comma becomes %2C and dot stays — so the
    # raw site_id string should NOT appear in the path.
    assert args[0].startswith("/sites/")
    assert args[0].endswith("/drive/root/children")
    # Confirm the raw site_id (with commas) does not appear unencoded.
    assert site_id not in args[0], (
        f"site_id was not URL-encoded in path: {args[0]!r}"
    )
    # Result is the parsed value list.
    assert isinstance(result, list)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_list_documents_url_encodes_site_id() -> None:
    """spec: ms-extensions / "Tool Input URL-Encoding and Validation".

    D23: every interpolated ID is URL-encoded via
    ``urllib.parse.quote(value, safe="")``.
    """
    mock = MockGraphClient()
    mock.next_get_response = {"value": []}
    ext = _make_extension(client=mock)

    # ID with characters that quote() will percent-encode.
    site_id = "tenant,site:id"
    await ext._list_documents(site_id=site_id)

    _, args, _ = mock.calls[0]
    # Path uses %2C (comma) and %3A (colon). Raw site_id MUST NOT appear.
    assert "%2C" in args[0] or "%2c" in args[0]
    assert "%3A" in args[0] or "%3a" in args[0]


@pytest.mark.asyncio
async def test_list_documents_top_passes_through() -> None:
    mock = MockGraphClient()
    mock.next_get_response = {"value": []}
    ext = _make_extension(client=mock)

    await ext._list_documents(site_id="abc", top=5)

    _, _, kwargs = mock.calls[0]
    assert kwargs["params"]["$top"] == 5


# ── download_document — uses get_bytes (D19) ────────────────────────


@pytest.mark.asyncio
async def test_download_document_delegates_to_get_bytes() -> None:
    """spec: ms-extensions / "download_document delegates to get_bytes
    and returns metadata dict".

    D19: the tool MUST call ``client.get_bytes(...)``, NOT
    ``client.get(...)``. Returns the metadata dict from get_bytes —
    raw bytes never enter the tool's return value.
    """
    mock = MockGraphClient()
    mock.next_get_bytes_metadata = {
        "path": "/tmp/synth-doc.pdf",
        "size_bytes": 12345,
        "content_type": "application/pdf",
        "request_id": "synth-request-id",
    }
    ext = _make_extension(client=mock)

    site_id = "synth-tenant.sharepoint.com,abc-site,xyz-web"
    item_id = "01SYNTHITEM000000000000000000000000A"
    result = await ext._download_document(site_id=site_id, item_id=item_id)

    # Call ledger MUST contain a get_bytes entry, NOT a get entry.
    methods = [call[0] for call in mock.calls]
    assert "get_bytes" in methods, (
        f"expected get_bytes call, got methods {methods}"
    )
    assert "get" not in methods, (
        f"download_document must use get_bytes, not get; got {methods}"
    )

    # Path is the SharePoint drive items content endpoint.
    get_bytes_call = next(c for c in mock.calls if c[0] == "get_bytes")
    _, args, _ = get_bytes_call
    assert args[0].startswith("/sites/")
    # The drive items pattern: /sites/{site_id}/drive/items/{item_id}/content
    assert "/drive/items/" in args[0]
    assert args[0].endswith("/content")

    # Return value is the metadata dict — exact shape from D19.
    assert result == {
        "path": "/tmp/synth-doc.pdf",
        "size_bytes": 12345,
        "content_type": "application/pdf",
        "request_id": "synth-request-id",
    }
    # No raw bytes in the return value.
    assert not isinstance(result, (bytes, bytearray))


@pytest.mark.asyncio
async def test_download_document_returns_dict_with_required_keys() -> None:
    """spec: ms-extensions / "download_document delegates to get_bytes
    and returns metadata dict" — return shape clause.

    Result MUST contain keys ``path``, ``size_bytes``, ``content_type``,
    ``request_id``.
    """
    mock = MockGraphClient()
    mock.next_get_bytes_metadata = {
        "path": "/tmp/x.bin",
        "size_bytes": 1,
        "content_type": "application/octet-stream",
        "request_id": "rid",
    }
    ext = _make_extension(client=mock)

    result = await ext._download_document(site_id="s1", item_id="i1")

    assert set(result.keys()) >= {
        "path",
        "size_bytes",
        "content_type",
        "request_id",
    }


@pytest.mark.asyncio
async def test_download_document_url_encodes_both_ids() -> None:
    """Both site_id and item_id MUST be URL-encoded (D23)."""
    mock = MockGraphClient()
    ext = _make_extension(client=mock)

    site_id = "tenant,site:id"
    item_id = "item:with:colons"
    await ext._download_document(site_id=site_id, item_id=item_id)

    get_bytes_call = next(c for c in mock.calls if c[0] == "get_bytes")
    _, args, _ = get_bytes_call
    path = args[0]
    # Raw IDs MUST NOT appear unencoded.
    assert site_id not in path
    assert item_id not in path
    # Encoded forms appear.
    assert "%3A" in path or "%3a" in path  # colon
    assert "%2C" in path or "%2c" in path  # comma


# ── Default scopes ────────────────────────────────────────────────────


def test_default_scopes_include_sites_and_files_read_all() -> None:
    """spec: ms-extensions / "Default scopes include Sites.Read.All and
    Files.Read.All"."""
    ext = _make_extension({})
    assert "Sites.Read.All" in ext.scopes
    assert "Files.Read.All" in ext.scopes


# ── Scope override REPLACE semantics (D24) ───────────────────────────


def test_persona_scopes_replace_defaults_entirely() -> None:
    """spec: ms-extensions / "Persona scopes replace defaults entirely"."""
    ext = _make_extension({"scopes": ["Sites.Read.All"]})
    assert ext.scopes == ["Sites.Read.All"]
    # Default Files.Read.All was not merged in.
    assert "Files.Read.All" not in ext.scopes


def test_empty_persona_scopes_uses_defaults() -> None:
    """spec: ms-extensions / "Empty persona scopes uses defaults"."""
    ext = _make_extension({"scopes": []})
    assert "Sites.Read.All" in ext.scopes
    assert "Files.Read.All" in ext.scopes


def test_missing_persona_scopes_uses_defaults() -> None:
    """spec: ms-extensions / "Missing persona scopes key uses defaults"."""
    ext = _make_extension({})
    assert "Sites.Read.All" in ext.scopes
    assert "Files.Read.All" in ext.scopes


# ── HealthStatus derivation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_returns_ok_when_breaker_closed() -> None:
    """spec: ms-extensions / "Real extension reports OK when breaker is
    CLOSED".

    The extension's breaker key is ``extension:sharepoint`` (per D6) so
    health_check derives state from that breaker.
    """
    ext = _make_extension()
    status = await ext.health_check()
    assert status.state is HealthState.OK
    assert status.breaker_key == "extension:sharepoint"


@pytest.mark.asyncio
async def test_health_check_returns_unavailable_when_breaker_open() -> None:
    """spec: ms-extensions / "Real extension reports UNAVAILABLE when
    breaker is OPEN"."""
    ext = _make_extension()

    # Force the extension's breaker into OPEN state.
    breaker = get_circuit_breaker_registry().get_breaker("extension:sharepoint")
    for _ in range(breaker._failure_threshold):
        await breaker.record_failure("synthetic upstream failure")

    status = await ext.health_check()
    assert status.state is HealthState.UNAVAILABLE
    assert status.breaker_key == "extension:sharepoint"


# ── URL-encoding + input validation (D23) ────────────────────────────


@pytest.mark.asyncio
async def test_path_segment_with_slash_rejected() -> None:
    """spec: ms-extensions / "Path segment with slash is rejected
    before HTTP call".

    item_id containing ``a/b`` MUST raise ValueError before any HTTP
    call is issued.
    """
    mock = MockGraphClient()
    ext = _make_extension(client=mock)

    with pytest.raises(ValueError) as exc_info:
        await ext._download_document(site_id="s1", item_id="a/b")

    assert "item_id" in str(exc_info.value)
    # No HTTP call MUST have been issued.
    assert mock.calls == []


@pytest.mark.asyncio
async def test_path_segment_with_backslash_rejected() -> None:
    """D23: backslashes are also rejected."""
    mock = MockGraphClient()
    ext = _make_extension(client=mock)

    with pytest.raises(ValueError):
        await ext._download_document(site_id=r"a\b", item_id="ok")
    assert mock.calls == []


@pytest.mark.asyncio
async def test_path_segment_with_control_char_rejected() -> None:
    """spec: ms-extensions / "Path segment with control character is
    rejected"."""
    mock = MockGraphClient()
    ext = _make_extension(client=mock)

    with pytest.raises(ValueError):
        await ext._download_document(site_id="s1", item_id="bad\x00id")
    assert mock.calls == []

    with pytest.raises(ValueError):
        await ext._list_documents(site_id="bad\x1fid")
    assert mock.calls == []


# ── OPEN-breaker structured error (D25) ─────────────────────────────


@pytest.mark.asyncio
async def test_tool_invocation_with_open_breaker_raises_graph_api_error() -> None:
    """spec: ms-extensions / "Tool invocation with OPEN breaker raises
    structured error".

    D25: when the per-extension breaker is OPEN, the tool raises
    ``GraphAPIError(status_code=None, error_code="breaker_open")`` and
    the error message MUST identify the extension by name.
    """
    mock = MockGraphClient()
    ext = _make_extension(client=mock)

    # Force the breaker to OPEN.
    breaker = get_circuit_breaker_registry().get_breaker("extension:sharepoint")
    for _ in range(breaker._failure_threshold):
        await breaker.record_failure("synth upstream failure")

    with pytest.raises(Exception) as exc_info:
        await ext._search_sites(query="anything")

    err = exc_info.value
    # The error type is GraphAPIError (from wp-foundation-impls). Until
    # that lands, the extension's lazy import falls back to a local
    # surrogate that still carries the contract attributes.
    assert err.__class__.__name__ == "GraphAPIError", (
        f"expected GraphAPIError, got {type(err).__name__}: {err!r}"
    )
    assert getattr(err, "status_code", "missing") is None
    assert getattr(err, "error_code", None) == "breaker_open"
    assert "sharepoint" in str(err)
    # No HTTP call MUST have been issued.
    assert mock.calls == []


# ── Factory persona=None TypeError (D26) ─────────────────────────────


def test_factory_persona_none_raises_actionable_typeerror() -> None:
    """spec: extension-registry / "Real factory called with persona=None
    raises actionable TypeError".

    D26: real Microsoft 365 factories MUST raise TypeError when
    persona is None (the default), before any MSALStrategy /
    GraphClient construction.
    """
    mod = _import_sharepoint()

    with pytest.raises(TypeError) as exc_info:
        mod.create_extension({}, persona=None)

    msg = str(exc_info.value)
    # Identify the offending extension by name.
    assert "sharepoint" in msg
    # Cite persona-config keys so the operator can fix it.
    assert "extensions" in msg
    assert "auth.ms" in msg


def test_factory_persona_omitted_raises_actionable_typeerror() -> None:
    """spec: extension-registry / "Real factory called with persona=None
    raises actionable TypeError" — omitted defaults to None.

    Calling ``create_extension({})`` without ``persona=`` MUST raise
    the same TypeError because the Protocol signature defaults persona
    to None.
    """
    mod = _import_sharepoint()

    with pytest.raises(TypeError) as exc_info:
        mod.create_extension({})

    assert "sharepoint" in str(exc_info.value)


# ── Pagination discipline ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_documents_does_not_fetch_per_item() -> None:
    """spec: ms-extensions / "list_messages does not call Graph per item"
    — same discipline applies to ``sharepoint.list_documents``.

    The call ledger size MUST NOT scale with the number of items in
    the response (no N+1 enrichment fetches).
    """
    mock = MockGraphClient()
    # Response with many items — discipline forbids per-item fetches.
    mock.next_get_response = {
        "value": [{"id": f"item-{i}", "name": f"f{i}.pdf"} for i in range(50)]
    }
    ext = _make_extension(client=mock)

    await ext._list_documents(site_id="s1", top=50)

    # Exactly one call: the initial GET. No per-item enrichment.
    assert len(mock.calls) == 1
    assert mock.calls[0][0] == "get"
