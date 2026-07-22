"""Clean-room knowledge declassification gateway — P26 knowledge-clean-room.

The runtime analogue of the test-time privacy boundary (ADR-0004):
personas are execution boundaries, and NOTHING crosses between them by
default. A persona that wants to share memory declares an explicit
``clean_room:`` section; everything that leaves flows through this
gateway:

    source persona memory → share rules → sanitization profile →
    provenance envelope (share bundle) → shared space directory →
    accept rules → consuming persona memory (provenance retained)

Design pillars (see openspec/changes/knowledge-clean-room/design.md):

- **No config, no sharing.** A persona without ``clean_room:`` can
  neither export nor import — today's total isolation is the default.
- **Sanitization reuses the telemetry redaction chain** (D5 secret
  patterns in ``telemetry/sanitize.py``) as the base layer of every
  named profile; profiles add PII patterns on top. The telemetry
  module itself is untouched — its 15-pattern list is bound to the
  observability spec.
- **Per-item provenance**: every exported item carries a content hash;
  the bundle carries source persona, profile, exporter
  :class:`AgentIdentity`, and a whole-bundle hash. Import verifies all
  of it before anything is stored.
- **Imported knowledge is quarantined as facts**: regardless of the
  source kind (fact / preference / interaction), the consumer stores
  one provenance-wrapped fact per item under
  ``cleanroom/<bundle_id>/<item_id>`` — foreign preferences never
  become native preferences, and revocation is a key-prefix delete.
- **Revocation**: the source persona writes a revocation record into
  the shared space; import refuses revoked bundles, and
  :func:`purge_revoked` removes already-imported items on the
  consumer's next sync.
- **Guardrails + audit**: export/import are guardrail actions
  (``cleanroom_export`` / ``cleanroom_import``) so ``PolicyGuardrails``
  can deny or require confirmation (which DENIES until the approval
  interrupt flow exists — P13 semantics). Every export/import/revoke/
  purge emits a ``cleanroom.<op>`` span through the telemetry
  ``start_span`` escape hatch, identity-stamped, mirroring the P25
  ``guardrail.decision`` precedent.

The bundle JSON format IS the interop surface for external agents
(A2A peers, MCP clients) for now — transporting bundles over A2A/MCP
is a recorded follow-up, and the envelope is self-contained so it can
travel.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from assistant.core.capabilities.audit import emit_guardrail_audit
from assistant.core.capabilities.guardrails import (
    AllowAllGuardrails,
    GuardrailConfig,
    GuardrailProvider,
    PolicyGuardrails,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.types import ActionRequest
from assistant.telemetry.sanitize import sanitize

if TYPE_CHECKING:
    from assistant.core.persona import PersonaConfig

logger = logging.getLogger(__name__)


@runtime_checkable
class CleanRoomMemoryStore(Protocol):
    """Structural slice of :class:`MemoryManager` the gateway consumes.

    A Protocol (rather than the concrete manager) so tests can inject
    lightweight in-memory fakes for the DB-bound surface; the real
    ``MemoryManager`` satisfies it structurally.
    """

    async def list_facts(
        self, persona: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    async def list_preferences(
        self, persona: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    async def list_interactions(
        self, persona: str, role: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]: ...

    async def store_fact(self, persona: str, key: str, value: Any) -> None: ...

    async def delete_facts_by_prefix(
        self, persona: str, key_prefix: str
    ) -> int: ...

# ── Errors ─────────────────────────────────────────────────────────────


class CleanRoomError(Exception):
    """Base class for clean-room gateway failures."""


class CleanRoomConfigError(CleanRoomError, ValueError):
    """A persona ``clean_room:`` section failed validation at load time."""


class CleanRoomDenied(CleanRoomError):
    """An export/import was refused (policy, guardrail, or no config)."""


class BundleVerificationError(CleanRoomError):
    """A share bundle failed provenance-envelope verification."""


class BundleRevokedError(CleanRoomError):
    """The bundle has a revocation record in the shared space."""


# ── Sanitization profiles ──────────────────────────────────────────────
#
# Every profile starts from the telemetry secret-redaction chain
# (``telemetry/sanitize.py`` — the 15-pattern D5 list) and layers
# additional PII patterns on top. The telemetry module's API is
# redaction-fixed (its list is bound to the observability spec), so the
# named-profile layer lives HERE, not there.

_PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Email addresses.
    (
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "EMAIL-REDACTED",
    ),
    # US-style SSNs (before the phone rules — 3-2-4 grouping).
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN-REDACTED"),
    # Payment-card-shaped digit groups (before phone rules).
    (re.compile(r"\b(?:\d{4}[ -]){3}\d{4}\b"), "CARD-REDACTED"),
    # IPv4 addresses.
    (
        re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
        "IP-REDACTED",
    ),
    # International phone numbers (+ prefix, 8+ digits with separators).
    (re.compile(r"\+\d[\d\s().-]{6,}\d"), "PHONE-REDACTED"),
    # US-style phone numbers (3-3-4 with separators).
    (re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b"), "PHONE-REDACTED"),
)

#: Named sanitization profiles: profile name → extra pattern chain
#: applied AFTER the telemetry secret chain. ``secrets`` is the base
#: chain alone; ``standard`` (the default) adds the PII patterns.
SANITIZATION_PROFILES: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "secrets": (),
    "standard": _PII_PATTERNS,
}

DEFAULT_PROFILE = "standard"


def apply_profile(profile: str, text: str) -> str:
    """Sanitize ``text`` under the named profile.

    Always runs the telemetry secret-redaction chain first, then the
    profile's additional patterns. Pure function; unknown profile names
    raise :class:`CleanRoomConfigError` (parse validates them up front,
    so hitting this at runtime means a hand-built config).
    """
    try:
        extra = SANITIZATION_PROFILES[profile]
    except KeyError:
        raise CleanRoomConfigError(
            f"clean_room: unknown sanitization profile {profile!r}. "
            f"Known profiles: {sorted(SANITIZATION_PROFILES)}."
        ) from None
    out = sanitize(text)
    for pattern, replacement in extra:
        out = pattern.sub(replacement, out)
    return out


# ── Configuration (persona ``clean_room:`` section) ───────────────────

#: Memory kinds a rule may name. Plural in config (mirrors the memory
#: tables); items carry the singular form in ``kind``.
VALID_KINDS = ("facts", "preferences", "interactions")

#: Audience keyword for non-persona consumers (A2A/MCP peers). Bundles
#: exported to ``external`` are never importable by a local persona.
EXTERNAL_AUDIENCE = "external"

#: Default shared-space directory (git-ignored), relative to the
#: process working directory unless the persona overrides ``space_dir``.
DEFAULT_SPACE_DIR = Path(".cleanroom")

#: Ceiling on rows read per memory kind during export.
EXPORT_READ_LIMIT = 200


@dataclass
class ShareRule:
    """One ordered declassification rule: what may LEAVE the persona."""

    audience: list[str]
    kinds: list[str]
    include: list[str] = field(default_factory=lambda: ["*"])
    exclude: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    profile: str = DEFAULT_PROFILE


@dataclass
class AcceptRule:
    """One ordered ingestion rule: what a consuming persona takes in."""

    from_personas: list[str]
    kinds: list[str]
    #: Sanitization profiles this consumer trusts. Empty = any profile.
    profiles: list[str] = field(default_factory=list)


@dataclass
class CleanRoomConfig:
    """Parsed persona ``clean_room:`` section.

    Falsy (the default) when the persona declares no clean-room rules —
    the gateway then refuses every export AND import, preserving total
    persona isolation.
    """

    share: list[ShareRule] = field(default_factory=list)
    accept: list[AcceptRule] = field(default_factory=list)
    space_dir: Path | None = None

    def __bool__(self) -> bool:
        return bool(self.share or self.accept)


def _require_str_list(raw: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if raw is None:
        raw = []
    if not isinstance(raw, list) or not all(
        isinstance(x, str) and x for x in raw
    ):
        raise CleanRoomConfigError(
            f"clean_room: {label} must be a list of non-empty strings."
        )
    if not raw and not allow_empty:
        raise CleanRoomConfigError(
            f"clean_room: {label} must not be empty."
        )
    return list(raw)


def _parse_kinds(raw: Any, label: str) -> list[str]:
    kinds = _require_str_list(raw, label)
    unknown = sorted(set(kinds) - set(VALID_KINDS))
    if unknown:
        raise CleanRoomConfigError(
            f"clean_room: {label} has unknown kinds {unknown}. "
            f"Valid kinds: {list(VALID_KINDS)}."
        )
    return kinds


def parse_clean_room_config(raw: Any) -> CleanRoomConfig:
    """Parse and validate a persona ``clean_room:`` section.

    Actionable-error posture (same as ``guardrails:`` / ``models:``):
    unknown keys, unknown kinds, and unknown sanitization profiles fail
    with :class:`CleanRoomConfigError` naming the offender, surfaced by
    persona load. ``None``/``{}`` yields the falsy default config.
    """
    if not raw:
        return CleanRoomConfig()
    if not isinstance(raw, dict):
        raise CleanRoomConfigError(
            f"clean_room: expected a mapping, got {type(raw).__name__}."
        )
    unknown = sorted(set(raw) - {"share", "accept", "space_dir"})
    if unknown:
        raise CleanRoomConfigError(
            f"clean_room: unknown keys {unknown}. Expected 'share:', "
            f"'accept:', and/or 'space_dir:'."
        )

    share: list[ShareRule] = []
    raw_share = raw.get("share") or []
    if not isinstance(raw_share, list):
        raise CleanRoomConfigError(
            f"clean_room: share must be a list, got "
            f"{type(raw_share).__name__}."
        )
    for i, entry in enumerate(raw_share):
        if not isinstance(entry, dict):
            raise CleanRoomConfigError(
                f"clean_room: share[{i}] must be a mapping."
            )
        unknown_keys = sorted(
            set(entry)
            - {"audience", "kinds", "include", "exclude", "categories", "profile"}
        )
        if unknown_keys:
            raise CleanRoomConfigError(
                f"clean_room: share[{i}] has unknown keys {unknown_keys}. "
                f"Allowed: ['audience', 'categories', 'exclude', "
                f"'include', 'kinds', 'profile']."
            )
        profile = entry.get("profile", DEFAULT_PROFILE)
        if profile not in SANITIZATION_PROFILES:
            raise CleanRoomConfigError(
                f"clean_room: share[{i}] profile {profile!r} is not one of "
                f"{sorted(SANITIZATION_PROFILES)}."
            )
        share.append(
            ShareRule(
                audience=_require_str_list(
                    entry.get("audience"), f"share[{i}].audience"
                ),
                kinds=_parse_kinds(entry.get("kinds"), f"share[{i}].kinds"),
                include=_require_str_list(
                    entry.get("include", ["*"]), f"share[{i}].include"
                ),
                exclude=_require_str_list(
                    entry.get("exclude", []),
                    f"share[{i}].exclude",
                    allow_empty=True,
                ),
                categories=_require_str_list(
                    entry.get("categories", []),
                    f"share[{i}].categories",
                    allow_empty=True,
                ),
                profile=profile,
            )
        )

    accept: list[AcceptRule] = []
    raw_accept = raw.get("accept") or []
    if not isinstance(raw_accept, list):
        raise CleanRoomConfigError(
            f"clean_room: accept must be a list, got "
            f"{type(raw_accept).__name__}."
        )
    for i, entry in enumerate(raw_accept):
        if not isinstance(entry, dict):
            raise CleanRoomConfigError(
                f"clean_room: accept[{i}] must be a mapping."
            )
        unknown_keys = sorted(set(entry) - {"from", "kinds", "profiles"})
        if unknown_keys:
            raise CleanRoomConfigError(
                f"clean_room: accept[{i}] has unknown keys {unknown_keys}. "
                f"Allowed: ['from', 'kinds', 'profiles']."
            )
        profiles = _require_str_list(
            entry.get("profiles", []), f"accept[{i}].profiles", allow_empty=True
        )
        unknown_profiles = sorted(
            set(profiles) - set(SANITIZATION_PROFILES)
        )
        if unknown_profiles:
            raise CleanRoomConfigError(
                f"clean_room: accept[{i}] has unknown profiles "
                f"{unknown_profiles}. Known: {sorted(SANITIZATION_PROFILES)}."
            )
        accept.append(
            AcceptRule(
                from_personas=_require_str_list(
                    entry.get("from"), f"accept[{i}].from"
                ),
                kinds=_parse_kinds(entry.get("kinds"), f"accept[{i}].kinds"),
                profiles=profiles,
            )
        )

    space_dir_raw = raw.get("space_dir")
    space_dir: Path | None = None
    if space_dir_raw is not None:
        if not isinstance(space_dir_raw, str) or not space_dir_raw:
            raise CleanRoomConfigError(
                "clean_room: space_dir must be a non-empty path string."
            )
        space_dir = Path(space_dir_raw)

    return CleanRoomConfig(share=share, accept=accept, space_dir=space_dir)


# ── Provenance envelope / share bundle ─────────────────────────────────

BUNDLE_FORMAT = "cleanroom-bundle"
BUNDLE_VERSION = 1

_REQUIRED_BUNDLE_KEYS = (
    "format",
    "version",
    "bundle_id",
    "source_persona",
    "audience",
    "profile",
    "exported_at",
    "exporter",
    "items",
    "bundle_hash",
)
_REQUIRED_ITEM_KEYS = ("item_id", "kind", "content", "content_hash")


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_hash(text: str) -> str:
    """Per-item provenance hash of sanitized content."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_bundle_hash(payload: dict[str, Any]) -> str:
    """Whole-bundle integrity hash over the canonical payload.

    Computed over every field except ``bundle_hash`` itself, with
    sorted keys and compact separators, so verification is independent
    of key order and whitespace.
    """
    body = {k: v for k, v in payload.items() if k != "bundle_hash"}
    return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()


