"""Tests for ``wrap_tool_spec`` / ``wrap_extension_tool_specs``.

Wrapping policy (per spec extension-registry + http-tools, migrated to
the ToolSpec layer by P17 ``mcp-server-exposure``):

- ``wrap_tool_spec(spec, tool_kind="extension")`` returns a new
  ``ToolSpec`` whose handler emits
  ``trace_tool_call(tool_kind="extension", ...)`` once per invocation.
- ``wrap_http_tool_spec(spec)`` does the same with ``tool_kind="http"``.
- ``name``, ``description``, ``input_schema``, ``source`` MUST pass
  through unchanged.
- On exception, ``trace_tool_call`` MUST be invoked with ``error=<type
  name>`` *before* the exception propagates.
- ``wrap_extension_tool_specs(ext)`` is a convenience helper that calls
  ``ext.tool_specs()`` and applies ``wrap_tool_spec`` to each yielded
  spec.
- Because wrapping happens at the ToolSpec layer, the trace survives
  every per-harness rendering — verified here for the LangChain
  adapter (the MCP surface invokes ``spec.handler`` directly).
"""

from __future__ import annotations

from typing import Any

import pytest

from assistant.core.toolspec import ToolSpec
from assistant.telemetry import factory
from assistant.telemetry.context import set_assistant_ctx


@pytest.fixture(autouse=True)
def _bind_ctx() -> None:
    """Per-test ContextVar binding so spans see persona/role labels."""
    set_assistant_ctx("personal", "assistant")


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


def _make_spec(name: str = "gmail.search") -> ToolSpec:
    async def _handler(query: str) -> str:
        return f"hit:{query}"

    return ToolSpec(
        name=name,
        description="A test tool.",
        input_schema=dict(_SCHEMA),
        handler=_handler,
        source="extension:gmail",
    )


def _make_failing_spec(
    exc: BaseException, name: str = "gmail.search"
) -> ToolSpec:
    async def _handler(query: str) -> str:
        raise exc

    return ToolSpec(
        name=name,
        description="A failing tool.",
        input_schema=dict(_SCHEMA),
        handler=_handler,
        source="extension:gmail",
    )


# ---------------------------------------------------------------------------
# wrap_tool_spec (extension kind)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_tool_spec_emits_trace_on_success(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.tool_wrap import wrap_tool_spec

    _install_spy(monkeypatch, spy_provider)
    wrapped = wrap_tool_spec(_make_spec(), tool_kind="extension")

    out = await wrapped.handler(query="foo")
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


def test_wrap_tool_spec_preserves_metadata(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """``name``, ``description``, ``input_schema``, ``source`` pass through."""
    from assistant.telemetry.tool_wrap import wrap_tool_spec

    _install_spy(monkeypatch, spy_provider)
    src = _make_spec(name="gmail.search")
    wrapped = wrap_tool_spec(src, tool_kind="extension")
    assert wrapped.name == "gmail.search"
    assert wrapped.description == "A test tool."
    assert wrapped.input_schema == src.input_schema
    assert wrapped.source == "extension:gmail"
    assert wrapped.handler is not src.handler


def test_wrap_tool_spec_passes_non_toolspec_through(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Non-ToolSpec inputs (test fakes) pass through unchanged."""
    from unittest.mock import MagicMock

    from assistant.telemetry.tool_wrap import wrap_tool_spec

    _install_spy(monkeypatch, spy_provider)
    fake = MagicMock()
    assert wrap_tool_spec(fake, tool_kind="extension") is fake


@pytest.mark.asyncio
async def test_wrap_tool_spec_emits_error_then_reraises(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.tool_wrap import wrap_tool_spec

    _install_spy(monkeypatch, spy_provider)
    wrapped = wrap_tool_spec(
        _make_failing_spec(ValueError("invalid query")),
        tool_kind="extension",
    )

    with pytest.raises(ValueError, match="invalid query"):
        await wrapped.handler(query="x")

    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["error"] == "ValueError"


# ---------------------------------------------------------------------------
# wrap_http_tool_spec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_http_tool_spec_emits_trace_on_success(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    from assistant.telemetry.tool_wrap import wrap_http_tool_spec

    _install_spy(monkeypatch, spy_provider)
    src = _make_spec(name="linear.listIssues")
    wrapped = wrap_http_tool_spec(src)

    out = await wrapped.handler(query="open")
    assert out == "hit:open"
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "linear.listIssues"
    assert calls[0]["tool_kind"] == "http"


@pytest.mark.asyncio
async def test_wrap_http_tool_spec_emits_error_for_http_status_error(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """HTTPStatusError is a common httpx error path."""
    import httpx

    from assistant.telemetry.tool_wrap import wrap_http_tool_spec

    _install_spy(monkeypatch, spy_provider)

    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("503", request=request, response=response)
    wrapped = wrap_http_tool_spec(
        _make_failing_spec(exc, name="linear.listIssues")
    )

    with pytest.raises(httpx.HTTPStatusError):
        await wrapped.handler(query="open")
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["error"] == "HTTPStatusError"


# ---------------------------------------------------------------------------
# wrap_extension_tool_specs (convenience helper)
# ---------------------------------------------------------------------------


class _FakeExtension:
    name = "gmail"

    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = specs

    def tool_specs(self) -> list[ToolSpec]:
        return self._specs

    async def health_check(self) -> bool:
        return True


def test_wrap_extension_tool_specs_returns_wrapped_list() -> None:
    from assistant.telemetry.tool_wrap import wrap_extension_tool_specs

    src1 = _make_spec(name="gmail.search")
    src2 = _make_spec(name="gmail.send")
    ext = _FakeExtension([src1, src2])
    wrapped = wrap_extension_tool_specs(ext)
    assert len(wrapped) == 2
    assert [t.name for t in wrapped] == ["gmail.search", "gmail.send"]
    # Wrapping happened — they are not the same object as the originals.
    assert all(t is not src1 and t is not src2 for t in wrapped)


# ---------------------------------------------------------------------------
# Wrapping survives per-harness rendering (P17 wrap-layer decision)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrapped_spec_traces_through_langchain_rendering(
    monkeypatch: pytest.MonkeyPatch, spy_provider: Any
) -> None:
    """Rendering a wrapped ToolSpec via the LangChain adapter keeps the
    trace: invoking the rendered StructuredTool emits exactly one
    ``trace_tool_call`` (no double wrapping, no lost span)."""
    from assistant.harnesses.tool_adapters import render_langchain_tool
    from assistant.telemetry.tool_wrap import wrap_tool_spec

    _install_spy(monkeypatch, spy_provider)
    wrapped = wrap_tool_spec(_make_spec(), tool_kind="extension")
    rendered = render_langchain_tool(wrapped)

    out = await rendered.ainvoke({"query": "foo"})
    assert out == "hit:foo"
    calls = spy_provider.calls["trace_tool_call"]
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "gmail.search"
    assert calls[0]["tool_kind"] == "extension"
