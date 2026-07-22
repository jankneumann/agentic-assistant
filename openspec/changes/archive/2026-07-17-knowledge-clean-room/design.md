# knowledge-clean-room — Design

## Context

Runtime analogue of the ADR-0004 test-time privacy boundary
(roadmap P26; ecosystem pillar 3 Gap B). Prerequisites in place:
P25 `AgentIdentity` + audit-span precedent, P21 live memory
retrieval, P13 `PolicyGuardrails`. The pre-made design from the
roadmap brief was followed; deviations are recorded per decision.

## Decisions

### D1 — Sanitization: named-profile layer OVER telemetry/sanitize.py

`telemetry/sanitize.py` is redaction-fixed: its 15-pattern chain is
bound 1:1 to the observability spec ("Secret Sanitization") and is a
pure secret scrubber with no PII coverage and no extension API.
Editing it would couple the clean-room profile vocabulary to the
observability contract. Instead `core/cleanroom.py` defines the
profile layer: every profile FIRST runs `sanitize()` (the full secret
chain, reused as-is), then applies its own additional patterns.

Profiles shipped: `secrets` (secret chain only) and `standard`
(default; secrets + email / SSN / payment-card / IPv4 / phone
patterns). The profile map is a module-level dict — adding a profile
is one entry; config parsing validates profile names against it so an
unknown profile fails at persona load, not mid-export.

### D2 — Bundle format: self-contained JSON with hash-based provenance

One JSON file per export: header (`format: cleanroom-bundle`,
`version: 1`, `bundle_id` uuid4-hex, `source_persona`, `audience`,
`profile`, `exported_at`), `exporter` (serialized `AgentIdentity`:
persona, role, delegation_chain, session_id, issued_at), `items`
(each with `item_id`, singular `kind`, sanitized `key` + `content`,
per-item `content_hash` = sha256 of the sanitized content, plus
kind-specific metadata: category/confidence for preferences, role for
interactions), and `bundle_hash` = sha256 over the canonical
(sorted-keys, compact) JSON of everything except `bundle_hash`.

Hashes are TAMPER-EVIDENCE, not authentication — there is no key
infrastructure to sign with yet. Cryptographic signing (e.g. the
exporter identity becoming a SPIFFE SVID per the P25 placeholder) is
deferred; the envelope carries the fields a future signature would
cover, so upgrading is additive (`version: 2`). The bundle is fully
self-contained so it can travel over A2A/MCP later without schema
changes — that transport is the recorded follow-up; for now the file
IS the interop surface for external agents.

### D3 — Shared space: git-ignored directory, revocations alongside

`<space>/<audience>/<bundle_id>.json` for bundles,
`<space>/revocations/<bundle_id>.json` for revocation records.
Default space is `.cleanroom/` (repo/cwd-relative, git-ignored);
persona `clean_room.space_dir` overrides; gateway functions accept an
explicit `space_dir` for tests/automation. A shared DIRECTORY (not a
DB) keeps the space inspectable, transportable, and free of any
cross-persona database coupling — each persona still owns exactly one
DB (ADR/convention), and the shared space holds only declassified
material.

### D4 — Import quarantines everything as provenance-wrapped facts

