# ADR-0004: Two-layer public-test / private-persona privacy boundary

## Status

ACCEPTED — decided in OpenSpec change `test-privacy-boundary`
(`openspec/changes/archive/2026-04-13-test-privacy-boundary/`),
archived 2026-04-13; spec drift codified by
`sync-test-privacy-boundary-spec` (same date).

## Date

2026-04-13

## Context

After P1, the public test suite read from and asserted on content
inside the private `personas/personal/` git submodule. Three concrete
problems: (1) private prompt strings leaked into public test
assertions; (2) CI could not clone the private submodule, so a
workaround overlaid fixtures onto the mount point — tests ran against
the real submodule locally but fixtures in CI, allowing silent
divergence; (3) the persona submodule could not be validated by
non-Python consumers because its only tests lived in the public repo
behind `PersonaRegistry`. Alternatives considered: a
`@pytest.mark.integration` dual-mode marker (rejected — markers decay
and the fixture-sync burden persists) and externalizing private
content into env vars (rejected — personas are private, not secret;
disproportionate refactor).

## Decision

Enforce a privacy boundary with two independent layers, both driven by
a single deny-list in `tests/_privacy_guard_config.py`:

1. **Collection-time substring scan** (`tests/conftest.py`): fails the
   session if any collected public test file references
   `personas/personal/` or `personas/work/` paths, with an allow-list
   for `tests/fixtures/` and `personas/_template/`.
2. **Runtime filesystem guard** (`tests/_privacy_guard_plugin.py`): a
   pytest plugin patching `pathlib.Path.open`/`read_text`/`read_bytes`,
   `builtins.open`, `os.open`, and `subprocess.Popen.__init__` to
   reject constructed-path reads into forbidden namespaces — closing
   the `Path("personas") / name / "x.yaml"` bypass. A self-probe at
   `pytest_configure` verifies the patches actually installed.

Public tests run exclusively against `tests/fixtures/personas/`
(resolved via the `ASSISTANT_PERSONAS_DIR` env-var contract, set in
`tests/conftest.py`), asserting on the tests-only
`FIXTURE_PERSONA_SENTINEL_v1` marker instead of real persona content.
Persona-specific tests moved into each persona's private submodule,
self-contained (no `src/assistant/*` imports), proven by fresh-venv
runs in `scripts/verify-submodule-standalone.sh` and
`scripts/verify-public-tests-standalone.sh`. Dual-repo pushes go
through `scripts/push-with-submodule.sh` so the parent never
references an unreachable submodule SHA.

## Consequences

- The CI "populate personas/personal from fixture" step was removed;
  `tests/test_ci_workflow_hygiene.py` prevents its reintroduction.
- One enforcement mechanism runs locally and in CI; leaks fail loudly
  at collection or at first read (CLAUDE.md gotcha G6).
- The monkey-patched I/O guard is scoped to the pytest lifecycle and
  documented as not covering mmap/ctypes I/O.
- The boundary covers `work` from day one, future-proofing P15
  `work-persona-config`; P26 `knowledge-clean-room` is planned as the
  runtime analogue of this test-time boundary.
