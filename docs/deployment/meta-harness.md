# Running under a meta-harness (Omnigent / NemoClaw)

P22 `meta-harness-compat` — how to register this assistant **under**
an external meta-harness instead of rebuilding a control plane in-repo
(ADR 0007, roadmap guiding principle 6). The composition surface is
the served endpoint trio:

| Surface | Endpoint | Since |
|---------|----------|-------|
| A2A agent card | `GET /.well-known/agent-card.json` (+ legacy `agent.json`) | P6 |
| A2A JSON-RPC | `POST /a2a/v1` (`message/send`, `message/stream`) | P6 |
| MCP (streamable HTTP) | `POST /mcp` — `ask` + one `ask_<role>` per role | P17 |
| AG-UI SSE | `POST /chat`, `GET /health` | P14a |

Start them together:

```bash
uv run assistant serve -p personal --a2a --mcp --host 0.0.0.0 --port 8765
```

> **Auth first**: the server binds loopback by default. Before binding
> beyond loopback, declare persona `auth.a2a: {type: bearer,
> token_env: REF}` (P25) so the A2A surface requires a bearer token;
> MCP-surface auth is still a recorded follow-up — keep `/mcp` behind
> the meta-harness's own network boundary until it lands.

> **Verify-on-connected-machine caveat**: this environment could not
> fetch the Omnigent, NemoClaw, or OpenShell repositories. Everything
> below is designed from their *documented concepts*; verify concrete
> schemas/manifests against the live projects before first use
> (ADR 0007 records the same caveat per verdict).

## 1. Omnigent (Databricks) — register as an external/custom agent

Omnigent composes agents defined via YAML plus a common API pattern
over harnesses; a runner wraps each agent and sessions run in
pluggable sandboxes. This assistant integrates as an
**externally-served agent** — Omnigent's runner talks to the endpoints
above and must NOT spawn `assistant` as a CLI subprocess (sessions,
guardrails, personas stay owned by this repo).

1. Generate the agent definition:

   ```bash
   uv run assistant export-omnigent-agent -p personal \
       --base-url http://gx10.local:8765 -o personal-agent.yaml
   ```

   The YAML carries: persona name/description, the A2A/MCP/AG-UI
   endpoints, the P25 auth declaration *shape* (credential ref name
   only — never a token value), and one skill per enabled role. Its
   header marks it **Omnigent-shaped, schema unverified** — check
   field names against the canonical `omnigent-ai/omnigent` schema on
   a connected machine, then adjust the file (not the generator's
   endpoints) as needed.

2. Register it via Omnigent's custom-agent API pattern, pointing at
   the A2A endpoint as the primary protocol (the card advertises
   streaming + auth) and MCP as the tool-shaped alternative.

3. Sandboxing: leave Omnigent-managed sandboxes off for this agent —
   it is endpoint-composed, and isolation is the persona's own
   `sandbox:` config (see §3).

## 2. NemoClaw / OpenShell — sandboxed always-on plugin on the GX10

NemoClaw hardens always-on agents inside OpenShell sandboxes with
routed inference (NIM) and network policy; the GX10 already hosts this
project's local inference endpoints (docs/deployment/gx10-node.md).
Verdict (ADR 0007): NemoClaw is the **target runtime** for the GX10
deployment; concrete manifests land in P23 `deployment-topology`.

What to deploy when P23 wires it up:

- **Entrypoint**: `uv run assistant daemon -p personal --serve`
  (single always-on process: scheduler + AG-UI/A2A/MCP server) as the
  NemoClaw plugin's long-lived command.
- **Network policy**: mirror the persona's `sandbox.network` plane —
  the assistant compiles its allow-list to `SANDBOX_NET_ALLOW` /
  `HTTPS_PROXY` env vars precisely so an enforcing layer (NemoClaw
  network policy or an egress proxy) can honor it; plain docker/podman
  cannot enforce per-host egress on their own.
- **Inference stays on-node**: point the persona `models:` registry at
  the NIM/vLLM endpoints (`dialect: openai-compatible`, P19/P20) so
  the sandboxed agent never needs cloud egress for the local tier.
- **OpenShell**: candidate backend for `ContainerSandboxProvider`'s
  injectable runner — supplying an OpenShell-invoking runner/runtime
  is a config/adapter change, not a provider rewrite.

## 3. The persona `sandbox:` section (first real SandboxProvider)

`ContainerSandboxProvider` compiles the sandbox-provider spec's three
planes into a `docker run` / `podman run` invocation, enforced at the
extension-subprocess seam (`SandboxedProcessRunner`). Opt in per
persona — omit the section to keep `PassthroughSandbox`:

```yaml
sandbox:
  provider: container          # passthrough (default) | container
  image: python:3.12-slim      # required for container
  runtime: docker              # docker | podman (omit = autodetect)
  filesystem:
    level: workspace-write     # read-only | workspace-write | full-access
    mounts:
      - host_path: /srv/data
        sandbox_path: /data
        writable: false
  network:
    allow: []                  # deny-by-default; [] = --network=none
    # allow: ["api.anthropic.com"]   # compiled to SANDBOX_NET_ALLOW —
    # proxy: http://proxy:3128       # needs an enforcing proxy/backend
  credentials:
    visible: [GMAIL_TOKEN]     # only these refs enter the container env
```

Compilation summary: `read-only` → `--read-only` root + `:ro`
workspace; `workspace-write` → `--read-only` root + `:rw` workspace;
`full-access` → writable root; empty network allow-list →
`--network=none`; non-empty allow-list → env-var declaration
(**documented limitation** — see §2); credentials plane → explicit
`-e REF=value` list, no ambient env inheritance.

Smoke-test on a machine with docker/podman:

```bash
RUN_CONTAINER_SANDBOX_TESTS=1 uv run pytest \
    tests/integration/test_container_sandbox_smoke.py -v
```
