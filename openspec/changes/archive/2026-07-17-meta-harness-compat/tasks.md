# meta-harness-compat — Tasks

## 1. SandboxConfig v2 planes (implement the binding spec)

- [x] 1.1 `core/capabilities/types.py` — `SandboxMount`,
  `FilesystemPlane` (Codex level vocabulary, invalid level fails
  validation), `NetworkPlane` (deny-by-default allow-list + proxy),
  `CredentialsPlane` (explicit visibility set); `SandboxConfig` gains
  the three optional plane fields + `declared_planes()` summary;
  legacy two-field construction unchanged
- [x] 1.2 `PassthroughSandbox` carries declared planes on
  `ExecutionContext.metadata` without enforcing (spec scenario)

## 2. ContainerSandboxProvider + seam runner

- [x] 2.1 `core/capabilities/sandbox.py` — `detect_container_runtime`
  (docker → podman, injectable `which`), `ContainerSandboxProvider`
  (image/runtime/runner/credentials injection; tempdir work_dir
  lifecycle; satisfies `SandboxProvider` protocol)
- [x] 2.2 Plane compilation `compile_run_argv`: fs levels + mounts,
  network `--network=none` / allow-list→env documented limitation
  (+ WARNING), credentials explicit `-e` allow-list via
  CredentialProvider
- [x] 2.3 `SandboxedProcessRunner` — extension-subprocess-boundary
  seam: container contexts wrap, others pass through; posture from
  the execution context only
- [x] 2.4 Opt-in real-runtime smoke test
  (`tests/integration/test_container_sandbox_smoke.py`,
  `RUN_CONTAINER_SANDBOX_TESTS=1` + runtime present; never runs in CI)

## 3. Persona schema + resolver selection

- [x] 3.1 `parse_sandbox_settings` (`SandboxSettings`,
  `SandboxConfigError` actionable errors: unknown keys, provider,
  missing image, runtime, level vocabulary, mount shape,
  writable-vs-read-only contradiction, network/credentials list types)
- [x] 3.2 `core/persona.py` — `PersonaConfig.sandbox` parsed at load
  with the standard error-wrapping pattern
- [x] 3.3 `core/capabilities/resolver.py` — `_resolve_sandbox`:
  factory wins; `provider: container` → `ContainerSandboxProvider`
  with persona credentials; default stays `PassthroughSandbox`;
  construction errors propagate (no silent degrade)
- [x] 3.4 `personas/_template/persona.yaml` — annotated `sandbox:`
  schema block

## 4. Omnigent-composable agent definition

- [x] 4.1 `src/assistant/composition/omnigent.py` —
  `build_omnigent_agent_definition` (persona identity, A2A/MCP/AG-UI
  endpoints from base_url, P25 auth shape ref-only, skills per role,
  `schema_verified: false`) + `render_omnigent_agent_yaml` with
  `UNVERIFIED_SCHEMA_HEADER`
- [x] 4.2 `cli.py` — `export-omnigent-agent` command (`-p`,
  `--base-url`, `-o/--output`; stdout default), joining the flat
  export family

## 5. Docs + ADR

- [x] 5.1 `docs/decisions/0007-meta-harness-posture.md` — ACCEPTED;
  verdicts: Omnigent integrate-under, NemoClaw target GX10 runtime
  (defer to P23; requirements captured), OpenShell backend candidate
  behind the runner seam; verify-on-connected-machine caveats; README
  index row
- [x] 5.2 `docs/deployment/meta-harness.md` — Omnigent registration
  (custom-agent API pattern over our endpoints), NemoClaw/OpenShell
  GX10 plan, `sandbox:` reference + compilation summary
- [x] 5.3 CLAUDE.md — P22 section (export command, sandbox config,
  seam, limitations)

## 6. Tests + gates

- [x] 6.1 `tests/test_sandbox_container.py` — plane types +
  validation, passthrough carry, autodetect/injection, per-plane
  compilation, seam runner, persona parsing (+ load errors), resolver
  selection (all subprocess interaction mocked)
- [x] 6.2 `tests/test_export_omnigent.py` — definition content, auth
  shapes, unverified marker, YAML render round-trip, CLI
  stdout/file/missing-persona, ADR + deployment-doc presence checks
- [x] 6.3 Gates: `uv run pytest tests/`, `ruff check src tests`,
  `mypy src tests`, `openspec validate meta-harness-compat --strict`