def _identity_payload(identity: AgentIdentity) -> dict[str, Any]:
    return {
        "persona": identity.persona,
        "role": identity.role,
        "delegation_chain": list(identity.delegation_chain),
        "session_id": identity.session_id,
        "issued_at": identity.issued_at.isoformat(),
    }


def verify_bundle(payload: Any) -> dict[str, Any]:
    """Verify a share bundle's provenance envelope; return the payload.

    Checks: top-level shape and required keys, format/version, exporter
    identity fields, per-item required keys, per-item content hashes,
    and the whole-bundle hash. Raises
    :class:`BundleVerificationError` naming the first failure — the
    error message never echoes item content.
    """
    if not isinstance(payload, dict):
        raise BundleVerificationError(
            f"bundle payload must be a JSON object, got "
            f"{type(payload).__name__}."
        )
    missing = [k for k in _REQUIRED_BUNDLE_KEYS if k not in payload]
    if missing:
        raise BundleVerificationError(
            f"bundle is missing required fields {missing}."
        )
    if payload["format"] != BUNDLE_FORMAT:
        raise BundleVerificationError(
            f"bundle format {payload['format']!r} is not "
            f"{BUNDLE_FORMAT!r}."
        )
    if payload["version"] != BUNDLE_VERSION:
        raise BundleVerificationError(
            f"bundle version {payload['version']!r} is not supported "
            f"(expected {BUNDLE_VERSION})."
        )
    exporter = payload["exporter"]
    if not isinstance(exporter, dict) or not exporter.get("persona"):
        raise BundleVerificationError(
            "bundle exporter identity is missing or has no persona."
        )
    items = payload["items"]
    if not isinstance(items, list):
        raise BundleVerificationError("bundle items must be a list.")
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise BundleVerificationError(
                f"bundle items[{idx}] must be an object."
            )
        missing_item = [k for k in _REQUIRED_ITEM_KEYS if k not in item]
        if missing_item:
            raise BundleVerificationError(
                f"bundle items[{idx}] is missing fields {missing_item}."
            )
        if content_hash(str(item["content"])) != item["content_hash"]:
            raise BundleVerificationError(
                f"bundle items[{idx}] ({item['item_id']!r}) failed its "
                f"content-hash check — item content was altered after "
                f"export."
            )
    if compute_bundle_hash(payload) != payload["bundle_hash"]:
        raise BundleVerificationError(
            "bundle hash mismatch — the bundle was altered after export."
        )
    return payload


