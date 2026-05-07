"""Tests for ``assistant.core.cloud_client``.

Covers the graph-client capability scenarios that pertain to the
Protocol shape itself (custom GraphClient impl + httpx semantics live
in wp-foundation-impls / ``test_graph_client.py``):

- "Protocol declares five transport + three lifecycle methods"
- "Custom GraphClient satisfies Protocol" (deferred — landed by impls)
- "MockGraphClient satisfies Protocol"
"""

from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from assistant.core.cloud_client import CloudGraphClient
from tests.mocks.graph_client import MockGraphClient

# ── Protocol shape ───────────────────────────────────────────────────


_TRANSPORT_METHODS = ("get", "post", "paginate", "get_bytes", "health_check")
_LIFECYCLE_METHODS = ("__aenter__", "__aexit__", "aclose")


@pytest.mark.parametrize("method_name", _TRANSPORT_METHODS)
def test_transport_methods_present(method_name: str) -> None:
    """All five transport methods MUST be declared on the Protocol."""
    assert hasattr(CloudGraphClient, method_name), (
        f"CloudGraphClient missing transport method {method_name!r}"
    )


@pytest.mark.parametrize("method_name", _LIFECYCLE_METHODS)
def test_lifecycle_methods_present(method_name: str) -> None:
    """All three lifecycle methods MUST be declared on the Protocol."""
    assert hasattr(CloudGraphClient, method_name), (
        f"CloudGraphClient missing lifecycle method {method_name!r}"
    )


_COROUTINE_METHODS = (
    "get",
    "post",
    "get_bytes",
    "health_check",
    "__aenter__",
    "__aexit__",
    "aclose",
)


@pytest.mark.parametrize("method_name", _COROUTINE_METHODS)
def test_coroutine_methods_are_async(method_name: str) -> None:
    """Every coroutine-returning Protocol method MUST be async.

    ``paginate`` is excluded because it returns an ``AsyncIterator``
    — the canonical Protocol shape is ``def paginate(...) ->
    AsyncIterator[...]: ...``, not ``async def``. See
    ``test_paginate_returns_async_iterator`` for that contract.
    """
    method = getattr(CloudGraphClient, method_name)
    assert inspect.iscoroutinefunction(method), (
        f"{method_name} on CloudGraphClient must be a coroutine function; "
        f"got {type(method).__name__}"
    )


def test_paginate_returns_async_iterator() -> None:
    """``paginate`` MUST be declared as ``def → AsyncIterator[...]``.

    Concrete implementations may use either ``async def with yield``
    (async-generator function) or a sync function returning an async
    iterator object — both satisfy the Protocol when called via
    ``async for page in client.paginate(...)``.
    """
    hints = get_type_hints(CloudGraphClient.paginate)
    return_type = hints.get("return")
    assert return_type is not None
    origin = getattr(return_type, "__origin__", return_type)
    # ``AsyncIterator`` lives in ``collections.abc``; check by name to
    # tolerate both that origin and the typing-module alias.
    origin_name = getattr(origin, "__name__", str(origin))
    assert "AsyncIterator" in origin_name, (
        f"paginate return type MUST be AsyncIterator-shaped; "
        f"got {return_type!r} (origin {origin_name!r})"
    )


def test_get_bytes_return_type_is_dict() -> None:
    """``get_bytes`` MUST return a metadata dict, not raw bytes (D19).

    Streaming the body to a tempfile and returning a metadata dict
    keeps LLM tool serialization bounded — raw bytes never enter agent
    context.
    """
    hints = get_type_hints(CloudGraphClient.get_bytes)
    return_type = hints.get("return")
    # ``dict[str, Any]`` resolves under get_type_hints to ``dict``-shaped
    # generic; confirm origin is dict, not bytes.
    assert return_type is not None
    origin = getattr(return_type, "__origin__", return_type)
    assert origin is dict, (
        f"get_bytes return type MUST be dict (was {return_type!r}); "
        "binary content streams to a tempfile per design D19."
    )


def test_protocol_is_runtime_checkable() -> None:
    """``isinstance(obj, CloudGraphClient)`` MUST work at runtime."""
    # Smoke test — if the decorator is missing, isinstance() raises
    # ``TypeError: Instance and class checks can only be used with
    # @runtime_checkable protocols``.
    instance = MockGraphClient()
    assert isinstance(instance, CloudGraphClient)


# ── MockGraphClient conformance ──────────────────────────────────────


def test_mock_graph_client_satisfies_protocol() -> None:
    """``MockGraphClient`` MUST be a structural ``CloudGraphClient``.

    Spec scenario: graph-client / "MockGraphClient satisfies Protocol".
    """
    assert isinstance(MockGraphClient(), CloudGraphClient)


def test_mock_records_call_ledger() -> None:
    """MockGraphClient MUST record method calls so tests can assert on them."""
    import asyncio

    async def _exercise() -> list[tuple[str, tuple, dict]]:
        mock = MockGraphClient()
        mock.next_get_response = {"value": [{"id": "1"}]}
        await mock.get("/me/messages", params={"$top": 5})
        await mock.post("/me/sendMail", json={"message": {"subject": "x"}})
        return mock.calls

    calls = asyncio.run(_exercise())
    assert len(calls) == 2
    assert calls[0][0] == "get"
    assert calls[0][1] == ("/me/messages",)
    assert calls[0][2]["params"] == {"$top": 5}
    assert calls[1][0] == "post"
    assert calls[1][2]["retry_safe"] is True  # default


def test_mock_post_records_retry_safe_flag() -> None:
    """Tests for non-idempotent writes need to assert ``retry_safe=False``."""
    import asyncio

    async def _exercise() -> dict[str, object]:
        mock = MockGraphClient()
        await mock.post("/me/sendMail", json={"x": 1}, retry_safe=False)
        return mock.calls[0][2]

    kwargs = asyncio.run(_exercise())
    assert kwargs["retry_safe"] is False


def test_mock_async_context_manager_closes() -> None:
    """``async with mock`` MUST set ``mock.closed = True`` on exit."""
    import asyncio

    async def _exercise() -> bool:
        mock = MockGraphClient()
        async with mock as client:
            assert client is mock
        return mock.closed

    assert asyncio.run(_exercise()) is True
