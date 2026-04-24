"""Unit tests for :mod:`assistant.http_tools.openapi`.

Covers the "OpenAPI Operation Parsing" requirement scenarios:
- with / without ``operationId``
- intra-document ``$ref`` resolution (including nested)
- external ``$ref`` skipped with warning
- cyclic ``$ref`` raises

Plus a drift-protection test that validates the 3.x fixtures with
``openapi-spec-validator``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pytest

from assistant.http_tools.openapi import (
    ParsedOperation,
    _resolve_ref,
    _synth_operation_id,
    parse_operations,
)

# ── operationId handling ─────────────────────────────────────────────


def test_operation_with_operation_id_preserved(
    load_fixture: Callable[[str], dict[str, Any]],
) -> None:
    """When the OpenAPI operation declares an ``operationId``, keep it."""
    spec = load_fixture("sample_openapi_v3_1.json")
    ops = {op.operation_id: op for op in parse_operations(spec)}
    assert "list_items" in ops
    assert "create_item" in ops
    assert "get_item" in ops


def test_operation_without_operation_id_synthesized() -> None:
    """Missing ``operationId`` produces a deterministic method_path slug."""
    assert _synth_operation_id("GET", "/items/{id}/history") == "get_items_id_history"
    assert _synth_operation_id("POST", "/users") == "post_users"
    assert _synth_operation_id("delete", "/a/b-c/d") == "delete_a_b_c_d"


def test_operation_without_id_round_trips_through_walker() -> None:
    """The walker synthesizes an id when the operation lacks one."""
    spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "paths": {
            "/items/{id}/history": {
                "get": {"summary": "History", "responses": {"200": {"description": "ok"}}},
            },
        },
    }
    ops = list(parse_operations(spec))
    assert len(ops) == 1
    assert ops[0].operation_id == "get_items_id_history"


# ── intra-document $ref resolution ───────────────────────────────────


def test_intra_ref_resolved(
    load_fixture: Callable[[str], dict[str, Any]],
) -> None:
    """POST /items requestBody ``$ref: #/components/schemas/ItemCreate``
    resolves inline to the ItemCreate schema (name, quantity).
    """
    spec = load_fixture("sample_openapi_v3_1.json")
    ops = {op.operation_id: op for op in parse_operations(spec)}
    create = ops["create_item"]
    schema = create.request_body_schema
    assert schema is not None
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"name", "quantity"}
    assert schema["properties"]["name"] == {"type": "string"}
    assert schema["required"] == ["name"]


def test_intra_ref_nested_recursively() -> None:
    """Refs inside the resolved schema's properties are also resolved."""
    spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "paths": {
            "/p": {
                "post": {
                    "operationId": "wrapper",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Outer"},
                            },
                        },
                    },
                    "responses": {"200": {"description": "ok"}},
                },
            },
        },
        "components": {
            "schemas": {
                "Outer": {
                    "type": "object",
                    "properties": {
                        "inner": {"$ref": "#/components/schemas/Inner"},
                    },
                },
                "Inner": {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                },
            },
        },
    }
    ops = list(parse_operations(spec))
    assert len(ops) == 1
    outer = ops[0].request_body_schema
    assert outer is not None
    # Outer.properties.inner was a ref; should now be the resolved Inner schema.
    inner = outer["properties"]["inner"]
    assert inner["type"] == "object"
    assert inner["properties"]["x"] == {"type": "integer"}


# ── external $ref — operation skipped with warning ───────────────────


def test_external_ref_skipped_with_warning(
    load_fixture: Callable[[str], dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An operation whose requestBody uses a non-``#/`` $ref is omitted.

    Spec scenario: "External $ref skipped with warning".
    """
    spec = load_fixture("external_ref_openapi.json")
    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.openapi"):
        ops = list(parse_operations(spec))
    assert ops == []
    assert any(
        "external" in record.getMessage().lower()
        for record in caplog.records
        if record.levelname == "WARNING"
    )


# ── cyclic $ref — raises ValueError surfaced as skip ─────────────────


def test_cyclic_ref_skips_operation_with_warning(
    load_fixture: Callable[[str], dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A → B → A chain raises ``ValueError`` which the walker catches.

    Spec scenario: "Cyclic $ref detected".
    """
    spec = load_fixture("cyclic_ref_openapi.json")
    with caplog.at_level(logging.WARNING, logger="assistant.http_tools.openapi"):
        ops = list(parse_operations(spec))
    assert ops == []
    assert any(
        "cyclic" in record.getMessage().lower()
        for record in caplog.records
        if record.levelname == "WARNING"
    )


def test_resolve_ref_external_raises() -> None:
    """Direct ``_resolve_ref`` call with an external ref raises."""
    with pytest.raises(ValueError, match="external"):
        _resolve_ref({}, "https://example.com/x.json", visited=set())


def test_resolve_ref_cyclic_raises() -> None:
    """Direct ``_resolve_ref`` call that revisits a ref raises."""
    spec: dict[str, Any] = {
        "components": {
            "schemas": {
                "A": {"type": "object", "properties": {"n": {"$ref": "#/components/schemas/B"}}},
                "B": {"type": "object", "properties": {"b": {"$ref": "#/components/schemas/A"}}},
            },
        },
    }
    with pytest.raises(ValueError, match="cyclic"):
        _resolve_ref(spec, "#/components/schemas/A", visited=set())


# ── Fixtures validate as real OpenAPI 3.x ────────────────────────────


def test_3x_fixtures_validate_as_openapi_spec(
    load_fixture: Callable[[str], dict[str, Any]],
) -> None:
    """Drift protection: 3.0 and 3.1 fixtures are valid OpenAPI docs.

    Deliberately excludes 1.3 (malformed) and 1.4 (Swagger 2.0 — meant
    to be rejected), plus cyclic/external-ref fixtures which are
    technically valid OpenAPI but would waste validator time.
    """
    from openapi_spec_validator import validate

    for name in ("sample_openapi_v3_0.json", "sample_openapi_v3_1.json"):
        spec = load_fixture(name)
        validate(spec)  # raises on drift


# ── ParsedOperation shape ────────────────────────────────────────────


def test_parsed_operation_carries_summary_and_parameters(
    load_fixture: Callable[[str], dict[str, Any]],
) -> None:
    """The walker populates method, path, summary, and parameters."""
    spec = load_fixture("sample_openapi_v3_1.json")
    ops = {op.operation_id: op for op in parse_operations(spec)}
    get_item = ops["get_item"]
    assert isinstance(get_item, ParsedOperation)
    assert get_item.method == "get"
    assert get_item.path == "/items/{id}"
    assert get_item.summary == "Fetch a single item by id."
    param_names = {p["name"] for p in get_item.parameters}
    assert param_names == {"id", "verbose"}
