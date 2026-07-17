# 0007 — Meta-harness posture: compose under, never rebuild

## Status

ACCEPTED — 2026-07-17 (P22 `meta-harness-compat`; architecture review
2026-07-07 finding G-D; roadmap guiding principle 6). Carries explicit
**verify-on-connected-machine caveats** — see the per-verdict notes:
the environment that executed P22 could not fetch the Omnigent or
NemoClaw repositories, so integration shapes were designed from their
documented concepts and must be checked against the live projects
before first real registration/deployment.

## Context

Two meta-harness control planes emerged above the agent-harness layer
in mid-2026:

- **Omnigent** (Databricks, Apache 2.0) composes Claude
  Code/Codex/Cursor/Pi/LangGraph agents under a runner+server control
  plane: agents are YAML-defined, wrapped by a runner exposing a
  "common API pattern", sessions run in pluggable sandboxes, and the
  server persists/shares sessions.
- **NVIDIA NemoClaw** hardens always-on agents (OpenClaw/Hermes-class)
  inside **OpenShell** sandboxes with routed inference (NIM) and
  network policy. The GX10 — this project's local-inference node
  (P20, docs/deployment/gx10-node.md) — is explicitly marketed as
  supporting OpenClaw and NemoClaw.

This repo is the persona/role/capability layer. It already exposes the
composition surface a meta-harness needs: AG-UI SSE (`/chat`), the A2A
agent card + JSON-RPC (`/a2a/v1`, P6), and MCP streamable HTTP
(`/mcp`, P17), with inbound auth declaration from P25. The
architecture review's position (G-D) is that rebuilding
session-sharing, agent fleets, or a sandbox control plane in-repo
would duplicate ecosystems that are already better funded and
maintained.

The sandbox-provider spec (v2, archived `capability-protocols-v2`)
defines a three-plane `SandboxConfig` (filesystem / network /
credentials) and names the enforcement seam (tool invocation + the
extension subprocess boundary), but until P22 only the
`PassthroughSandbox` stub existed.

## Decision

One verdict per meta-harness — **adopt / integrate-under / defer**:

### Omnigent → INTEGRATE-UNDER (do not adopt its server)

- The assistant registers with Omnigent as an **external/custom
  agent** described by an agent-definition YAML (`assistant
  export-omnigent-agent`, `src/assistant/composition/omnigent.py`)
  pointing at the served A2A + MCP + AG-UI endpoints. Omnigent's
  runner composes via those endpoints; it does **not** spawn the
  assistant as a CLI subprocess, and its sandbox management is
  irrelevant to an endpoint-composed agent.
- We do **not** adopt the Omnigent server for our own orchestration:
  sessions, personas, roles, guardrails, and model routing remain
  owned by this repo's capability protocols. Session sharing and
  fleet features, if ever wanted, are consumed from Omnigent — never
  rebuilt here.
- *Verify on a connected machine*: the exported YAML is
  Omnigent-SHAPED, generated offline from documented concepts
  (YAML-defined agents, runner wraps agent, sandboxed sessions). The
  file header and docs/deployment/meta-harness.md instruct the
  operator to verify field names against the canonical
  `omnigent-ai/omnigent` schema, and to confirm the exact custom-agent
  registration API, before use.

### NemoClaw → TARGET RUNTIME for the GX10 (concrete integration DEFERRED to P23)

- NemoClaw is the deployment vehicle for running the assistant as a
  sandboxed always-on plugin/agent on the GX10, next to the NIM/vLLM
  inference endpoints it already routes to (P20). Concrete manifests,
  installation, and network-policy wiring belong to P23
  `deployment-topology` — not here.
- What its model **requires from us today** (and P22 delivers):
  1. a **declarative isolation posture** NemoClaw's network-policy
     engine can honor — the three-plane `SandboxConfig`, with the
     network plane's allow-list/proxy compiled to
     `SANDBOX_NET_ALLOW` / proxy env vars precisely because plain
     container runtimes cannot enforce per-host egress (an enforcing
     backend can);
  2. **loopback-safe defaults + declared inbound auth** (P25
     `auth.a2a`) so exposing the endpoints inside a NemoClaw pod
     boundary is a config change;
  3. a **single always-on entrypoint** (`assistant daemon --serve`,
     P7) suitable for supervision as a long-lived plugin.
- *Verify on a connected machine*: NemoClaw's actual plugin manifest
  format and network-policy CRD/schema were not fetchable; the
  requirements list above is derived from its documented posture.

### OpenShell → SANDBOX BACKEND CANDIDATE behind the runner abstraction (deferred)

- P22 ships the first real provider, `ContainerSandboxProvider`
  (`src/assistant/core/capabilities/sandbox.py`): compiles the three
  planes into a `docker run`/`podman run` invocation (runtime
  autodetected), enforced at the spec's extension-subprocess seam via
  `SandboxedProcessRunner`, selected by the capability resolver only
  when a persona's `sandbox:` section requests it
  (`PassthroughSandbox` stays the default).
- The provider's **injectable `ProcessRunner`** is the deliberate
  seam for OpenShell: adopting it (e.g. under NemoClaw on the GX10)
  means supplying an OpenShell-invoking runner/runtime — a config or
  small-adapter change, not a provider rewrite. Adoption is deferred
  until P23 puts real workloads on the GX10.
- *Verify on a connected machine*: OpenShell's CLI/API surface was
  not fetchable; the runner abstraction was sized to what a
  container-shaped `run` interface needs.

## Consequences

- The assistant stays a **composable leaf**, reachable over three
  standard protocols; every meta-harness integration is data (YAML,
  env, persona config), not new agent code paths.
- Real isolation is now opt-in per persona; personas without a
  `sandbox:` section are byte-for-byte unaffected (passthrough).
- The network plane's allow-list is **declared but not enforced** by
  plain docker/podman — a documented limitation surfaced via warning
  + env compilation. Enforcement arrives with an egress proxy or the
  NemoClaw/OpenShell backend (P23).
- Nothing in-repo depends on Omnigent/NemoClaw existing: if either
  project pivots, we discard an export command and a doc, not an
  orchestration layer.
- Embodied by: `src/assistant/core/capabilities/sandbox.py`,
  `src/assistant/core/capabilities/types.py` (planes),
  `src/assistant/composition/omnigent.py`, `assistant
  export-omnigent-agent` (cli.py), docs/deployment/meta-harness.md;
  originating change `openspec/changes/meta-harness-compat/`.
