"""Tests for ``MemoryManager`` tracing (Phase 3 wp-hooks).

Each public method on :class:`MemoryManager` (``get_context``,
``store_fact``, ``store_interaction``, ``store_episode``, ``search``,
``export_memory``) MUST emit exactly one ``trace_memory_op`` per call
with the spec-defined ``op`` value. The ``target`` argument follows
the mapping in the observability spec (Requirement: MemoryManager
Operation Tracing).

These tests use the in-memory ``SpyProvider`` fixture and a fake
sessionmaker / fake graphiti so the assertions stay focused on
emission contract — not on Postgres or graphiti behavior.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Any

import pytest

from assistant.telemetry import factory


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


# ---------------------------------------------------------------------------
# Test doubles for the MemoryManager dependencies. We avoid touching
# Postgres or graphiti — only the trace emission contract is exercised.
# ---------------------------------------------------------------------------


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
    """Records inner calls so the no-double-counting test can verify."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def add_episode(self, **_: Any) -> None:
        self.calls.append("add_episode")

    async def search(self, query: str, num_results: int = 5) -> list[Any]:
        self.calls.append(f"search:{query}")
        return []


@pytest.fixture
def spy_and_manager(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> Any:
    from assistant.core.memory import MemoryManager

    _install_spy(monkeypatch, spy_provider)
    graphiti = _FakeGraphiti()
    mgr = MemoryManager(_FakeSessionFactory(), graphiti_client=graphiti)  # type: ignore[arg-type]
    return spy_provider, mgr, graphiti


# ---------------------------------------------------------------------------
# Per-method emission contract.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_context_emits_op_context(spy_and_manager: Any) -> None:
    spy, mgr, _ = spy_and_manager
    await mgr.get_context("personal", "assistant")
    calls = spy.calls["trace_memory_op"]
    assert len(calls) == 1
    assert calls[0]["op"] == "context"
    assert calls[0]["target"] == "personal"
    assert calls[0]["persona"] == "personal"
    assert isinstance(calls[0]["duration_ms"], float)


@pytest.mark.asyncio
async def test_store_fact_emits_op_fact_write_with_key_target(
    spy_and_manager: Any,
) -> None:
    spy, mgr, _ = spy_and_manager
    await mgr.store_fact("personal", "last_summary", "value")
    calls = spy.calls["trace_memory_op"]
    assert len(calls) == 1
    assert calls[0]["op"] == "fact_write"
    assert calls[0]["target"] == "last_summary"
    assert calls[0]["persona"] == "personal"


@pytest.mark.asyncio
async def test_store_interaction_emits_op_interaction_write(
    spy_and_manager: Any,
) -> None:
    spy, mgr, _ = spy_and_manager
    await mgr.store_interaction("personal", "assistant", "summary text")
    calls = spy.calls["trace_memory_op"]
    assert len(calls) == 1
    assert calls[0]["op"] == "interaction_write"
    assert calls[0]["target"] == "personal"


@pytest.mark.asyncio
async def test_store_episode_emits_op_episode_write_no_double_count(
    spy_and_manager: Any,
) -> None:
    """Spec scenario: exactly ONE trace_memory_op for store_episode.

    Even though store_episode internally calls graphiti.add_episode,
    no second span MUST be emitted from inside the graphiti client.
    Per req observability.6, instrumentation lives at the MemoryManager
    boundary only.
    """
    spy, mgr, graphiti = spy_and_manager
    await mgr.store_episode("personal", "an event happened", "test")
    calls = spy.calls["trace_memory_op"]
    assert len(calls) == 1
    assert calls[0]["op"] == "episode_write"
    assert calls[0]["target"] == "personal"
    # Verify graphiti was actually invoked — proving the single span
    # spans the inner call.
    assert graphiti.calls == ["add_episode"]


@pytest.mark.asyncio
async def test_search_emits_op_search_with_query_target(
    spy_and_manager: Any,
) -> None:
    spy, mgr, _ = spy_and_manager
    await mgr.search("personal", "recent decisions")
    calls = spy.calls["trace_memory_op"]
    assert len(calls) == 1
    assert calls[0]["op"] == "search"
    assert calls[0]["target"] == "recent decisions"


@pytest.mark.asyncio
async def test_search_hashes_long_query(spy_and_manager: Any) -> None:
    spy, mgr, _ = spy_and_manager
    long_query = "q" * 1000
    await mgr.search("personal", long_query)
    calls = spy.calls["trace_memory_op"]
    assert len(calls) == 1
    assert re.match(r"^sha256:[0-9a-f]{16}$", calls[0]["target"]) is not None


@pytest.mark.asyncio
async def test_export_memory_emits_op_export(spy_and_manager: Any) -> None:
    spy, mgr, _ = spy_and_manager
    await mgr.export_memory("personal")
    calls = spy.calls["trace_memory_op"]
    assert len(calls) == 1
    assert calls[0]["op"] == "export"
    assert calls[0]["target"] == "personal"


# ---------------------------------------------------------------------------
# Enum validation — spec scenario "Rejects mis-typed op value".
# The SpyProvider raises ValueError on bad op values, mirroring the
# NoopProvider/LangfuseProvider validation contract.
# ---------------------------------------------------------------------------


def test_spy_provider_rejects_wrong_case_op(spy_provider: Any) -> None:
    with pytest.raises(ValueError, match="invalid op="):
        spy_provider.trace_memory_op(
            op="CONTEXT", target=None, persona=None, duration_ms=0.0
        )


def test_spy_provider_rejects_unknown_op(spy_provider: Any) -> None:
    with pytest.raises(ValueError, match="invalid op="):
        spy_provider.trace_memory_op(
            op="frobnicate", target=None, persona=None, duration_ms=0.0
        )
