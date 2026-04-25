"""StructuredTool wrappers that emit ``trace_tool_call`` (D3).

Owned by ``wp-hooks``. Lives under ``assistant.telemetry`` for import
clarity but contains hook-integration logic, not the telemetry
contract surface.

Two public wrappers:

- :func:`wrap_extension_tool` — emits ``tool_kind="extension"``.
- :func:`wrap_http_tool` — emits ``tool_kind="http"``.

Both share the same wrapping policy:

- A new :class:`StructuredTool` is constructed via
  ``StructuredTool.from_function``, preserving the source tool's
  ``name``, ``description``, and ``args_schema`` so agents and
  tool-discovery consumers see no change in the public contract.
- The wrapper invokes the source tool's ``coroutine`` (or runs
  ``func`` in a thread) inside a ``perf_counter`` window, then emits
  exactly one ``trace_tool_call`` per invocation. On exception, the
  span carries ``error=<type name>`` before the exception is
  re-raised.

The convenience helper :func:`wrap_extension_tools` calls
``ext.as_langchain_tools()`` once and applies
:func:`wrap_extension_tool` to each yielded tool — used at the two
extension-tool aggregation sites named in the
``capability-resolver`` spec.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from langchain_core.tools import StructuredTool

from assistant.telemetry.context import get_assistant_ctx
from assistant.telemetry.factory import get_observability_provider


def _wrap(
    tool: StructuredTool,
    *,
    tool_kind: str,
) -> StructuredTool:
    """Construct a ``StructuredTool`` whose invocation emits one trace.

    ``tool_kind`` is one of ``"extension"`` or ``"http"``; provider
    validation rejects any other value.

    The wrapped tool preserves the source tool's invocation surface:
    if the source had ``func`` (sync) the wrapped tool also has ``func``
    so ``tool.invoke(...)`` keeps working; if the source had only
    ``coroutine``, the wrapped tool exposes only ``coroutine`` and a
    sync caller will see the same async-only behaviour as before. This
    matters because LangChain's ReAct agents and most async harnesses
    call ``ainvoke`` while CLI tooling and certain test paths still use
    ``.invoke()`` — wrapping must not narrow the source contract. (Iter
    2 fix for IMPL_REVIEW round 1 finding E.)
    """
    name = tool.name
    description = tool.description
    args_schema = tool.args_schema
    src_coroutine = tool.coroutine
    src_func = tool.func

    def _emit(
        persona: str | None,
        role: str | None,
        start: float,
        error: str | None,
    ) -> None:
        duration_ms = (time.perf_counter() - start) * 1000.0
        get_observability_provider().trace_tool_call(
            tool_name=name,
            tool_kind=tool_kind,
            persona=persona,
            role=role,
            duration_ms=duration_ms,
            error=error,
            metadata=None,
        )

    async def _traced_async(**kwargs: Any) -> Any:
        persona, role = get_assistant_ctx()
        start = time.perf_counter()
        try:
            if src_coroutine is not None:
                result = await src_coroutine(**kwargs)
            elif src_func is not None:
                # Run sync ``func`` in a worker thread to avoid blocking
                # the event loop. Mirrors LangChain's own ``ainvoke``
                # fallback for tools constructed from sync functions.
                result = await asyncio.to_thread(src_func, **kwargs)
            else:  # pragma: no cover — defensive: StructuredTool requires one
                raise RuntimeError(
                    f"Tool {name!r} has neither coroutine nor func"
                )
        except BaseException as exc:
            _emit(persona, role, start, type(exc).__name__)
            raise
        _emit(persona, role, start, None)
        return result

    def _traced_sync(**kwargs: Any) -> Any:
        """Sync entry point — only constructed when the source has
        ``func`` so we never invent sync support that the underlying
        tool does not provide.
        """
        persona, role = get_assistant_ctx()
        start = time.perf_counter()
        try:
            assert src_func is not None  # guarded by caller below
            result = src_func(**kwargs)
        except BaseException as exc:
            _emit(persona, role, start, type(exc).__name__)
            raise
        _emit(persona, role, start, None)
        return result

    # Match the source tool's invocation surface. ``StructuredTool.from_function``
    # accepts ``func=None`` and ``coroutine=None`` independently, but
    # requires at least one. Since ``_wrap`` is only called for real
    # StructuredTool instances (the isinstance gate above), at least
    # one of ``src_func`` / ``src_coroutine`` is present.
    sync_callable = _traced_sync if src_func is not None else None
    return StructuredTool.from_function(
        coroutine=_traced_async,
        func=sync_callable,
        name=name,
        description=description,
        args_schema=args_schema,
    )


def wrap_extension_tool(tool: Any) -> Any:
    """Wrap an extension-supplied StructuredTool with trace emission.

    Per spec ``extension-registry`` — every tool returned by
    ``Extension.as_langchain_tools()`` MUST have one ``trace_tool_call``
    span emitted per invocation with ``tool_kind="extension"``.

    Non-:class:`StructuredTool` inputs (e.g. ``unittest.mock.MagicMock``
    instances used by tests that don't construct real tools) pass
    through unchanged — wrapping them would raise inside
    ``StructuredTool.from_function`` because their ``args_schema`` is
    not a Pydantic model. The spec speaks of LangChain
    ``StructuredTool`` instances explicitly, so this passthrough does
    not deviate from the contract.
    """
    if not isinstance(tool, StructuredTool):
        return tool
    return _wrap(tool, tool_kind="extension")


def wrap_http_tool(tool: Any) -> Any:
    """Wrap an HTTP-discovered StructuredTool with trace emission.

    Per spec ``http-tools`` — every tool returned by the HTTP builder
    MUST emit one ``trace_tool_call`` per invocation with
    ``tool_kind="http"``. Non-StructuredTool inputs pass through
    unchanged for the same reason as :func:`wrap_extension_tool`.
    """
    if not isinstance(tool, StructuredTool):
        return tool
    return _wrap(tool, tool_kind="http")


def wrap_extension_tools(ext: Any) -> list[Any]:
    """Apply :func:`wrap_extension_tool` to each tool from an Extension.

    The two known aggregation sites (capability-resolver tools.py and
    DeepAgentsHarness.create_agent) call this helper rather than
    constructing their own loop, so the wrapping policy stays in one
    place per spec ``capability-resolver`` "Helper is the single source
    of truth".
    """
    return [wrap_extension_tool(t) for t in ext.as_langchain_tools()]


__all__ = [
    "wrap_extension_tool",
    "wrap_extension_tools",
    "wrap_http_tool",
]
