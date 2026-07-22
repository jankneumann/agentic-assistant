# meta-harness-compat — Compose under meta-harnesses; first real SandboxProvider (P22)

## Why

Architecture-review finding G-D (2026-07-07): the meta-harness posture
is undefined. Omnigent (Databricks, Apache 2.0) composes agents under
a runner+server control plane with YAML-defined agents and pluggable
sandboxes; NVIDIA NemoClaw hardens always-on agents inside OpenShell
sandboxes with routed inference and network policy — and the GX10 this
project already uses for local inference supports both. Guiding
principle 6 says compose UNDER meta-harnesses, don't rebuild one. The
composition surface (AG-UI `/chat`, A2A card + `/a2a/v1`, MCP `/mcp`)
exists since P6/P14a/P17, but nothing describes the assistant TO a
meta-harness, no verdict is recorded per meta-harness, and the sandbox
seam is still the `PassthroughSandbox` stub even though the
sandbox-provider spec (v2, archived `capability-protocols-v2`) already
binds the three-plane `SandboxConfig` and names the enforcement seam.

## What Changes

- **Omnigent-composable agent definition**: new `assistant
  export-omnigent-agent -p <persona>` (export family) generating an
  Omnigent-shaped agent-definition YAML — persona name/description,
  A2A/MCP/AG-UI endpoints from a `--base-url`, P25 `auth.a2a`
  declaration shape (ref name only), one skill per enabled role —
  with a mandatory header marking the schema as designed-offline and
  requiring verification against `omnigent-ai/omnigent` on a
  connected machine (this environment cannot fetch the repo).
  Builder in `src/assistant/composition/omnigent.py`.
- **First real SandboxProvider — `ContainerSandboxProvider`**:
  implements the binding v2 planes: filesystem
  (`read-only`/`workspace-write`/`full-access` + mounts → `-v` /
  `--read-only`), network (deny-by-default → `--network=none`;
  non-empty allow-list is a documented limitation compiled to
  `SANDBOX_NET_ALLOW`/proxy env vars for an enforcing backend),
  credentials (explicit `-e REF=value` allow-list, no ambient env).
  docker/podman autodetected; `ProcessRunner` injectable (all
  container interaction mocked in tests — no real `docker run` in
  CI). `SandboxedProcessRunner` provides the spec's
  extension-subprocess-boundary seam. The plane dataclasses
  (`FilesystemPlane`/`NetworkPlane`/`CredentialsPlane` on
  `SandboxConfig`) land in `types.py`, and `PassthroughSandbox` now
  carries declared planes on context metadata (already spec'd, now
  implemented).
- **Resolver selection + persona schema**: persona `sandbox:` section
  (`provider`/`image`/`runtime` + the three planes), validated with
  actionable errors at load; the capability resolver selects
  `ContainerSandboxProvider` only when `provider: container` is
  requested — `PassthroughSandbox` remains the default.
- **ADR 0007 + deployment doc**: per-meta-harness verdicts (Omnigent
  = integrate-under; NemoClaw = target GX10 runtime, concrete
  integration deferred to P23; OpenShell = sandbox backend candidate
  behind the runner abstraction), status ACCEPTED with
  verify-on-connected-machine caveats;
  `docs/deployment/meta-harness.md` covers registration under
  Omnigent and the NemoClaw/OpenShell plan.

## Impact

- Affected specs: `sandbox-provider` (ContainerSandboxProvider +
  seam runner + persona selection), `cli-interface`
  (export-omnigent-agent), `meta-harness` (NEW — agent-definition
  content contract).
- Affected code: `core/capabilities/{types,sandbox,resolver}.py`,
  `core/persona.py`, `composition/{__init__,omnigent}.py` (new),
  `cli.py`, `personas/_template/persona.yaml`,
  `docs/decisions/0007-meta-harness-posture.md` (+ README index),
  `docs/deployment/meta-harness.md`, CLAUDE.md.
- Behavior preserved: personas without a `sandbox:` section keep
  `PassthroughSandbox`; existing `SandboxConfig` construction sites
  (legacy two fields) are unchanged; no existing CLI command changes.
- Honest uncertainty: Omnigent schema, NemoClaw plugin/network-policy
  formats, and the OpenShell CLI were not fetchable from this
  environment — recorded in the export header, ADR 0007, and the
  deployment doc as verify-on-connected-machine items.