# ── Shared-space layout ────────────────────────────────────────────────


def resolve_space_dir(
    persona: PersonaConfig, space_dir: Path | str | None = None
) -> Path:
    """Resolve the shared-space root: explicit arg → persona config →
    :data:`DEFAULT_SPACE_DIR`."""
    if space_dir is not None:
        return Path(space_dir)
    configured = getattr(persona, "clean_room", None)
    if configured is not None and configured.space_dir is not None:
        return configured.space_dir
    return DEFAULT_SPACE_DIR


def bundle_path(space: Path, audience: str, bundle_id: str) -> Path:
    return space / audience / f"{bundle_id}.json"


def revocation_path(space: Path, bundle_id: str) -> Path:
    return space / "revocations" / f"{bundle_id}.json"


def is_revoked(space: Path, bundle_id: str) -> bool:
    return revocation_path(space, bundle_id).is_file()


def find_bundle(space: Path, bundle_id: str) -> Path | None:
    """Locate ``<bundle_id>.json`` under any audience directory."""
    if not space.is_dir():
        return None
    for candidate in sorted(space.glob(f"*/{bundle_id}.json")):
        if candidate.parent.name != "revocations":
            return candidate
    return None


# ── Guardrail + audit plumbing ─────────────────────────────────────────

CLEANROOM_EXPORT_SPAN = "cleanroom.export"
CLEANROOM_IMPORT_SPAN = "cleanroom.import"
CLEANROOM_REVOKE_SPAN = "cleanroom.revoke"
CLEANROOM_PURGE_SPAN = "cleanroom.purge"


