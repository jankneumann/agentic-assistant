"""Typed test fixture that satisfies ``CloudGraphClient``.

Lives in ``wp-foundation-protocols`` so extension test suites can use
it without depending on the httpx-based ``GraphClient`` implementation
that lands in ``wp-foundation-impls``. Per-test stub responses are
configured by attribute assignment on the instance — no global state,
no respx required for unit tests that only care about extension logic.

Spec: graph-client / "MockGraphClient satisfies Protocol" (design D7).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from assistant.core.cloud_client import CloudGraphClient
from assistant.core.resilience import (
    HealthState,
    HealthStatus,
)


class MockGraphClient:
    """Typed mock that satisfies ``CloudGraphClient`` at runtime.

    Configure per-test:

        mock = MockGraphClient()
        mock.next_get_response = {"value": [{"id": "1"}]}
        mock.next_paginate_pages = [page1_dict, page2_dict]
        mock.next_post_response = {"id": "msg-123"}
        mock.next_get_bytes_path = "/tmp/x.pdf"
        mock.next_get_bytes_metadata = {"size_bytes": 12345, ...}

    Each method records its call args on ``self.calls`` (a list of
    ``(method_name, args, kwargs)`` tuples) so tests can assert on the
    call ledger.
    """

    name: str = "mock"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed: bool = False

        self.next_get_response: dict[str, Any] = {}
        self.next_post_response: dict[str, Any] = {}
        self.next_paginate_pages: list[dict[str, Any]] = []
        self.next_get_bytes_metadata: dict[str, Any] | None = None
        self.next_health_status: HealthStatus = HealthStatus(
            state=HealthState.OK,
            reason="mock",
            last_error=None,
            checked_at=datetime.now(UTC),
            breaker_key="mock",
        )

        # Optional side-effect injection for failure paths. If set,
        # the next call to the matching method raises this exception.
        self.next_get_exception: BaseException | None = None
        self.next_post_exception: BaseException | None = None
        self.next_paginate_exception: BaseException | None = None
        self.next_get_bytes_exception: BaseException | None = None

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            ("get", (path,), {"params": params, "headers": headers})
        )
        if self.next_get_exception is not None:
            exc, self.next_get_exception = self.next_get_exception, None
            raise exc
        return self.next_get_response

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_safe: bool = True,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "post",
                (path,),
                {
                    "json": json,
                    "params": params,
                    "headers": headers,
                    "retry_safe": retry_safe,
                },
            )
        )
        if self.next_post_exception is not None:
            exc, self.next_post_exception = self.next_post_exception, None
            raise exc
        return self.next_post_response

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(("paginate", (path,), {"params": params}))
        if self.next_paginate_exception is not None:
            exc = self.next_paginate_exception
            self.next_paginate_exception = None
            raise exc
        for page in self.next_paginate_pages:
            yield page

    async def get_bytes(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        max_bytes: int = 50 * 1024 * 1024,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "get_bytes",
                (path,),
                {"params": params, "headers": headers, "max_bytes": max_bytes},
            )
        )
        if self.next_get_bytes_exception is not None:
            exc = self.next_get_bytes_exception
            self.next_get_bytes_exception = None
            raise exc
        if self.next_get_bytes_metadata is not None:
            return self.next_get_bytes_metadata
        # Default: write a tiny tempfile so callers can stat it. Tests
        # that need a specific shape MUST set ``next_get_bytes_metadata``.
        fd, tmp_path = tempfile.mkstemp(prefix="mock_graph_", suffix=".bin")
        try:
            os.write(fd, b"")
        finally:
            os.close(fd)
        return {
            "path": tmp_path,
            "size_bytes": 0,
            "content_type": "application/octet-stream",
            "request_id": "mock-request-id",
        }

    async def health_check(self) -> HealthStatus:
        self.calls.append(("health_check", (), {}))
        return self.next_health_status

    async def __aenter__(self) -> CloudGraphClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self.calls.append(("aclose", (), {}))
        self.closed = True
