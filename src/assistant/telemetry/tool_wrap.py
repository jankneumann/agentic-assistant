"""ToolSpec handler wrappers that emit ``trace_tool_call`` (D3).

Owned by ``wp-hooks``. Lives under ``assistant.telemetry`` for import
clarity but contains hook-integration logic, not the telemetry
contract surface.

P17 ``mcp-server-exposure`` moved the wrapping seam from LangChain
``StructuredTool`` instances to the harness-neutral
:class:`~assistant.core.toolspec.ToolSpec` layer: the traced handler
survives **every** rendering (LangChain, MSAF, MCP, direct handler
invocation) because the per-harness adapters are pure renderings that
call ``spec.handler``. Two public wrappers remain:

- :func:`wrap_tool_spec` — wrap one spec's handler; ``tool_kind`` is
  ``"extension"`` or ``"http"``.
- :func:`wrap_extension_tool_specs` — calls ``ext.tool_specs()`` once
  and wraps each yielded spec with ``tool_kind="extension"``. Used at
  the single extension-tool aggregation site named in the
  ``capability-resolver`` spec (``DefaultToolPolicy.authorized_tools``).

The HTTP builder applies :func:`wrap_tool_spec` (``tool_kind="http"``)
inside ``_build_tool`` so the wrapping stays transparent to
``discover_tools`` consumers.

Wrapping policy: the traced handler invokes the source handler inside
a ``perf_counter`` window, then emits exactly one ``trace_tool_call``
per invocation. On exception the span carries ``error=<type name>``
before the exception is re-raised. Name, description, and
``input_schema`` are preserved verbatim (the spec is copied via
``with_handler``), so agents and tool-discovery consumers see no
change in the public contract.
"""

from __future__ import annotations

import time
from typing import Any

from assistant.core.toolspec import ToolSpec
from assistant.telemetry.context import get_assistant_ctx
from assistant.telemetry.factory import get_observability_provider


def wrap_tool_spec(spec: Any, *, tool_kind: str) -> Any:
    """Return a copy of ``spec`` whose handler emits one trace per call.

    ``tool_kind`` is one of ``"extension"`` or ``"http"``; provider
    validation rejects any other value.

    Non-:class:`ToolSpec` inputs (e.g. ``unittest.mock.MagicMock``
    instances used by tests that don't construct real specs) pass
    through unchanged — mirroring the pre-P17 StructuredTool-level
    passthrough behavior.
    """
    if not isinstance(spec, ToolSpec):
        return spec

    name = spec.name
    src_handler = spec.handler

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

    async def _traced(**kwargs: Any) -> Any:
        persona, role = get_assistant_ctx()
        start = time.perf_counter()
        try:
            result = await src_handler(**kwargs)
        except BaseException as exc:
            _emit(persona, role, start, type(exc).__name__)
            raise
        _emit(persona, role, start, None)
        return result

    return spec.with_handler(_traced)


def wrap_extension_tool_specs(ext: Any) -> list[Any]:
    """Apply :func:`wrap_tool_spec` to each spec from an Extension.

    The single aggregation site (``DefaultToolPolicy.authorized_tools``
    in ``src/assistant/core/capabilities/tools.py``) calls this helper
    rather than constructing its own loop, so the wrapping policy stays
    in one place per spec ``capability-resolver`` "Helper is the single
    source of truth".
    """
    return [wrap_tool_spec(s, tool_kind="extension") for s in ext.tool_specs()]


def wrap_http_tool_spec(spec: Any) -> Any:
    """Wrap an HTTP-discovered ToolSpec with trace emission.

    Per spec ``http-tools`` — every tool built by the HTTP builder MUST
    emit one ``trace_tool_call`` per invocation with
    ``tool_kind="http"``.
    """
    return wrap_tool_spec(spec, tool_kind="http")


__all__ = [
    "wrap_extension_tool_specs",
    "wrap_http_tool_spec",
    "wrap_tool_spec",
]
