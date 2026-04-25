"""Verify graphiti operations are NOT separately instrumented.

Per req observability.6 ("MemoryManager Operation Tracing"):

> Graphiti client calls (`create_graphiti_client(persona)` and its
> inner `add_episode` / query methods at `src/assistant/core/graphiti.py`)
> are NOT separately instrumented at the telemetry layer — they are
> observed only through the `MemoryManager` method that invoked them.

This file owns the design-decision check that
``src/assistant/core/graphiti.py`` does not import telemetry helpers
and that no second ``trace_memory_op`` span is emitted from inside the
graphiti client when ``MemoryManager.store_episode`` runs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from assistant.telemetry import factory


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


class _FakeSession:
    async def execute(self, _stmt: Any) -> Any:
        class _Result:
            def scalars(self_inner: Any) -> Any:
                class _Scalars:
                    def all(self2: Any) -> list[Any]:
                        return []

                return _Scalars()

        return _Result()

    async def commit(self) -> None:
        return None

    def add(self, _obj: Any) -> None:
        return None


class _FakeSessionFactory:
    @asynccontextmanager
    async def __call__(self) -> Any:
        yield _FakeSession()


class _FakeGraphiti:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def add_episode(self, **_: Any) -> None:
        self.calls.append("add_episode")

    async def search(self, query: str, num_results: int = 5) -> list[Any]:
        self.calls.append(f"search:{query}")
        return []


def test_graphiti_module_does_not_import_telemetry_decorators() -> None:
    """Static check: graphiti.py MUST NOT import telemetry decorators.

    The design explicitly forbids per-graphiti-call spans (req
    observability.6). If a future change adds telemetry hooks at the
    graphiti layer, this test fires so the design decision is
    revisited intentionally rather than drifting silently.
    """
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "assistant"
        / "core"
        / "graphiti.py"
    )
    text = src.read_text()
    assert "from assistant.telemetry" not in text
    assert "trace_memory_op" not in text


@pytest.mark.asyncio
async def test_store_episode_emits_exactly_one_span_around_graphiti(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Spec scenario: store_episode emits ONE trace_memory_op covering graphiti.

    No second ``trace_memory_op`` SHALL be emitted from inside the
    graphiti client even though ``store_episode`` invokes graphiti's
    ``add_episode`` method.
    """
    from assistant.core.memory import MemoryManager

    _install_spy(monkeypatch, spy_provider)
    graphiti = _FakeGraphiti()
    mgr = MemoryManager(_FakeSessionFactory(), graphiti_client=graphiti)  # type: ignore[arg-type]

    await mgr.store_episode("personal", "x happened", "test")

    # Exactly one boundary-level span.
    calls = spy_provider.calls["trace_memory_op"]
    assert len(calls) == 1
    assert calls[0]["op"] == "episode_write"
    # Graphiti was actually invoked, proving the single boundary span
    # genuinely covers the graphiti call.
    assert graphiti.calls == ["add_episode"]


@pytest.mark.asyncio
async def test_search_emits_exactly_one_span_around_graphiti(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """search() also covers graphiti.search with one boundary span."""
    from assistant.core.memory import MemoryManager

    _install_spy(monkeypatch, spy_provider)
    graphiti = _FakeGraphiti()
    mgr = MemoryManager(_FakeSessionFactory(), graphiti_client=graphiti)  # type: ignore[arg-type]

    await mgr.search("personal", "query text")
    calls = spy_provider.calls["trace_memory_op"]
    assert len(calls) == 1
    assert calls[0]["op"] == "search"
    assert graphiti.calls == ["search:query text"]
