# meta-harness-compat — Design

## D1. Compose under, never rebuild (posture)

The assistant stays the persona/role/capability layer; meta-harnesses
are optional control planes ABOVE it (arch review G-D; guiding
principle 6). Every integration in this change is data — an exported
YAML, persona config, env vars — never a new agent code path. If
Omnigent or NemoClaw pivots, we discard an export command and a doc.

## D2. Omnigent-shaped export, not Omnigent-schema export (honesty)

This environment cannot fetch `omnigent-ai/omnigent`, so the exact
agent-definition schema is unverifiable here. Decision: design the
YAML from Omnigent's *documented concepts* (YAML-defined agents,
runner wraps agent, sandboxed sessions, common API pattern over
harnesses; sources linked from the 2026-07-07 architecture review) and
make the uncertainty impossible to miss:

- `UNVERIFIED_SCHEMA_HEADER` is prepended to every render and names
  the canonical repo to verify against;
- the definition carries `x_generator.schema_verified: false`;
- ADR 0007 and docs/deployment/meta-harness.md repeat the caveat.

Registration model is **external/custom agent**: Omnigent's runner
composes via the served A2A/MCP/AG-UI endpoints and must not spawn the
assistant as a CLI subprocess — sessions/guardrails/routing stay owned
by this repo (hence `kind: external-agent` and the explicit
`sandbox.managed_by: assistant` note in the definition).

`export-omnigent-agent` joins the existing FLAT export family
(`export`, `export-eval-dataset`, `export-memory`) rather than
converting `export` into a click group — converting would break the
existing `assistant export -p ... -H claude_code` invocation shape.

## D3. Container provider compiles; the runner executes (testability)

`ContainerSandboxProvider` separates *compilation* (pure:
`compile_run_argv(config, context, command) -> argv`) from *execution*
(the injectable `ProcessRunner`). Tests assert on compiled argv and
inject a recording runner — a real `docker run` never executes in CI;
the real-runtime smoke test is opt-in
(`RUN_CONTAINER_SANDBOX_TESTS=1`, tests/integration/). The runner
abstraction is also the OpenShell adoption seam (ADR 0007): an
OpenShell backend supplies a different runner/runtime, not a new
provider.

Plane compilation decisions:

- **Filesystem**: `--read-only` root for `read-only` and
  `workspace-write`; the context `work_dir` mounts at `/workspace`
  (`:ro` only for `read-only`). Declared mounts compile to
  `-v host:sandbox:ro|rw`. A writable mount under `read-only` is a
  *parse-time* error (contradictory declaration) rather than a silent
  downgrade.
- **Network**: declared plane + empty allow-list → `--network=none`
  (real enforcement). Non-empty allow-list: plain docker/podman have
  no per-host egress primitive — DOCUMENTED LIMITATION, compiled to
  `SANDBOX_NET_ALLOW` + proxy env vars (`HTTPS_PROXY`/`HTTP_PROXY`/
  `SANDBOX_NET_PROXY`) for an egress proxy or NemoClaw/OpenShell
  network policy to honor, with a WARNING log so the operator knows
  enforcement is delegated. No plane → legacy permissive default.
- **Credentials**: container runtimes don't inherit host env, so
  no-ambient-inheritance holds by construction; the visibility set
  compiles to explicit `-e REF=value` pairs resolved through the
  persona's `CredentialProvider` (injected by the resolver), falling
  back to process env when none is injected.

## D4. Enforcement at the named seam only

The sandbox-provider spec names two seam boundaries; this change
implements the **extension subprocess boundary** via
`SandboxedProcessRunner(provider, config, context)`: posture comes
from the execution context (never per-extension config), container
contexts wrap commands, all other providers pass through. The tool-
invocation boundary keeps flowing through the provider's context as
today (Passthrough carries planes on metadata); making ToolSpec
handlers container-aware is out of scope until a workload needs it —
no ad-hoc isolation was added anywhere else.

## D5. Selection is explicit and fail-loud

Resolver: factory override > persona `sandbox.provider: container` >
`PassthroughSandbox`. Construction errors (no docker/podman on PATH,
bad runtime) PROPAGATE — a persona that explicitly requested isolation
never silently degrades to passthrough (mirrors P20's fail-closed
health posture). Schema validation happens at persona load
(`parse_sandbox_settings`, `SandboxConfigError` wrapped into the
standard "invalid sandbox: section" ValueError), matching the
`auth.a2a` actionable-error pattern.

## D6. NemoClaw deferred to P23, requirements captured now

ADR 0007 records what NemoClaw's plugin/network-policy model requires
from us (declarative isolation posture, declared inbound auth,
single always-on entrypoint) — all delivered by P22/P25/P7 — and
defers manifests/installation to P23 `deployment-topology`, where real
GX10 workloads exist to validate against.

## Deferred / follow-ups

- Tool-invocation-boundary container enforcement (needs a concrete
  sandboxed-tool workload).
- OpenShell runner adapter + NemoClaw manifests (P23).
- Wiring `SandboxedProcessRunner` into a real subprocess-spawning
  extension (none exists in-tree today; the seam ships ready).
- Verify Omnigent schema / registration API on a connected machine
  and, if needed, adjust `build_omnigent_agent_definition` field
  names (mechanical rename).
