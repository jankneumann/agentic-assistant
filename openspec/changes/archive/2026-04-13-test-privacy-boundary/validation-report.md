# Validation Report: test-privacy-boundary

**Date**: 2026-04-13
**Commit**: `c24c158`
**Branch**: `openspec/test-privacy-boundary`
**PR**: https://github.com/jankneumann/agentic-assistant/pull/2

## Phase Results

| Phase | Status | Evidence |
|-------|--------|----------|
| Prerequisites | ✓ pass | On `openspec/test-privacy-boundary`, 5 commits since `main`, submodule initialized |
| Deploy | ○ skip | N/A — test-infrastructure feature, no HTTP API |
| Smoke | ○ skip | N/A — no deployed service |
| Gen-Eval | ○ skip | No descriptors found |
| Security | ○ skip | N/A — no dependencies added; privacy-boundary is in-process only |
| E2E | ○ skip | No `tests/e2e/` exists |
| Architecture | ○ skip | `docs/architecture-analysis/` not scaffolded in this repo (tracked as gap) |
| **Spec Compliance** | ✓ pass | 14/14 scenarios verified — see below |
| Work-Package Evidence | ✓ pass | All packages completed; artifacts committed |
| Log Analysis | ○ skip | No service logs (Deploy skipped) |
| **CI/CD Status** | ✓ pass | PR #2: `Lint + typecheck + test` passed in 45s |

## Spec Compliance Summary

**All 14 SHALL/MUST scenarios are satisfied by the implementation.** Evidence per
scenario is captured inline; full audit JSON recorded in the session log.

### Requirement coverage

| Requirement | Scenarios | Status |
|-------------|-----------|--------|
| Public test fixture root | 2/2 | ✓ |
| Two-layer collection + runtime guard | 7/7 | ✓ |
| Self-contained persona-submodule test suite | 4/4 | ✓ (including fresh-venv proof + parent-workspace forward-compat) |
| Replacement integration coverage | 1/1 | ✓ (`FIXTURE_PERSONA_SENTINEL_v1` + `FIXTURE_ROLE_SENTINEL_v1`) |
| CI simplification + hygiene check | 2/2 | ✓ |
| Documentation | 2/2 | ✓ (`CLAUDE.md` Conventions + `docs/gotchas.md` G6/G7) |

### Over-implementation (defense-in-depth beyond spec)

1. **`ASSISTANT_PERSONAS_DIR` env-var contract** in `PersonaRegistry`/`RoleRegistry`
   with precedence `explicit > env > default`, locked by 6 unit tests in
   `tests/test_env_var_contract.py` and documented in `docs/gotchas.md` G6.
2. **Idempotent `_install_patches`** (tests/_privacy_guard_plugin.py:235-249)
   with dedicated regression test — defends against double `pytest_configure`
   (xdist, re-registration) that would otherwise cause infinite recursion.
3. **Symlink-escape resolve-pass** in `_is_forbidden` — catches
   `tests/fixtures/sneaky → ../../personas/personal` bypass that the lexical
   substring check would admit.
4. **Component-aware subprocess argv matching** — catches `git -C
   personas/personal log` (bare-dir) and `--config=.../personas/personal/...`
   (colon-list) bypasses that simple substring matching would miss.
5. **Plugin self-probe** at `pytest_configure` — fails session loudly if a
   future CPython refuses Python-level rebinding of `Path.open`.

### Spec drift (implementation evolved past spec; addressable in `/cleanup-feature`)

| # | Drift | Resolution |
|---|-------|------------|
| 1 | `ASSISTANT_PERSONAS_DIR` env var is implemented + tested + documented in `docs/gotchas.md` G6 but not captured as a SHALL in `spec.md` | Add a scenario under "Public test fixture root" describing the precedence contract during spec-sync |
| 2 | Subprocess interception covers `executable=` and `cwd=` kwargs (not just `args`); component-aware regex catches bare-dir argv | Add scenarios to "Layer 2 rejects a forbidden subprocess argv" |
| 3 | Layer 1 `SCAN_EXCLUDED_FILES` includes `test_ci_workflow_hygiene.py` + `test_workspace_hygiene.py` (they reference forbidden names as data) | Document in D9 scope + add scenario |
| 4 | Submodule conftest resolves parent root via `parents[3]` (conftest-relative), spec says `parents[2]` (test-file-relative) — both point to same directory but wording differs | Clarify spec phrasing |
| 5 | `scripts/push-with-submodule.sh` exists as implementation-phase helper but no spec scenario governs it | Document as out-of-scope tooling OR add scenario for atomic dual-commit push |

None of these drifts represent missing requirements — the implementation is
stricter than the spec and tested accordingly. They are spec-grooming items
that will make the spec reflect production reality.

## Deferred (tracked, not blocking)

- 15+ MINOR findings from IMPL_REVIEW Round 1 (perf polish, docstring drift,
  commit split for bisect ergonomics, graphiti-contract positive assertion,
  `os.open` perf short-circuit, missing-upstream error message clarity).
  Captured in `openspec/changes/test-privacy-boundary/session-log.md` under
  each review phase's "Open Questions".
- Architecture graph (`docs/architecture-analysis/`) is absent in this repo —
  unrelated to this change; tracked as a pre-existing gap.

## Known limitations (documented in design R2, not blockers)

Layer 2 runtime guard does NOT cover:
- `mmap.mmap` on an already-opened file descriptor
- `ctypes`-based I/O bypassing the stdlib
- `os.system` on Windows (dispatches via `cmd.exe`, not `subprocess.Popen`)
- Deliberately-split subprocess argv reconstructed at `execve` time

These patterns are outside the documented threat model (deliberate evasion,
not accidental Copilot idiom). Layer 1 substring scan is the only defense
for any of them.

## Verification commands (reproducible)

```bash
# Full parent-repo test suite
uv run pytest tests/                      # 126 passed

# Parent-repo tests with submodule deinit-ed (proves goal G1)
bash scripts/verify-public-tests-standalone.sh  # 126 passed

# Submodule self-contained suite in fresh venv (proves goal G3)
bash scripts/verify-submodule-standalone.sh     # 9 passed

# Static analysis
uv run mypy src tests                     # 38 files, no issues
uv run ruff check .                       # all checks passed

# OpenSpec strict validation
openspec validate test-privacy-boundary --strict
```

## Result

**PASS — ready to merge.**

Remaining work after merge:
1. `/cleanup-feature test-privacy-boundary` — archives the change, syncs
   spec delta into `openspec/specs/`, handles final submodule SHA
   housekeeping on `main`.
2. During spec-sync, resolve the 5 drift items above (most importantly,
   capture the `ASSISTANT_PERSONAS_DIR` env-var contract as a SHALL).