def select_guardrails(persona: PersonaConfig) -> GuardrailProvider:
    """Mirror the capability resolver's guardrail selection for CLI paths.

    Personas with a truthy ``guardrails:`` config get
    :class:`PolicyGuardrails`; everyone else keeps
    :class:`AllowAllGuardrails` (pre-P13 behavior).
    """
    config = getattr(persona, "guardrails", None)
    if isinstance(config, GuardrailConfig) and config:
        return PolicyGuardrails(
            config,
            persona=getattr(persona, "name", ""),
            database_url=getattr(persona, "database_url", "") or "",
        )
    return AllowAllGuardrails()


def _emit_cleanroom_audit(
    span_name: str,
    attributes: dict[str, Any],
    identity: AgentIdentity | None,
) -> None:
    """Emit one clean-room audit span, identity-stamped when known.

    Same defensive posture as ``emit_guardrail_audit``: a failing
    telemetry provider logs a WARNING and never changes the gateway
    outcome.
    """
    attrs: dict[str, Any] = dict(attributes)
    if identity is not None:
        attrs.update(
            {
                "persona": identity.persona,
                "role": identity.role,
                "delegation_chain": list(identity.delegation_chain),
                "chain_depth": identity.chain_depth,
                "session_id": identity.session_id,
                "issued_at": identity.issued_at.isoformat(),
            }
        )
    try:
        from assistant.telemetry import get_observability_provider

        with get_observability_provider().start_span(
            span_name, attributes=attrs
        ):
            pass
    except Exception as exc:
        logger.warning(
            "clean-room audit record not emitted (%s); gateway outcome "
            "is unaffected",
            type(exc).__name__,
        )


