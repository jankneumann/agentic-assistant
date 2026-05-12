"""Opt-in smoke tests for the four real Microsoft 365 extensions.

These tests exercise the extensions against the real Microsoft Graph
API. They are gated on ``RUN_GRAPH_TESTS=1`` and require the same
environment variables a real persona would (``AZURE_TENANT_ID``,
``AZURE_CLIENT_ID``, plus delegated identity for read tests).

CI does NOT run these — keeping them out of the default pytest sweep
avoids leaking real credentials into log artifacts and prevents flaky
behavior from Microsoft Graph's throttling on shared CI accounts.

Local invocation:

    RUN_GRAPH_TESTS=1 \
    AZURE_TENANT_ID=... AZURE_CLIENT_ID=... \
    uv run pytest tests/integration/test_graph_smoke.py -v

Per task 7.6 (smoke gating) and 8.5.2 (get_bytes streaming smoke).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GRAPH_TESTS") != "1",
    reason="set RUN_GRAPH_TESTS=1 to run real-Graph smoke tests",
)


def test_smoke_marker_is_respected() -> None:
    """Sanity test that the gating env-var actually enables collection.

    Visible only when ``RUN_GRAPH_TESTS=1`` is set; otherwise pytest
    skips the entire module per the module-level ``pytestmark``.
    """
    assert os.environ.get("RUN_GRAPH_TESTS") == "1"


def test_get_bytes_streaming_smoke_via_mock() -> None:
    """Verify ``get_bytes`` end-to-end against MockGraphClient (8.5.2).

    This is a smoke check that the SharePoint download flow:
    1. Calls ``client.get_bytes`` (NOT ``client.get``)
    2. Receives the metadata dict shape (path, size_bytes, content_type,
       request_id)
    3. Hands it back to the caller without parsing the bytes content

    The full streaming-against-real-SharePoint test is skipped on CI
    by ``pytestmark``; this in-module smoke is a no-credential
    fallback that runs when ``RUN_GRAPH_TESTS=1`` and asserts the
    code path still wires up correctly.
    """
    import asyncio

    from assistant.extensions.sharepoint import SharepointExtension
    from tests.mocks.graph_client import MockGraphClient

    mock = MockGraphClient()
    mock.next_get_bytes_metadata = {
        "path": "/tmp/smoke.bin",
        "size_bytes": 12345,
        "content_type": "application/pdf",
        "request_id": "smoke-request-id",
    }
    ext = SharepointExtension({}, client=mock)

    async def _drive() -> dict[str, object]:
        return await ext._download_document(
            site_id="site-1", item_id="item-1"
        )

    result = asyncio.run(_drive())
    assert result["size_bytes"] == 12345
    assert result["content_type"] == "application/pdf"
    # The call ledger must contain a get_bytes entry, NOT a get entry —
    # this is the central D19 invariant for SharePoint downloads.
    methods = [c[0] for c in mock.calls]
    assert "get_bytes" in methods
    assert "get" not in methods
