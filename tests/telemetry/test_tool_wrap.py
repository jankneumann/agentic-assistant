"""Tests for ``wrap_structured_tool`` / ``wrap_extension_tools``.

Wrapping policy (per spec extension-registry + http-tools):

- ``wrap_extension_tool(tool)`` returns a new ``StructuredTool`` whose
  invocation emits ``trace_tool_call(tool_kind="extension", ...)``.
- ``wrap_http_tool(tool)`` does the same with ``tool_kind="http"``.
- ``name``, ``description``, ``args_schema`` MUST pass through unchanged.
- On exception, ``trace_tool_call`` MUST be invoked with ``error=<type
  name>`` *before* the exception propagates.
- ``wrap_extension_tools(ext)`` is a convenience helper that calls
  ``ext.as_langchain_tools()`` and applies ``wrap_extension_tool`` to
  each yielded tool.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from assistant.telemetry import factory
from assistant.telemetry.context import set_assistant_ctx


@pytest.fixture(autouse=True)
def _bind_ctx() -> None:
    """Per-test ContextVar binding so spans see persona/role labels."""
    set_assistant_ctx("personal", "assistant")


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


class _Args(BaseModel):
    query: str = Field(..., description="What to search for.")


def _make_tool(name: str = "gmail.search") -> StructuredTool:
    async def _coro(query: str) -> str:
        return f"hit:{query}"

    return StructuredTool.from_function(
        coroutine=_coro,
        name=name,
        description="A test tool.",
        args_schema=_Args,
    )


def _make_failing_tool(exc: BaseException, name: str = "gmail.search") -> StructuredTool:
    async def _coro(query: str) -> str:
        raise exc

    return StructuredTool.from_function(
        coroutine=_coro,
        name=name,
        description="A failing tool.",
        args_schema=_Args,
    )


# ---------------------------------------------------------------------------
# wrap_extension_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_extension_tool_emits_trace_on_success(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.tool_wrap import wrap_extension_tool

    _install_spy(monkeypatch, spy_provider)
    wrapped = wrap_extension_tool(_make_tool())

    out = await wrapped.ainvoke({"query": "foo"})
    assert out == "hit:foo"
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    call = calls[0]
    assert call["tool_name"] == "gmail.search"
    assert call["tool_kind"] == "extension"
    assert call["persona"] == "personal"
    assert call["role"] == "assistant"
    assert isinstance(call["duration_ms"], float)
    assert call.get("error") is None


def test_wrap_extension_tool_preserves_metadata(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """``name``, ``description``, ``args_schema`` MUST pass through."""
    from assistant.telemetry.tool_wrap import wrap_extension_tool

    _install_spy(monkeypatch, spy_provider)
    src = _make_tool(name="gmail.search")
    wrapped = wrap_extension_tool(src)
    assert wrapped.name == "gmail.search"
    assert wrapped.description == "A test tool."
    assert wrapped.args_schema is _Args


@pytest.mark.asyncio
async def test_wrap_extension_tool_emits_error_then_reraises(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.tool_wrap import wrap_extension_tool

    _install_spy(monkeypatch, spy_provider)
    wrapped = wrap_extension_tool(_make_failing_tool(ValueError("invalid query")))

    with pytest.raises(ValueError, match="invalid query"):
        await wrapped.ainvoke({"query": "x"})

    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["error"] == "ValueError"


# ---------------------------------------------------------------------------
# wrap_http_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_http_tool_emits_trace_on_success(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.tool_wrap import wrap_http_tool

    _install_spy(monkeypatch, spy_provider)
    src = _make_tool(name="linear.listIssues")
    wrapped = wrap_http_tool(src)

    out = await wrapped.ainvoke({"query": "open"})
    assert out == "hit:open"
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "linear.listIssues"
    assert calls[0]["tool_kind"] == "http"


@pytest.mark.asyncio
async def test_wrap_http_tool_emits_error_for_http_status_error(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """HTTPStatusError is a common httpx error path."""
    import httpx

    from assistant.telemetry.tool_wrap import wrap_http_tool

    _install_spy(monkeypatch, spy_provider)

    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("503", request=request, response=response)
    wrapped = wrap_http_tool(_make_failing_tool(exc, name="linear.listIssues"))

    with pytest.raises(httpx.HTTPStatusError):
        await wrapped.ainvoke({"query": "open"})
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["error"] == "HTTPStatusError"


# ---------------------------------------------------------------------------
# wrap_extension_tools (convenience helper)
# ---------------------------------------------------------------------------


class _FakeExtension:
    name = "gmail"

    def __init__(self, tools: list[StructuredTool]) -> None:
        self._tools = tools

    def as_langchain_tools(self) -> list[StructuredTool]:
        return self._tools

    def as_ms_agent_tools(self) -> list[Any]:
        return []

    async def health_check(self) -> bool:
        return True


def test_wrap_extension_tools_returns_wrapped_list() -> None:
    from assistant.telemetry.tool_wrap import wrap_extension_tools

    src1 = _make_tool(name="gmail.search")
    src2 = _make_tool(name="gmail.send")
    ext = _FakeExtension([src1, src2])
    wrapped = wrap_extension_tools(ext)
    assert len(wrapped) == 2
    assert {t.name for t in wrapped} == {"gmail.search", "gmail.send"}
    # Wrapping happened — they are not the same object as the originals.
    assert all(t is not src1 and t is not src2 for t in wrapped)