def _check_gateway_action(
    guardrails: GuardrailProvider,
    action_type: str,
    resource: str,
    persona_name: str,
    identity: AgentIdentity | None,
    approvals: Any | None = None,
) -> None:
    """Run the guardrail hook for an export/import; deny raises.

    ``require_confirmation`` (P30 durable-sessions): with an
    ``approvals`` store (persona ``sessions: {durable: true}``) the
    operation SUSPENDS — a persisted ApprovalRequest is created and
    ``PendingApprovalError`` propagates to the CLI, which prints the
    resume instructions; after ``assistant approvals approve <id>``
    the retried export/import consumes the approval exactly once.
    WITHOUT a store the P13 deny fallback is preserved (approvals need
    the persona DB).
    """
    action = ActionRequest(
        action_type=action_type,
        resource=resource,
        persona=persona_name,
        role=identity.role if identity is not None else "",
        identity=identity,
    )
    decision = guardrails.check_action(action)
    emit_guardrail_audit(action, decision)
    if not decision.allowed:
        raise CleanRoomDenied(
            f"{action_type} to {resource!r} denied by guardrails: "
            f"{decision.reason or 'no reason given'}"
        )
    if decision.require_confirmation:
        if approvals is None:
            raise CleanRoomDenied(
                f"{action_type} to {resource!r} requires confirmation, "
                f"which DENIES without a durable approval store "
                f"(sessions: {{durable: true}} + database url — P13 "
                f"fallback semantics): {decision.reason or 'no reason given'}"
            )
        from assistant.core.capabilities.approvals import consume_or_suspend

        consume_or_suspend(
            approvals,
            action,
            decision,
            risk=guardrails.declare_risk(action),
        )


# ── Export ─────────────────────────────────────────────────────────────


@dataclass
class ExportResult:
    bundle_id: str
    path: Path
    item_count: int
    profile: str
    audience: str


def _matches_globs(patterns: list[str], *values: str) -> bool:
    return any(
        fnmatchcase(value, pattern)
        for pattern in patterns
        for value in values
    )


def _rule_for_audience(
    config: CleanRoomConfig, audience: str
) -> ShareRule | None:
    """First share rule naming the audience wins (declaration order)."""
    for rule in config.share:
        if audience in rule.audience:
            return rule
    return None


