# knowledge-clean-room — Tasks

## 1. Config + sanitization layer

- [x] 1.1 `core/cleanroom.py`: `ShareRule` / `AcceptRule` /
      `CleanRoomConfig` dataclasses + `parse_clean_room_config`
      (actionable errors; falsy default = total isolation)
- [x] 1.2 Named sanitization profiles (`secrets`, `standard`) layered
      over the reused `telemetry/sanitize.py` chain; `apply_profile`
- [x] 1.3 Wire `clean_room:` into `PersonaConfig` +
      `PersonaRegistry.load` (error wrapping names the persona);
      annotated section in `personas/_template/persona.yaml`

## 2. MemoryManager surface

- [x] 2.1 `list_facts` / `list_preferences` structured reads
      (JSON-safe dicts, limit short-circuit)
- [x] 2.2 `delete_facts_by_prefix` (autoescaped LIKE, refuses empty
      prefix, returns rowcount)
- [x] 2.3 Extend `trace_memory_op` vocabulary with `fact_list` /
      `preference_list` / `fact_delete` (base.py + protocol test)

## 3. Gateway

- [x] 3.1 Provenance envelope: bundle build, canonical hashing,
      `verify_bundle` (per-item + whole-bundle tamper evidence)
- [x] 3.2 `export_shared`: share-rule selection, filtering,
      sanitization, guardrail hook (`cleanroom_export`), bundle write,
      `cleanroom.export` audit span
- [x] 3.3 `import_shared`: envelope verification, revocation check,
      audience check, accept rules, guardrail hook
      (`cleanroom_import`), provenance-wrapped fact storage,
      `cleanroom.import` audit span
- [x] 3.4 `revoke` (source-persona-only, audited) + `purge_revoked`
      (prefix delete per revocation record, audited)
- [x] 3.5 Git-ignore the default shared space (`.cleanroom/`)

## 4. CLI

- [x] 4.1 `assistant cleanroom` group: `export --to`, `import`,
      `revoke`, `sync` (shared manager/identity helpers; actionable
      errors, exit 1 on refusal)

## 5. Tests

- [x] 5.1 Two fixture personas (`cleanroom_alpha` / `cleanroom_beta`)
      with sentinel markers under `tests/fixtures/personas/`
- [x] 5.2 Config parsing + persona wiring + invalid-section load error
- [x] 5.3 Sanitization profiles redact seeded PII/secrets
- [x] 5.4 Export: bundle round-trip, share-rule filtering, exclusion
      globs, kind selection, no-config refusal, guardrail deny +
      require_confirmation, audit spans
- [x] 5.5 Import: provenance round-trip, accept-rule enforcement
      (kinds skipped / source refused / profile refused), tampered
      item + envelope refusals, wrong audience, guardrail deny
- [x] 5.6 Revocation: import refusal, source-only revoke, purge
      removes imported items, audit spans
- [x] 5.7 MemoryManager structured reads + prefix delete (mocked
      sessions)
- [x] 5.8 CLI flows (export/import/revoke/sync, missing database_url)

## 6. Docs + validation

- [x] 6.1 CLAUDE.md clean-room section + essential commands
- [x] 6.2 `openspec validate knowledge-clean-room --strict`
- [x] 6.3 Full gates: `uv run pytest tests/ -q`, `ruff check src
      tests`, `mypy src tests`
