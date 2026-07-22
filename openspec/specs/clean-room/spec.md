# clean-room Specification

## Purpose
TBD - created by archiving change knowledge-clean-room. Update Purpose after archive.
## Requirements
### Requirement: Clean-Room Configuration Section

The system SHALL parse an optional persona `clean_room:` section into
a `CleanRoomConfig` (in `core/cleanroom.py`) with ordered `share:`
rules (each with `audience:` — a non-empty list of persona names
and/or the literal `external`; `kinds:` — a non-empty subset of
`facts` / `preferences` / `interactions`; optional `include:` /
`exclude:` glob lists matched against item key or content, exclusions
winning; optional `categories:` for preferences; and a `profile:`
naming a known sanitization profile, default `standard`), ordered
`accept:` rules (each with `from:` — non-empty source-persona glob
list; `kinds:`; and optional `profiles:` listing trusted sanitization
profiles, empty meaning any), and an optional `space_dir:` path
override for the shared space. Validation MUST follow the
actionable-error posture: unknown keys, unknown kinds, and unknown
profile names fail persona load with an error naming the offender. A
missing/empty section MUST parse to a falsy default config, and a
persona with a falsy config MUST be refused by BOTH the export and
import gateways — total persona isolation is the default.

#### Scenario: Valid section parses into ordered rules

- **WHEN** a persona declares a `clean_room:` section with one share
  rule (`audience: [beta]`, `kinds: [facts]`) and one accept rule
  (`from: [alpha]`, `kinds: [facts]`)
- **THEN** persona load MUST succeed and expose a truthy
  `PersonaConfig.clean_room` carrying both rules

#### Scenario: Invalid section fails persona load actionably

- **WHEN** a persona declares a share rule with `kinds: [dreams]`
- **THEN** persona load MUST raise a `ValueError` naming the
  `clean_room:` section and the unknown kind

#### Scenario: No section means total isolation

- **WHEN** a persona declares no `clean_room:` section
- **THEN** `PersonaConfig.clean_room` MUST be falsy
- **AND** both `export_shared` and `import_shared` MUST refuse with a
  denial naming the missing section

### Requirement: Named Sanitization Profiles

The system SHALL sanitize every exported item (key and content) under
a named profile that ALWAYS applies the telemetry secret-redaction
chain (`telemetry/sanitize.py`, reused unchanged) first and then the
profile's additional patterns. The shipped profiles are `secrets`
(secret chain only) and `standard` (the default; secret chain plus
PII patterns covering at least email addresses, US-style SSNs,
payment-card digit groups, IPv4 addresses, and phone numbers).
Unknown profile names MUST be rejected at config parse time.

#### Scenario: Standard profile redacts PII and secrets

- **WHEN** content containing an email address, a phone number, and
  an `sk-` style API key is sanitized under `standard`
- **THEN** none of the raw values appear in the output
- **AND** the corresponding redaction markers do

#### Scenario: Secrets profile leaves PII but redacts secrets

- **WHEN** content containing an email address and an `sk-` style key
  is sanitized under `secrets`
- **THEN** the email address survives and the key is redacted

### Requirement: Share Bundle Provenance Envelope

The system SHALL wrap every export in a self-contained JSON share
bundle carrying `format` (`cleanroom-bundle`), `version` (`1`), a
unique `bundle_id`, `source_persona`, `audience`, `profile`,
`exported_at`, the serialized exporter `AgentIdentity` (persona,
role, delegation chain, session id, issued_at), `items` (each with
`item_id`, singular `kind`, sanitized `key` and `content`, and a
per-item `content_hash` over the sanitized content), and a
`bundle_hash` computed over the canonical sorted-keys JSON of every
other field. Verification (`verify_bundle`) MUST reject bundles with
missing fields, wrong format/version, a missing exporter persona, a
failed per-item content hash, or a failed whole-bundle hash — and its
error messages MUST NOT echo item content. Hashes are tamper
evidence, not authentication; cryptographic signing is deferred.

#### Scenario: Exported bundle verifies round-trip

- **WHEN** a bundle written by `export_shared` is re-read and passed
  to `verify_bundle`
- **THEN** verification MUST succeed

#### Scenario: Tampered item content is rejected

- **WHEN** an item's `content` is altered after export
- **THEN** `verify_bundle` MUST raise a verification error naming the
  item's content-hash failure

#### Scenario: Tampered envelope field is rejected

- **WHEN** the bundle's `source_persona` is altered after export
- **THEN** `verify_bundle` MUST raise a bundle-hash mismatch error

### Requirement: Clean-Room Export Gateway

The system SHALL provide `export_shared(persona, audience, manager,
*, guardrails, identity=None, space_dir=None)` in `core/cleanroom.py`
which selects the FIRST share rule whose audience list contains the
requested audience (refusing when none does or when the persona has
no clean-room config), reads the rule's kinds through the memory
store (structured `list_facts` / `list_preferences` /
`list_interactions` reads), applies include/exclude globs and
preference-category filters, sanitizes every admitted item under the
rule's profile, and writes the provenance-enveloped bundle to
`<space>/<audience>/<bundle_id>.json` in the shared space (default
`.cleanroom/`, git-ignored; overridable via persona `space_dir:` or
the explicit argument). Before reading memory the gateway MUST run
the `cleanroom_export` guardrail action (resource = audience,
identity attached — synthesized from persona name and default role
when not injected); a denial or a `require_confirmation` decision
MUST abort the export with nothing written — confirmation DENIES
until the approval interrupt flow exists (P13 semantics).