async def _collect_items(
    manager: CleanRoomMemoryStore, persona_name: str, rule: ShareRule
) -> list[dict[str, Any]]:
    """Read, filter, and sanitize the memory items a rule declassifies."""
    items: list[dict[str, Any]] = []

    def _admit(key: str, content: str) -> bool:
        if rule.exclude and _matches_globs(rule.exclude, key, content):
            return False
        return _matches_globs(rule.include, key, content)

    def _sanitized_item(
        item_id: str, kind: str, key: str, content: str, **extra: Any
    ) -> dict[str, Any]:
        clean_key = apply_profile(rule.profile, key)
        clean_content = apply_profile(rule.profile, content)
        return {
            "item_id": item_id,
            "kind": kind,
            "key": clean_key,
            "content": clean_content,
            "content_hash": content_hash(clean_content),
            **extra,
        }

    if "facts" in rule.kinds:
        for fact in await manager.list_facts(
            persona_name, limit=EXPORT_READ_LIMIT
        ):
            raw = json.dumps(fact["value"], ensure_ascii=False)
            if not _admit(fact["key"], raw):
                continue
            items.append(
                _sanitized_item(f"fact:{fact['key']}", "fact", fact["key"], raw)
            )

    if "preferences" in rule.kinds:
        for pref in await manager.list_preferences(
            persona_name, limit=EXPORT_READ_LIMIT
        ):
            if rule.categories and pref["category"] not in rule.categories:
                continue
            raw = json.dumps(pref["value"], ensure_ascii=False)
            if not _admit(pref["key"], raw):
                continue
            items.append(
                _sanitized_item(
                    f"pref:{pref['category']}:{pref['key']}",
                    "preference",
                    pref["key"],
                    raw,
                    category=pref["category"],
                    confidence=pref["confidence"],
                )
            )

    if "interactions" in rule.kinds:
        for inter in await manager.list_interactions(
            persona_name, limit=EXPORT_READ_LIMIT
        ):
            summary = str(inter["summary"])
            if not _admit(str(inter["id"]), summary):
                continue
            items.append(
                _sanitized_item(
                    f"interaction:{inter['id']}",
                    "interaction",
                    str(inter["id"]),
                    summary,
                    role=inter["role"],
                )
            )

    return items


