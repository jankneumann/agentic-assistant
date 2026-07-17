"""ToolSpec — the single internal, harness-neutral tool representation.

Spec ``tool-spec`` (archived ``capability-protocols-v2``; implemented by
P17 ``mcp-server-exposure``): every tool source — OpenAPI-derived HTTP
tools, extensions, served MCP tools — compiles into :class:`ToolSpec`,
and per-harness adapters (``assistant.harnesses.tool_adapters``) render
it to each harness's native shape. The field shape mirrors the MCP tool
schema (``name`` / ``description`` / JSON-Schema ``input_schema`` /
async ``handler``) so serving a ToolSpec over MCP is a transport
concern requiring no translation layer.

Argument validation lives in the handler, not in the renderings:
:func:`tool_spec_from_model` wraps a canonical async callable so every
surface (LangChain, MSAF, MCP, direct handler invocation) applies the
same Pydantic validation. Only the keys the caller actually provided
are forwarded to the underlying callable — mirroring LangChain's
``StructuredTool`` semantics so callable-signature defaults still
apply — while values are passed in their Pydantic-validated (coerced)
form.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel

ToolHandler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    """MCP-shaped, harness-neutral tool description plus async handler.

    Attributes:
        name: Canonical tool name — ``"{source}:{operation_id}"`` for
            HTTP tools, ``"<extension>.<verb>"`` for extension tools.
        description: Human/model-readable description.
        input_schema: JSON Schema **object** describing the tool's
            parameters (the MCP ``inputSchema`` shape).
        handler: Async callable executing the tool; invoked with
            keyword arguments valid against ``input_schema``.
        source: Provenance metadata (e.g. ``"extension:gmail"``,
            ``"http:backend"``, ``"mcp:serve"``).
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler = field(repr=False)
    source: str = ""

    def with_handler(self, handler: ToolHandler) -> ToolSpec:
        """Return a copy of this spec with ``handler`` swapped.

        Used by the telemetry layer to wrap handlers without mutating
        the (frozen) original spec.
        """
        return replace(self, handler=handler)

    def as_mcp_listing(self) -> dict[str, Any]:
        """The (name, description, inputSchema) triple as an MCP
        ``tools/list`` entry — directly serializable."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def tool_spec_from_model(
    *,
    name: str,
    description: str,
    args_model: type[BaseModel],
    handler: ToolHandler,
    source: str,
) -> ToolSpec:
    """Compile a Pydantic-args async callable into a :class:`ToolSpec`.

    The returned spec's handler validates incoming kwargs against
    ``args_model`` and forwards **only the provided keys** (validated /
    coerced) to ``handler`` — byte-compatible with how LangChain's
    ``StructuredTool`` invoked the same callables before the ToolSpec
    migration, so callable-signature defaults keep applying when a key
    is omitted.
    """

    async def _validated(**kwargs: Any) -> Any:
        parsed = args_model.model_validate(kwargs)
        dumped = parsed.model_dump()
        return await handler(**{k: dumped[k] for k in kwargs if k in dumped})

    return ToolSpec(
        name=name,
        description=description,
        input_schema=args_model.model_json_schema(),
        handler=_validated,
        source=source,
    )


__all__ = ["ToolHandler", "ToolSpec", "tool_spec_from_model"]