#### Scenario: Share rules filter and sanitize what leaves

- **WHEN** the source persona's rule shares `facts` and `preferences`
  with an `exclude` glob, and its memory contains a matching-excluded
  fact, PII-laced facts, and interactions
- **THEN** the written bundle contains the sanitized facts and
  preferences only
- **AND** the excluded fact and all interactions are absent
- **AND** the seeded PII does not appear anywhere in the bundle file

#### Scenario: Guardrail denial aborts the export

- **WHEN** a guardrail policy denies `cleanroom_export`
- **THEN** `export_shared` MUST raise a clean-room denial carrying the
  policy reason
- **AND** no bundle file may be written

#### Scenario: Uncovered audience is refused

- **WHEN** no share rule's audience list contains the requested
  audience
- **THEN** `export_shared` MUST refuse with an error naming the
  audience

### Requirement: Clean-Room Import Gateway

The system SHALL provide `import_shared(persona, bundle, manager, *,
guardrails, identity=None, space_dir=None)` which verifies the
provenance envelope, refuses bundles with a revocation record in the
shared space, refuses bundles whose `audience` is not the consuming
persona's name, selects the FIRST accept rule whose `from` glob
matches the bundle's `source_persona` (refusing when none matches,
when the persona has no clean-room config, or when the matched rule's
`profiles` list does not trust the bundle's profile), and runs the
`cleanroom_import` guardrail action (resource = source persona) with
the same deny/confirmation semantics as export. Accepted items MUST
be stored in the consumer's memory as facts keyed
`cleanroom/<bundle_id>/<item_id>` whose value retains the sanitized
content, the item kind, and the full provenance (source persona,
bundle id, item id, content hash, profile, export and import
timestamps, exporter identity); items whose kind the accept rule does
not admit are skipped and counted, not fatal.

#### Scenario: Round-trip import retains provenance

- **WHEN** a consumer whose accept rule admits `facts` from the
  source imports a verified bundle containing one fact and one
  preference
- **THEN** exactly one fact is stored under the
  `cleanroom/<bundle_id>/` key prefix with its provenance metadata
  (source persona, bundle id, profile, exporter) retained
- **AND** the preference item is reported as skipped

#### Scenario: Untrusted source or profile is refused

- **WHEN** the bundle's source persona matches no accept rule, OR the
  matched rule's `profiles` list does not contain the bundle's
  profile
- **THEN** `import_shared` MUST refuse and store nothing

#### Scenario: Bundle addressed to another audience is refused

- **WHEN** a persona imports a bundle whose `audience` names a
  different consumer (e.g. `external`)
- **THEN** `import_shared` MUST refuse with an error naming the
  addressed audience

### Requirement: Bundle Revocation and Purge

The system SHALL let ONLY the source persona revoke a bundle it
exported: `revoke(persona, bundle_id)` locates the bundle in the
shared space, verifies `source_persona` matches the acting persona,
and writes an identity-stamped revocation record to
`<space>/revocations/<bundle_id>.json`. `import_shared` MUST refuse
any bundle with a revocation record. `purge_revoked(persona,
manager)` MUST delete the consumer's already-imported items for every
revocation record via a `cleanroom/<bundle_id>/` key-prefix delete
and return the number of deleted items — the consumer-side half of
revocation, run on demand (`assistant cleanroom sync`).

#### Scenario: Revoked bundle refuses import

- **WHEN** the source persona revokes a bundle and a consumer then
  attempts to import it
- **THEN** the import MUST be refused as revoked

#### Scenario: Purge removes previously imported items

- **WHEN** a consumer imported a bundle, the source revoked it, and
  the consumer runs the purge
- **THEN** every fact under that bundle's key prefix MUST be deleted
  from the consumer's memory

#### Scenario: Non-source persona cannot revoke

- **WHEN** a persona other than the bundle's `source_persona` calls
  `revoke`
- **THEN** the call MUST be refused

### Requirement: Clean-Room Audit Spans

The system SHALL emit one identity-stamped audit span per clean-room
operation through the EXISTING telemetry provider's `start_span`
escape hatch (the closed trace-op vocabulary is untouched): span
names `cleanroom.export`, `cleanroom.import`, `cleanroom.revoke`, and
`cleanroom.purge`, with attributes covering at least the bundle id,
the counterpart (audience or source persona), the outcome, and — when
an identity is known — the P25 identity attribute set (persona, role,
delegation chain, chain depth, session id, issued_at). Guardrail
decisions for `cleanroom_export` / `cleanroom_import` MUST
additionally flow through the existing `emit_guardrail_audit`.
Emission MUST be defensive: a failing telemetry provider degrades to
a WARNING and never changes the gateway outcome.

#### Scenario: Export emits guardrail and clean-room spans

- **WHEN** an identity-carrying export succeeds
- **THEN** one `guardrail.decision` span and one `cleanroom.export`
  span MUST be emitted
- **AND** the `cleanroom.export` attributes include the bundle id,
  audience, item count, and the acting persona/role