async def export_shared(
    persona: PersonaConfig,
    audience: str,
    manager: CleanRoomMemoryStore,
    *,
    guardrails: GuardrailProvider,
    identity: AgentIdentity | None = None,
    space_dir: Path | str | None = None,
    now: datetime | None = None,
    approvals: Any | None = None,
) -> ExportResult:
    """Declassify persona memory into a share bundle for ``audience``.

    Refuses (raising :class:`CleanRoomDenied`) when the persona has no
    ``clean_room:`` section, when no share rule names the audience, or
    when the ``cleanroom_export`` guardrail action is denied /
    requires confirmation. On success writes
    ``<space>/<audience>/<bundle_id>.json`` and emits a
    ``cleanroom.export`` audit span.
    """
    config: CleanRoomConfig = getattr(
        persona, "clean_room", None
    ) or CleanRoomConfig()
    if not config:
        raise CleanRoomDenied(
            f"persona {persona.name!r} declares no clean_room: section — "
            f"nothing may leave this persona (total isolation is the "
            f"default)."
        )
    rule = _rule_for_audience(config, audience)
    if rule is None:
        raise CleanRoomDenied(
            f"persona {persona.name!r} has no clean_room share rule for "
            f"audience {audience!r} — export refused."
        )

    if identity is None:
        identity = AgentIdentity(
            persona=persona.name, role=getattr(persona, "default_role", "")
        )
    _check_gateway_action(
        guardrails,
        "cleanroom_export",
        audience,
        persona.name,
        identity,
        approvals=approvals,
    )

    items = await _collect_items(manager, persona.name, rule)

    exported_at = (now or datetime.now(UTC)).isoformat()
    payload: dict[str, Any] = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "bundle_id": uuid.uuid4().hex,
        "source_persona": persona.name,
        "audience": audience,
        "profile": rule.profile,
        "exported_at": exported_at,
        "exporter": _identity_payload(identity),
        "items": items,
    }
    payload["bundle_hash"] = compute_bundle_hash(payload)

    space = resolve_space_dir(persona, space_dir)
    path = bundle_path(space, audience, payload["bundle_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    _emit_cleanroom_audit(
        CLEANROOM_EXPORT_SPAN,
        {
            "bundle_id": payload["bundle_id"],
            "source_persona": persona.name,
            "audience": audience,
            "profile": rule.profile,
            "item_count": len(items),
            "outcome": "exported",
        },
        identity,
    )
    return ExportResult(
        bundle_id=payload["bundle_id"],
        path=path,
        item_count=len(items),
        profile=rule.profile,
        audience=audience,
    )


# ── Import ─────────────────────────────────────────────────────────────

#: Key prefix for imported facts; revocation deletes by this prefix.
IMPORT_KEY_PREFIX = "cleanroom/"


def import_key(bundle_id: str, item_id: str) -> str:
    return f"{IMPORT_KEY_PREFIX}{bundle_id}/{item_id}"


@dataclass
class ImportResult:
    bundle_id: str
    source_persona: str
    imported: int
    skipped: int


def _accept_rule_for(
    config: CleanRoomConfig, source_persona: str
) -> AcceptRule | None:
    """First accept rule whose ``from`` glob matches wins."""
    for rule in config.accept:
        if any(fnmatchcase(source_persona, p) for p in rule.from_personas):
            return rule
    return None


_SINGULAR_KIND = {
    "facts": "fact",
    "preferences": "preference",
    "interactions": "interaction",
}


async def import_shared(
    persona: PersonaConfig,
    bundle: Path | str | dict[str, Any],
    manager: CleanRoomMemoryStore,
    *,
    guardrails: GuardrailProvider,
    identity: AgentIdentity | None = None,
    space_dir: Path | str | None = None,
    approvals: Any | None = None,
) -> ImportResult:
    """Ingest a verified share bundle into the consuming persona.

    Verification order: provenance envelope (format, hashes, exporter)
    → revocation record → audience match (the bundle must be addressed
    to this persona) → accept rules (source persona glob + trusted
    profile) → ``cleanroom_import`` guardrail action. Accepted items
    are stored as provenance-wrapped facts under
    ``cleanroom/<bundle_id>/<item_id>``; items whose kind the accept
    rule does not admit are skipped (counted, not fatal).
    """
    config: CleanRoomConfig = getattr(
        persona, "clean_room", None
    ) or CleanRoomConfig()
    if not config:
        raise CleanRoomDenied(
            f"persona {persona.name!r} declares no clean_room: section — "
            f"it does not ingest shared knowledge (total isolation is "
            f"the default)."
        )

    if isinstance(bundle, (str, Path)):
        bundle_file = Path(bundle)
        try:
            payload_raw = json.loads(bundle_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BundleVerificationError(
                f"cannot read bundle at {bundle_file}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
    else:
        payload_raw = bundle

    payload = verify_bundle(payload_raw)
    bundle_id = payload["bundle_id"]
    source_persona = payload["source_persona"]

    space = resolve_space_dir(persona, space_dir)
    if is_revoked(space, bundle_id):
        _emit_cleanroom_audit(
            CLEANROOM_IMPORT_SPAN,
            {
                "bundle_id": bundle_id,
                "source_persona": source_persona,
                "outcome": "refused-revoked",
            },
            identity,
        )
        raise BundleRevokedError(
            f"bundle {bundle_id} from {source_persona!r} has been revoked "
            f"by its source persona — import refused."
        )

    if payload["audience"] != persona.name:
        raise CleanRoomDenied(
            f"bundle {bundle_id} is addressed to audience "
            f"{payload['audience']!r}, not to persona {persona.name!r} — "
            f"import refused."
        )

    rule = _accept_rule_for(config, source_persona)
    if rule is None:
        raise CleanRoomDenied(
            f"persona {persona.name!r} has no clean_room accept rule for "
            f"source persona {source_persona!r} — import refused."
        )
    if rule.profiles and payload["profile"] not in rule.profiles:
        raise CleanRoomDenied(
            f"bundle {bundle_id} was sanitized under profile "
            f"{payload['profile']!r}, but persona {persona.name!r} only "
            f"accepts {rule.profiles} from {source_persona!r} — import "
            f"refused."
        )

    if identity is None:
        identity = AgentIdentity(
            persona=persona.name, role=getattr(persona, "default_role", "")
        )
    _check_gateway_action(
        guardrails,
        "cleanroom_import",
        source_persona,
        persona.name,
        identity,
        approvals=approvals,
    )

    accepted_kinds = {_SINGULAR_KIND[k] for k in rule.kinds}
    imported = 0
    skipped = 0
    imported_at = datetime.now(UTC).isoformat()
    for item in payload["items"]:
        if item["kind"] not in accepted_kinds:
            skipped += 1
            continue
        value = {
            "content": item["content"],
            "kind": item["kind"],
            "provenance": {
                "source_persona": source_persona,
                "bundle_id": bundle_id,
                "item_id": item["item_id"],
                "content_hash": item["content_hash"],
                "profile": payload["profile"],
                "exported_at": payload["exported_at"],
                "exporter": payload["exporter"],
                "imported_at": imported_at,
            },
        }
        await manager.store_fact(
            persona.name, import_key(bundle_id, item["item_id"]), value
        )
        imported += 1

    _emit_cleanroom_audit(
        CLEANROOM_IMPORT_SPAN,
        {
            "bundle_id": bundle_id,
            "source_persona": source_persona,
            "profile": payload["profile"],
            "imported": imported,
            "skipped": skipped,
            "outcome": "imported",
        },
        identity,
    )
    return ImportResult(
        bundle_id=bundle_id,
        source_persona=source_persona,
        imported=imported,
        skipped=skipped,
    )


# ── Revocation ─────────────────────────────────────────────────────────


def revoke(
    persona: PersonaConfig,
    bundle_id: str,
    *,
    identity: AgentIdentity | None = None,
    space_dir: Path | str | None = None,
) -> Path:
    """Revoke a previously exported bundle (source persona only).

    Writes ``<space>/revocations/<bundle_id>.json``; import refuses
    revoked bundles, and consumers purge already-imported items via
    :func:`purge_revoked`. Revoking is the safety direction (it only
    removes access), so it needs no guardrail hook — but it is audited.
    """
    space = resolve_space_dir(persona, space_dir)
    found = find_bundle(space, bundle_id)
    if found is None:
        raise CleanRoomError(
            f"bundle {bundle_id!r} not found in shared space {space} — "
            f"nothing to revoke."
        )
    try:
        payload = json.loads(found.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BundleVerificationError(
            f"cannot read bundle at {found}: {type(exc).__name__}: {exc}"
        ) from exc
    source_persona = payload.get("source_persona", "")
    if source_persona != persona.name:
        raise CleanRoomDenied(
            f"bundle {bundle_id} was exported by {source_persona!r}; only "
            f"the source persona may revoke it (acting persona: "
            f"{persona.name!r})."
        )

    if identity is None:
        identity = AgentIdentity(
            persona=persona.name, role=getattr(persona, "default_role", "")
        )
    record = {
        "bundle_id": bundle_id,
        "source_persona": source_persona,
        "audience": payload.get("audience", ""),
        "revoked_at": datetime.now(UTC).isoformat(),
        "revoked_by": _identity_payload(identity),
    }
    path = revocation_path(space, bundle_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _emit_cleanroom_audit(
        CLEANROOM_REVOKE_SPAN,
        {
            "bundle_id": bundle_id,
            "source_persona": source_persona,
            "audience": record["audience"],
            "outcome": "revoked",
        },
        identity,
    )
    return path


async def purge_revoked(
    persona: PersonaConfig,
    manager: CleanRoomMemoryStore,
    *,
    identity: AgentIdentity | None = None,
    space_dir: Path | str | None = None,
) -> int:
    """Delete this persona's imported items for every revoked bundle.

    The consumer-side half of revocation: walks the shared space's
    ``revocations/`` records and removes any imported facts under the
    matching ``cleanroom/<bundle_id>/`` key prefix. Returns the number
    of deleted items; emits one ``cleanroom.purge`` span when anything
    was deleted.
    """
    space = resolve_space_dir(persona, space_dir)
    revocations_dir = space / "revocations"
    if not revocations_dir.is_dir():
        return 0
    if identity is None:
        identity = AgentIdentity(
            persona=persona.name, role=getattr(persona, "default_role", "")
        )
    total = 0
    for record_file in sorted(revocations_dir.glob("*.json")):
        bundle_id = record_file.stem
        deleted = await manager.delete_facts_by_prefix(
            persona.name, f"{IMPORT_KEY_PREFIX}{bundle_id}/"
        )
        if deleted:
            total += deleted
            _emit_cleanroom_audit(
                CLEANROOM_PURGE_SPAN,
                {
                    "bundle_id": bundle_id,
                    "deleted": deleted,
                    "outcome": "purged",
                },
                identity,
            )
    return total


__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "CLEANROOM_EXPORT_SPAN",
    "CLEANROOM_IMPORT_SPAN",
    "CLEANROOM_PURGE_SPAN",
    "CLEANROOM_REVOKE_SPAN",
    "DEFAULT_PROFILE",
    "DEFAULT_SPACE_DIR",
    "EXTERNAL_AUDIENCE",
    "IMPORT_KEY_PREFIX",
    "SANITIZATION_PROFILES",
    "VALID_KINDS",
    "AcceptRule",
    "BundleRevokedError",
    "BundleVerificationError",
    "CleanRoomConfig",
    "CleanRoomConfigError",
    "CleanRoomDenied",
    "CleanRoomError",
    "ExportResult",
    "ImportResult",
    "ShareRule",
    "apply_profile",
    "compute_bundle_hash",
    "content_hash",
    "export_shared",
    "find_bundle",
    "import_key",
    "import_shared",
    "is_revoked",
    "parse_clean_room_config",
    "purge_revoked",
    "resolve_space_dir",
    "revoke",
    "select_guardrails",
    "verify_bundle",
]
