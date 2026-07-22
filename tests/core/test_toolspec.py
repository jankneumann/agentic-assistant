"""Tests for the ToolSpec core type (spec ``tool-spec``).

Scenarios: "ToolSpec captures an MCP-shaped tool", "Handler is async",
plus the ``tool_spec_from_model`` validation contract that the P17
migration relies on (validated coercion, provided-keys-only
forwarding so callable defaults keep applying).
"""

from __future__ import annotations

import inspect
import json

import pytest
from pydantic import BaseModel, Field, ValidationError

from assistant.core.toolspec import ToolSpec, tool_spec_from_model


def _spec() -> ToolSpec:
    async def _handler(query: str) -> str:
        return f"hit:{query}"

    return ToolSpec(
        name="search",
        description="Search things.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_handler,
        source="extension:test",
    )


def test_fields_are_typed_attributes() -> None:
    spec = _spec()
    assert spec.name == "search"
    assert spec.description == "Search things."
    assert spec.input_schema["type"] == "object"
    assert callable(spec.handler)
    assert spec.source == "extension:test"


def test_mcp_listing_triple_is_serializable() -> None:
    """(name, description, input_schema) serializes directly as an MCP
    tools/list entry."""
    listing = _spec().as_mcp_listing()
    assert listing == {
        "name": "search",
        "description": "Search things.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    json.dumps(listing)  # must not raise


@pytest.mark.asyncio
async def test_handler_is_async() -> None:
    spec = _spec()
    result = spec.handler(query="x")
    assert inspect.isawaitable(result)
    assert await result == "hit:x"


def test_with_handler_returns_copy_preserving_metadata() -> None:
    spec = _spec()

    async def _other(**kwargs: object) -> str:
        return "other"

    replaced = spec.with_handler(_other)
    assert replaced is not spec
    assert replaced.handler is _other
    assert replaced.name == spec.name
    assert replaced.input_schema == spec.input_schema
    assert spec.handler is not _other  # original untouched (frozen)


# ---------------------------------------------------------------------------
# tool_spec_from_model
# ---------------------------------------------------------------------------


class _Args(BaseModel):
    query: str = Field(..., description="What to search.")
    top: int = Field(25, ge=1)


def _from_model(calls: list[dict]) -> ToolSpec:
    async def _fn(query: str, top: int = 25) -> str:
        calls.append({"query": query, "top": top})
        return f"{query}:{top}"

    return tool_spec_from_model(
        name="t.search",
        description="d",
        args_model=_Args,
        handler=_fn,
        source="extension:t",
    )


def test_from_model_derives_json_schema() -> None:
    spec = _from_model([])
    assert spec.input_schema == _Args.model_json_schema()
    assert "query" in spec.input_schema["properties"]


@pytest.mark.asyncio
async def test_from_model_validates_and_coerces() -> None:
    calls: list[dict] = []
    spec = _from_model(calls)
    out = await spec.handler(query="x", top="7")  # str → int coercion
    assert out == "x:7"
    assert calls == [{"query": "x", "top": 7}]


@pytest.mark.asyncio
async def test_from_model_forwards_only_provided_keys() -> None:
    """Omitted optional args fall back to the callable's own default —
    LangChain StructuredTool parity."""
    calls: list[dict] = []
    spec = _from_model(calls)
    await spec.handler(query="x")
    assert calls == [{"query": "x", "top": 25}]


@pytest.mark.asyncio
async def test_from_model_rejects_invalid_args() -> None:
    spec = _from_model([])
    with pytest.raises(ValidationError):
        await spec.handler(top=3)  # missing required "query"
