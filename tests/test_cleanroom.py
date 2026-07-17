"""Clean-room declassification gateway tests (P26 knowledge-clean-room).

Exercised between the two public fixture personas
``cleanroom_alpha`` (source, share rules) and ``cleanroom_beta``
(consumer, accept rules); the DB-bound memory surface is a lightweight
in-memory fake satisfying the ``CleanRoomMemoryStore`` protocol.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from assistant.core import cleanroom as cr
from assistant.core.capabilities.guardrails import (
    ActionPolicy,
    AllowAllGuardrails,
    GuardrailConfig,
    PolicyGuardrails,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.persona import PersonaRegistry
from assistant.telemetry import factory

# ── Shared helpers ─────────────────────────────────────────────────────


class FakeMemoryManager:
    """In-memory CleanRoomMemoryStore fake (the real one is DB-bound)."""

    def __init__(
        self,
        facts: list[dict[str, Any]] | None = None,
        preferences: list[dict[str, Any]] | None = None,
        interactions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.facts = facts or []
        self.preferences = preferences or []
        self.interactions = interactions or []
        self.stored: dict[str, Any] = {}

    async def list_facts(
        self, persona: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self.facts[:limit]

    async def list_preferences(
        self, persona: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self.preferences[:limit]

    async def list_interactions(
        self, persona: str, role: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self.interactions[:limit]

    async def store_fact(self, persona: str, key: str, value: Any) -> None:
        self.stored[key] = value

    async def delete_facts_by_prefix(
        self, persona: str, key_prefix: str
    ) -> int:
        doomed = [k for k in self.stored if k.startswith(key_prefix)]
        for key in doomed:
            del self.stored[key]
        return len(doomed)


class _SpanSpy:
    def __init__(self) -> None:
        self.name = "spy"
        self.spans: list[tuple[str, dict]] = []

    def start_span(self, name, attributes=None):
        self.spans.append((name, dict(attributes or {})))
        return nullcontext()


@pytest.fixture
def span_spy(monkeypatch: pytest.MonkeyPatch) -> _SpanSpy:
    spy = _SpanSpy()
    monkeypatch.setattr(factory, "_provider", spy)
    return spy


@pytest.fixture
def alpha(personas_dir: Path):
    return PersonaRegistry(personas_dir).load("cleanroom_alpha")


@pytest.fixture
def beta(personas_dir: Path):
    return PersonaRegistry(personas_dir).load("cleanroom_beta")


@pytest.fixture
def isolated_persona(personas_dir: Path):
    """A persona with NO clean_room section (the fixture mirror)."""
    return PersonaRegistry(personas_dir).load("personal")


def _seeded_manager() -> FakeMemoryManager:
    """PII/secret-laced source memory for export tests."""
    return FakeMemoryManager(
        facts=[
            {
                "id": 1,
                "key": "project",
                "value": {
                    "name": "apollo",
                    "contact": "alice@example.com",
                    "api_key": "sk-abc123def456",
                },
                "updated_at": "2026-07-17T00:00:00+00:00",
            },
            {
                "id": 2,
                "key": "do-not-share-token",
                "value": "extremely private",
                "updated_at": "2026-07-17T00:00:00+00:00",
            },
        ],
        preferences=[
            {
                "id": 1,
                "category": "communication",
                "key": "tone",
                "value": "concise",
                "confidence": 0.9,
                "updated_at": "2026-07-17T00:00:00+00:00",
            }
        ],
        interactions=[
            {
                "id": 7,
                "role": "coder",
                "summary": "Emailed bob@example.com about standup",
                "created_at": "2026-07-17T00:00:00+00:00",
                "metadata": {},
            }
        ],
    )


def _make_item(item_id: str, kind: str, content: str, **extra: Any) -> dict:
    return {
        "item_id": item_id,
        "kind": kind,
        "key": item_id,
        "content": content,
        "content_hash": cr.content_hash(content),
        **extra,
    }


def _make_bundle(
    source: str,
    audience: str,
    items: list[dict],
    profile: str = "standard",
    bundle_id: str = "deadbeef" * 4,
) -> dict:
    payload = {
        "format": cr.BUNDLE_FORMAT,
        "version": cr.BUNDLE_VERSION,
        "bundle_id": bundle_id,
        "source_persona": source,
        "audience": audience,
        "profile": profile,
        "exported_at": "2026-07-17T00:00:00+00:00",
        "exporter": {
            "persona": source,
            "role": "chief_of_staff",
            "delegation_chain": [],
            "session_id": "",
            "issued_at": "2026-07-17T00:00:00+00:00",
        },
        "items": items,
    }
    payload["bundle_hash"] = cr.compute_bundle_hash(payload)
    return payload


# ── Config parsing ─────────────────────────────────────────────────────


class TestParseCleanRoomConfig:
    def test_none_and_empty_yield_falsy_config(self):
        assert not cr.parse_clean_room_config(None)
        assert not cr.parse_clean_room_config({})

    def test_valid_config_parses(self):
        config = cr.parse_clean_room_config(
            {
                "space_dir": "/tmp/space",
                "share": [
                    {
                        "audience": ["beta", "external"],
                        "kinds": ["facts"],
                        "exclude": ["*secret*"],
                        "profile": "secrets",
                    }
                ],
                "accept": [
                    {"from": ["alpha"], "kinds": ["facts"], "profiles": []}
                ],
            }
        )
        assert config
        assert config.space_dir == Path("/tmp/space")
        assert config.share[0].audience == ["beta", "external"]
        assert config.share[0].include == ["*"]
        assert config.share[0].profile == "secrets"
        assert config.accept[0].from_personas == ["alpha"]

    def test_unknown_top_level_key_rejected(self):
        with pytest.raises(cr.CleanRoomConfigError, match="unknown keys"):
            cr.parse_clean_room_config({"shares": []})

    def test_unknown_kind_rejected(self):
        with pytest.raises(cr.CleanRoomConfigError, match="unknown kinds"):
            cr.parse_clean_room_config(
                {"share": [{"audience": ["b"], "kinds": ["dreams"]}]}
            )

    def test_unknown_profile_rejected(self):
        with pytest.raises(cr.CleanRoomConfigError, match="profile"):
            cr.parse_clean_room_config(
                {
                    "share": [
                        {
                            "audience": ["b"],
                            "kinds": ["facts"],
                            "profile": "nope",
                        }
                    ]
                }
            )

    def test_accept_requires_from(self):
        with pytest.raises(cr.CleanRoomConfigError, match="from"):
            cr.parse_clean_room_config({"accept": [{"kinds": ["facts"]}]})

    def test_accept_unknown_profiles_rejected(self):
        with pytest.raises(cr.CleanRoomConfigError, match="unknown profiles"):
            cr.parse_clean_room_config(
                {
                    "accept": [
                        {
                            "from": ["a"],
                            "kinds": ["facts"],
                            "profiles": ["bogus"],
                        }
                    ]
                }
            )

    def test_share_rule_unknown_key_rejected(self):
        with pytest.raises(cr.CleanRoomConfigError, match="share\\[0\\]"):
            cr.parse_clean_room_config(
                {
                    "share": [
                        {"audience": ["b"], "kinds": ["facts"], "oops": 1}
                    ]
                }
            )


class TestPersonaWiring:
    def test_fixture_personas_load_clean_room(self, alpha, beta):
        assert alpha.clean_room
        assert alpha.clean_room.share[0].audience == ["cleanroom_beta"]
        assert alpha.clean_room.share[0].profile == "standard"
        assert beta.clean_room.accept[0].from_personas == ["cleanroom_alpha"]

    def test_persona_without_section_is_isolated(self, isolated_persona):
        assert not isolated_persona.clean_room

    def test_invalid_section_fails_persona_load(self, tmp_path: Path):
        pdir = tmp_path / "badcr"
        pdir.mkdir()
        (pdir / "persona.yaml").write_text(
            "name: badcr\nclean_room:\n  share:\n"
            "    - audience: [x]\n      kinds: [dreams]\n"
        )
        with pytest.raises(ValueError, match="clean_room"):
            PersonaRegistry(tmp_path).load("badcr")


# ── Sanitization profiles ──────────────────────────────────────────────


class TestSanitizationProfiles:
    def test_standard_redacts_pii_and_secrets(self):
        text = (
            "mail alice@example.com, call +1 (415) 555-0123 or "
            "415-555-0123, ssn 123-45-6789, ip 10.0.0.1, "
            "card 4111 1111 1111 1111, key sk-abc123"
        )
        out = cr.apply_profile("standard", text)
        assert "alice@example.com" not in out
        assert "555-0123" not in out
        assert "123-45-6789" not in out
        assert "10.0.0.1" not in out
        assert "4111" not in out
        assert "sk-abc123" not in out
        assert "EMAIL-REDACTED" in out
        assert "PHONE-REDACTED" in out
        assert "SSN-REDACTED" in out
        assert "IP-REDACTED" in out
        assert "CARD-REDACTED" in out
        assert "SK-REDACTED" in out

    def test_secrets_profile_keeps_pii_but_redacts_secrets(self):
        out = cr.apply_profile(
            "secrets", "alice@example.com uses sk-abc123"
        )
        assert "alice@example.com" in out
        assert "sk-abc123" not in out

    def test_unknown_profile_raises(self):
        with pytest.raises(cr.CleanRoomConfigError, match="unknown"):
            cr.apply_profile("bogus", "text")


# ── Export ─────────────────────────────────────────────────────────────


class TestExport:
    @pytest.mark.asyncio
    async def test_export_writes_sanitized_provenance_bundle(
        self, alpha, tmp_path: Path
    ):
        manager = _seeded_manager()
        result = await cr.export_shared(
            alpha,
            "cleanroom_beta",
            manager,
            guardrails=AllowAllGuardrails(),
            space_dir=tmp_path,
        )
        assert result.path.is_file()
        assert result.path.parent == tmp_path / "cleanroom_beta"

        raw = result.path.read_text(encoding="utf-8")
        # Sanitization actually happened on the seeded PII/secrets.
        assert "alice@example.com" not in raw
        assert "sk-abc123def456" not in raw
        assert "EMAIL-REDACTED" in raw

        payload = cr.verify_bundle(json.loads(raw))  # round-trips intact
        assert payload["source_persona"] == "cleanroom_alpha"
        assert payload["audience"] == "cleanroom_beta"
        assert payload["profile"] == "standard"
        assert payload["exporter"]["persona"] == "cleanroom_alpha"

        ids = {item["item_id"] for item in payload["items"]}
        assert "fact:project" in ids
        assert "pref:communication:tone" in ids
        # exclude glob filtered the do-not-share fact out.
        assert not any("do-not-share" in i for i in ids)
        # interactions are not in the share rule's kinds.
        assert not any(i.startswith("interaction:") for i in ids)
        assert result.item_count == len(payload["items"]) == 2

    @pytest.mark.asyncio
    async def test_no_clean_room_section_refuses_export(
        self, isolated_persona, tmp_path: Path
    ):
        with pytest.raises(cr.CleanRoomDenied, match="no clean_room"):
            await cr.export_shared(
                isolated_persona,
                "cleanroom_beta",
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_uncovered_audience_refuses_export(
        self, alpha, tmp_path: Path
    ):
        with pytest.raises(cr.CleanRoomDenied, match="no clean_room share rule"):
            await cr.export_shared(
                alpha,
                "somebody_else",
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_guardrail_deny_blocks_export(self, alpha, tmp_path: Path):
        guardrails = PolicyGuardrails(
            GuardrailConfig(
                policies=[
                    ActionPolicy(
                        action_type="cleanroom_export",
                        effect="deny",
                        reason="locked down",
                    )
                ]
            ),
            persona="cleanroom_alpha",
        )
        with pytest.raises(cr.CleanRoomDenied, match="locked down"):
            await cr.export_shared(
                alpha,
                "cleanroom_beta",
                _seeded_manager(),
                guardrails=guardrails,
                space_dir=tmp_path,
            )
        assert not (tmp_path / "cleanroom_beta").exists()

    @pytest.mark.asyncio
    async def test_require_confirmation_denies_until_interrupt_flow(
        self, alpha, tmp_path: Path
    ):
        guardrails = PolicyGuardrails(
            GuardrailConfig(
                policies=[
                    ActionPolicy(
                        action_type="cleanroom_export",
                        effect="require_confirmation",
                    )
                ]
            ),
            persona="cleanroom_alpha",
        )
        with pytest.raises(cr.CleanRoomDenied, match="confirmation"):
            await cr.export_shared(
                alpha,
                "cleanroom_beta",
                _seeded_manager(),
                guardrails=guardrails,
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_export_emits_guardrail_and_cleanroom_spans(
        self, alpha, tmp_path: Path, span_spy: _SpanSpy
    ):
        identity = AgentIdentity(
            persona="cleanroom_alpha", role="chief_of_staff"
        )
        result = await cr.export_shared(
            alpha,
            "cleanroom_beta",
            _seeded_manager(),
            guardrails=AllowAllGuardrails(),
            identity=identity,
            space_dir=tmp_path,
        )
        names = [name for name, _ in span_spy.spans]
        assert "guardrail.decision" in names
        assert cr.CLEANROOM_EXPORT_SPAN in names
        attrs = dict(span_spy.spans)[cr.CLEANROOM_EXPORT_SPAN]
        assert attrs["bundle_id"] == result.bundle_id
        assert attrs["audience"] == "cleanroom_beta"
        assert attrs["item_count"] == 2
        assert attrs["outcome"] == "exported"
        # Identity-stamped.
        assert attrs["persona"] == "cleanroom_alpha"
        assert attrs["role"] == "chief_of_staff"


# ── Import ─────────────────────────────────────────────────────────────


async def _exported_bundle(alpha, tmp_path: Path) -> cr.ExportResult:
    return await cr.export_shared(
        alpha,
        "cleanroom_beta",
        _seeded_manager(),
        guardrails=AllowAllGuardrails(),
        space_dir=tmp_path,
    )


class TestImport:
    @pytest.mark.asyncio
    async def test_round_trip_import_stores_provenance_marked_facts(
        self, alpha, beta, tmp_path: Path
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        consumer = FakeMemoryManager()
        result = await cr.import_shared(
            beta,
            exported.path,
            consumer,
            guardrails=AllowAllGuardrails(),
            space_dir=tmp_path,
        )
        # Beta accepts facts only — the preference item is skipped.
        assert result.imported == 1
        assert result.skipped == 1
        assert result.source_persona == "cleanroom_alpha"

        key = cr.import_key(exported.bundle_id, "fact:project")
        assert key in consumer.stored
        stored = consumer.stored[key]
        assert stored["kind"] == "fact"
        assert "EMAIL-REDACTED" in stored["content"]
        prov = stored["provenance"]
        assert prov["source_persona"] == "cleanroom_alpha"
        assert prov["bundle_id"] == exported.bundle_id
        assert prov["profile"] == "standard"
        assert prov["exporter"]["persona"] == "cleanroom_alpha"

    @pytest.mark.asyncio
    async def test_import_emits_audit_span(
        self, alpha, beta, tmp_path: Path, span_spy: _SpanSpy
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        span_spy.spans.clear()
        await cr.import_shared(
            beta,
            exported.path,
            FakeMemoryManager(),
            guardrails=AllowAllGuardrails(),
            space_dir=tmp_path,
        )
        attrs = dict(span_spy.spans)[cr.CLEANROOM_IMPORT_SPAN]
        assert attrs["outcome"] == "imported"
        assert attrs["imported"] == 1
        assert attrs["skipped"] == 1

    @pytest.mark.asyncio
    async def test_no_clean_room_section_refuses_import(
        self, alpha, isolated_persona, tmp_path: Path
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        with pytest.raises(cr.CleanRoomDenied, match="no clean_room"):
            await cr.import_shared(
                isolated_persona,
                exported.path,
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_tampered_item_content_refused(
        self, alpha, beta, tmp_path: Path
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        payload = json.loads(exported.path.read_text())
        payload["items"][0]["content"] = "poisoned content"
        with pytest.raises(cr.BundleVerificationError, match="content-hash"):
            await cr.import_shared(
                beta,
                payload,
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_tampered_envelope_refused(
        self, alpha, beta, tmp_path: Path
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        payload = json.loads(exported.path.read_text())
        payload["source_persona"] = "someone_trusted"
        with pytest.raises(cr.BundleVerificationError, match="hash mismatch"):
            await cr.import_shared(
                beta,
                payload,
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_wrong_audience_refused(self, alpha, beta, tmp_path: Path):
        # Alpha's second rule exports to `external`; beta must not
        # be able to ingest a bundle addressed to someone else.
        exported = await cr.export_shared(
            alpha,
            "external",
            _seeded_manager(),
            guardrails=AllowAllGuardrails(),
            space_dir=tmp_path,
        )
        with pytest.raises(cr.CleanRoomDenied, match="addressed to audience"):
            await cr.import_shared(
                beta,
                exported.path,
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_unlisted_source_persona_refused(
        self, beta, tmp_path: Path
    ):
        payload = _make_bundle(
            "cleanroom_gamma",
            "cleanroom_beta",
            [_make_item("fact:x", "fact", "hello")],
        )
        with pytest.raises(cr.CleanRoomDenied, match="no clean_room accept"):
            await cr.import_shared(
                beta,
                payload,
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_untrusted_profile_refused(self, beta, tmp_path: Path):
        payload = _make_bundle(
            "cleanroom_alpha",
            "cleanroom_beta",
            [_make_item("fact:x", "fact", "hello")],
            profile="secrets",
        )
        with pytest.raises(cr.CleanRoomDenied, match="profile"):
            await cr.import_shared(
                beta,
                payload,
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_guardrail_deny_blocks_import(
        self, alpha, beta, tmp_path: Path
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        guardrails = PolicyGuardrails(
            GuardrailConfig(
                policies=[
                    ActionPolicy(
                        action_type="cleanroom_import",
                        effect="deny",
                        reason="quarantine",
                    )
                ]
            ),
            persona="cleanroom_beta",
        )
        consumer = FakeMemoryManager()
        with pytest.raises(cr.CleanRoomDenied, match="quarantine"):
            await cr.import_shared(
                beta,
                exported.path,
                consumer,
                guardrails=guardrails,
                space_dir=tmp_path,
            )
        assert consumer.stored == {}


# ── Revocation ─────────────────────────────────────────────────────────


class TestRevocation:
    @pytest.mark.asyncio
    async def test_revoked_bundle_refuses_import(
        self, alpha, beta, tmp_path: Path
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        record = cr.revoke(alpha, exported.bundle_id, space_dir=tmp_path)
        assert record.is_file()
        with pytest.raises(cr.BundleRevokedError, match="revoked"):
            await cr.import_shared(
                beta,
                exported.path,
                FakeMemoryManager(),
                guardrails=AllowAllGuardrails(),
                space_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_only_source_persona_may_revoke(
        self, alpha, beta, tmp_path: Path
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        with pytest.raises(cr.CleanRoomDenied, match="only"):
            cr.revoke(beta, exported.bundle_id, space_dir=tmp_path)

    def test_revoking_unknown_bundle_fails(self, alpha, tmp_path: Path):
        with pytest.raises(cr.CleanRoomError, match="not found"):
            cr.revoke(alpha, "nonexistent", space_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_purge_removes_imported_items_after_revocation(
        self, alpha, beta, tmp_path: Path, span_spy: _SpanSpy
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        consumer = FakeMemoryManager()
        await cr.import_shared(
            beta,
            exported.path,
            consumer,
            guardrails=AllowAllGuardrails(),
            space_dir=tmp_path,
        )
        assert len(consumer.stored) == 1

        cr.revoke(alpha, exported.bundle_id, space_dir=tmp_path)
        deleted = await cr.purge_revoked(
            beta, consumer, space_dir=tmp_path
        )
        assert deleted == 1
        assert consumer.stored == {}
        attrs = dict(span_spy.spans)[cr.CLEANROOM_PURGE_SPAN]
        assert attrs["bundle_id"] == exported.bundle_id
        assert attrs["deleted"] == 1

    @pytest.mark.asyncio
    async def test_purge_without_revocations_is_noop(
        self, beta, tmp_path: Path
    ):
        assert (
            await cr.purge_revoked(
                beta, FakeMemoryManager(), space_dir=tmp_path
            )
            == 0
        )

    @pytest.mark.asyncio
    async def test_revoke_emits_audit_span(
        self, alpha, tmp_path: Path, span_spy: _SpanSpy
    ):
        exported = await _exported_bundle(alpha, tmp_path)
        span_spy.spans.clear()
        cr.revoke(alpha, exported.bundle_id, space_dir=tmp_path)
        attrs = dict(span_spy.spans)[cr.CLEANROOM_REVOKE_SPAN]
        assert attrs["bundle_id"] == exported.bundle_id
        assert attrs["outcome"] == "revoked"


# ── Envelope verification unit tests ───────────────────────────────────


class TestVerifyBundle:
    def test_valid_bundle_passes(self):
        payload = _make_bundle(
            "a", "b", [_make_item("fact:x", "fact", "hi")]
        )
        assert cr.verify_bundle(payload) is payload

    def test_missing_fields_rejected(self):
        with pytest.raises(cr.BundleVerificationError, match="missing"):
            cr.verify_bundle({"format": cr.BUNDLE_FORMAT})

    def test_wrong_format_rejected(self):
        payload = _make_bundle("a", "b", [])
        payload["format"] = "something-else"
        payload["bundle_hash"] = cr.compute_bundle_hash(payload)
        with pytest.raises(cr.BundleVerificationError, match="format"):
            cr.verify_bundle(payload)

    def test_unsupported_version_rejected(self):
        payload = _make_bundle("a", "b", [])
        payload["version"] = 99
        payload["bundle_hash"] = cr.compute_bundle_hash(payload)
        with pytest.raises(cr.BundleVerificationError, match="version"):
            cr.verify_bundle(payload)

    def test_exporter_identity_required(self):
        payload = _make_bundle("a", "b", [])
        payload["exporter"] = {}
        payload["bundle_hash"] = cr.compute_bundle_hash(payload)
        with pytest.raises(cr.BundleVerificationError, match="exporter"):
            cr.verify_bundle(payload)

    def test_memory_manager_satisfies_store_protocol(self):
        assert isinstance(FakeMemoryManager(), cr.CleanRoomMemoryStore)

        from assistant.core.memory import MemoryManager

        manager = MemoryManager(session_factory=None)  # type: ignore[arg-type]
        assert isinstance(manager, cr.CleanRoomMemoryStore)