Deviation from a literal reading of "stores into the consuming
persona's memory with provenance metadata retained": ALL accepted
items — facts, preferences, interactions — are stored as FACTS in the
consumer, keyed `cleanroom/<bundle_id>/<item_id>`, value
`{content, kind, provenance{source_persona, bundle_id, item_id,
content_hash, profile, exported_at, exporter, imported_at}}`.
Rationale: a foreign preference must not silently become a native
preference (confidence semantics are the consumer's own), a foreign
interaction is not the consumer's session history, and the uniform
key prefix makes revocation a single `delete_facts_by_prefix` call.
The `memory` table's JSONB value carries the provenance envelope —
no schema change, so the memory-policy delta is additive methods
only.

### D5 — Rule semantics: first-match-wins, exact audience names

Share rules: the FIRST rule whose `audience` list contains the
requested audience (exact name match — audiences are identifiers,
not patterns) wins; its kinds/globs/profile apply. Accept rules: the
FIRST rule whose `from` glob matches the bundle's source persona
wins; if that rule's `profiles` list doesn't trust the bundle's
profile, the import is refused (no fallthrough — consistent with
guardrail policy first-match semantics). Include/exclude globs match
against item key OR content (`fnmatchcase`, exclusions win);
preference rules may additionally pin `categories`.

### D6 — Guardrails: new action types, require_confirmation DENIES

`cleanroom_export` (resource = audience) and `cleanroom_import`
(resource = source persona), identity attached (CLI synthesizes
`AgentIdentity(persona, default_role)` when none is injected). No new
guardrail machinery: `PolicyGuardrails` action policies already
dispatch on arbitrary `action_type` strings. `require_confirmation`
is treated as denial until the approval interrupt flow exists —
identical to the P13 `model_call` posture, documented in the spec.
`revoke` deliberately has NO guardrail hook (it only removes access —
the safety direction) but IS audited.

### D7 — Audit: `cleanroom.<op>` spans via the start_span escape hatch

Mirrors `core/capabilities/audit.py` exactly: spans
`cleanroom.export` / `cleanroom.import` / `cleanroom.revoke` /
`cleanroom.purge` through the telemetry provider's `start_span`
escape hatch (closed trace-op vocabulary untouched), identity-stamped
with the same attribute names as `guardrail.decision`, and emission
is defensive (WARNING, never raises into the gateway). Guardrail
decisions themselves additionally flow through the existing
`emit_guardrail_audit`, so a denied export leaves a
`guardrail.decision` record.

### D8 — MemoryManager gains structured reads + prefix delete

Export needs machine-readable rows, but the manager only offered
formatted strings (`get_context`) for facts/preferences.
Added: `list_facts` / `list_preferences` (JSON-safe dicts, mirroring
P27's `list_interactions`) and `delete_facts_by_prefix`
(`autoescape`d `LIKE`, refuses an empty prefix so it can never wipe a
persona's memory). Three new `trace_memory_op` values (`fact_list`,
`preference_list`, `fact_delete`) extend the observability
vocabulary — the exact precedent P27 set with `interaction_list`,
hence the observability MODIFIED delta (a deviation from the
proposal-brief's expected delta list, recorded here).

### D9 — Gateway takes a structural store protocol, not the manager

`CleanRoomMemoryStore` Protocol (the five methods the gateway
consumes). The real `MemoryManager` satisfies it structurally; tests
inject an in-memory fake — the public suite stays DB-free and the
privacy guard untouched. Two new fixture personas
(`cleanroom_alpha` share-side, `cleanroom_beta` accept-side) carry
the `FIXTURE_PERSONA_SENTINEL_v1` marker and live under
`tests/fixtures/personas/` per the boundary rules.

## Risks / Trade-offs

- **Regex PII redaction is best-effort** — names, addresses, and
  free-text identifiers survive. Mitigations: share rules are
  allow-list-shaped (globs + kinds), exclusion globs, and the
  guardrail deny hook. An NER-based profile can be added behind the
  same profile map later.
- **Revocation is cooperative**: a consumer must run
  `cleanroom sync` (or import-time refusal) — nothing reaches into an
  external agent that already read a bundle. This matches the
  declassification model: revocation limits FUTURE spread.
- **In-memory ledger analogue**: the shared space is a directory;
  concurrent exporters could race on the same bundle id only if
  uuid4 collides (ignored).

## Deferred / Follow-ups

- A2A/MCP transport of bundles (serve + fetch endpoints).
- Cryptographic bundle signing tied to a real workload identity.
- Graphiti episode export (semantic-graph declassification).
- Scheduled `cleanroom sync` as a P7 daemon job example.
- Durable audit store (owned by approval interrupt/resume work).
