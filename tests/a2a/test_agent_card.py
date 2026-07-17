"""Agent card builder tests — roles→skills, streaming, wire shape."""

from __future__ import annotations

from assistant.a2a.agent_card import build_agent_card
from assistant.a2a.types import A2A_PROTOCOL_VERSION
from tests.a2a.helpers import fixture_persona, fixture_roles


def test_one_skill_per_enabled_role():
    card = build_agent_card(
        fixture_persona(), fixture_roles(), base_url="http://127.0.0.1:8765"
    )
    assert [s.id for s in card.skills] == ["coder", "researcher"]
    coder = card.skills[0]
    assert coder.name == "Coder"
    assert coder.description == "Code analysis and implementation"
    assert "role" in coder.tags


def test_card_advertises_streaming_and_jsonrpc():
    card = build_agent_card(
        fixture_persona(), fixture_roles(), base_url="http://127.0.0.1:8765"
    )
    assert card.capabilities.streaming is True
    assert card.capabilities.push_notifications is False
    assert card.preferred_transport == "JSONRPC"
    assert card.url == "http://127.0.0.1:8765/a2a/v1"
    assert card.protocol_version == A2A_PROTOCOL_VERSION


def test_card_identity_from_persona():
    card = build_agent_card(
        fixture_persona(), fixture_roles(), base_url="http://127.0.0.1:8765"
    )
    assert card.name == "Fixture Persona"
    assert "fixture" in card.description


def test_card_version_override_and_default():
    card = build_agent_card(
        fixture_persona(),
        [],
        base_url="http://x",
        version="9.9.9",
    )
    assert card.version == "9.9.9"
    default = build_agent_card(fixture_persona(), [], base_url="http://x")
    assert default.version  # non-empty (package metadata or fallback)


def test_card_wire_shape_is_camel_case():
    card = build_agent_card(
        fixture_persona(), fixture_roles(), base_url="http://127.0.0.1:8765"
    )
    wire = card.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert wire["protocolVersion"] == A2A_PROTOCOL_VERSION
    assert wire["preferredTransport"] == "JSONRPC"
    assert wire["defaultInputModes"] == ["text/plain"]
    assert wire["capabilities"]["pushNotifications"] is False
    assert "protocol_version" not in wire
