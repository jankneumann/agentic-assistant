# knowledge-clean-room — Clean-Room Knowledge Sharing (P26)

## Why

Personas are execution boundaries. The test-time privacy boundary
(ADR-0004, two-layer guard) makes cross-persona reads impossible in
the public test suite — but at RUNTIME cross-persona exchange is
merely *undefined*: there is no sanctioned way for the personal
persona to hand a fact to the work persona (or to an external A2A/MCP
peer) without ambient leakage. The bootstrap's "cross-persona bridge"
was deferred with no design; ecosystem pillar 3 (Gap B,
`docs/architecture-analysis/2026-07-16-ecosystem-pillars.md`) re-scopes
it as a **declassification gateway**: policy-driven, audited flow
`source persona memory → sanitization → shared knowledge space →
consuming persona`, with per-fact provenance and revocation — the
runtime analogue of the test-time boundary. P25 supplied the
`AgentIdentity` principal and audit-span precedent; P21 supplied real
memory retrieval. Both are prerequisites this change now composes.

## What Changes

- **Persona `clean_room:` section** (validated at load with the
  actionable-error posture): ordered `share:` rules — what may LEAVE
  (memory kinds facts/preferences/interactions, key/content globs +
  preference-category filters, a named sanitization profile, an
  audience of persona names and/or `external`) — and ordered
  `accept:` rules — what a consuming persona ingests (source-persona
  globs, kinds, trusted profiles). **No `clean_room:` section = no
  sharing in either direction** — total isolation stays the default.
- **Declassification gateway** (`core/cleanroom.py`):
  `export_shared` reads via `MemoryManager`, applies the first share
  rule naming the audience, sanitizes every item through a named
  profile built ON TOP of the telemetry secret-redaction chain
  (`telemetry/sanitize.py` reused unchanged; the profile layer adds
  PII patterns), wraps items in a provenance envelope (source
  persona, per-item content hashes, profile, exporter
  `AgentIdentity`, whole-bundle hash) and writes a JSON **share
  bundle** to the git-ignored shared space (`.cleanroom/<audience>/`,
  path configurable). `import_shared` verifies the envelope, refuses
  revoked bundles and wrong audiences, applies accept rules, and
  stores accepted items as provenance-wrapped facts under
  `cleanroom/<bundle_id>/<item_id>` keys. `revoke` (source persona
  only) writes a revocation record; `purge_revoked` deletes a
  consumer's already-imported items on the next sync.
- **Guardrail hook**: export/import are guardrail actions
  (`cleanroom_export` / `cleanroom_import` with the audience/source
  as resource, identity attached) so `PolicyGuardrails` can deny or
  `require_confirmation` them — which DENIES until the approval
  interrupt flow exists (P13 semantics, documented).
- **Audit**: every export/import/revoke/purge emits a
  `cleanroom.<op>` span through the telemetry `start_span` escape
  hatch, identity-stamped (P25 `guardrail.decision` precedent);
  guardrail decisions additionally flow through the existing
  `emit_guardrail_audit`.
- **MemoryManager additions**: structured `list_facts` /
  `list_preferences` reads and a `delete_facts_by_prefix` (revocation
  purge; refuses an empty prefix). The `trace_memory_op` vocabulary
  gains `fact_list` / `preference_list` / `fact_delete` (same
  precedent as P27's `interaction_list`).
- **CLI**: `assistant cleanroom export -p <persona> --to <audience>`,
  `cleanroom import -p <persona> <bundle>`, `cleanroom revoke -p
  <persona> <bundle-id>`, `cleanroom sync -p <persona>`.
- **External agents**: the bundle JSON format IS the interop surface
  for now; transporting bundles over A2A/MCP is a recorded follow-up
  (the envelope is self-contained so it can travel).

## Impact

- Affected specs: `clean-room` (NEW capability), `cli-interface`
  (cleanroom command group), `memory-policy` (structured
  listing/deletion methods), `observability` (three new
  `trace_memory_op` values).
- Affected code: `core/cleanroom.py` (new), `core/memory.py`,
  `core/persona.py`, `cli.py`, `telemetry/providers/base.py`
  (op vocabulary), `personas/_template/persona.yaml`, `.gitignore`
  (`.cleanroom/`), CLAUDE.md; two new fixture personas
  (`tests/fixtures/personas/cleanroom_{alpha,beta}/`).
- Behavior preserved: personas without a `clean_room:` section load
  and behave exactly as before (falsy default config); no existing
  memory semantics change — the new manager methods are additive.
- Deferred (design.md): A2A/MCP bundle transport, cryptographic
  signing of bundles (hashes are tamper-evidence, not authentication),
  Graphiti-episode export, automatic purge scheduling, durable audit
  store (still owned by the approval-interrupt work).
