# Tasks: sync-test-privacy-boundary-spec

This is a pure spec-sync change. Every scenario added or modified in
`specs/test-privacy-boundary/spec.md` is already satisfied by the
shipped implementation at commit `2069784`. There is **no code to write
and no tests to add** — only spec text updates.

## Phase 1 — Spec edits

- [x] 1.1 Draft `specs/test-privacy-boundary/spec.md` with:
  - MODIFIED `Public test fixture root` (+3 scenarios: conftest
    setdefault, registry precedence, CI env declaration)
  - MODIFIED `Two-layer collection-time and runtime boundary guard`
    (subprocess kwargs scenario; updated exclusion-list scenario with
    six items)
  - MODIFIED `Self-contained persona-submodule test suite` (parents[N]
    wording clarified)
  - ADDED `Atomic dual-commit push wrapper` (3 scenarios)

- [x] 1.2 Draft `proposal.md` explaining each drift and why spec-sync
  is the right response (vs. backing out implementation or ignoring).

## Phase 2 — Validation

- [ ] 2.1 Run `openspec validate sync-test-privacy-boundary-spec --strict`

- [ ] 2.2 Cross-check each new/modified scenario against the shipped
  implementation to confirm the spec matches reality:
  - Env-var scenarios vs `tests/conftest.py:46`, `src/assistant/core/persona.py:42-56`, `tests/test_env_var_contract.py`
  - Subprocess kwargs vs `tests/_privacy_guard_plugin.py:259-263`, `tests/test_privacy_guard.py::test_layer2_rejects_subprocess_executable_kwarg/cwd_kwarg`
  - Exclusion list vs `tests/_privacy_guard_config.py:SCAN_EXCLUDED_FILES`
  - parents[N] wording vs `personas/personal/tests/conftest.py:15`
  - Push-wrapper scenarios vs `scripts/push-with-submodule.sh` modes + exit codes

- [ ] 2.3 No pytest run required — no code changes — but confirm that
  running `uv run pytest tests/` on this branch still exits 0 (it
  should, since this is pure-docs).

## Phase 3 — Merge

- [ ] 3.1 Push branch `openspec/sync-test-privacy-boundary-spec`
  and open PR.

- [ ] 3.2 After merge: the archive flow syncs the delta into
  `openspec/specs/test-privacy-boundary/spec.md`, increasing the
  published requirement count.
