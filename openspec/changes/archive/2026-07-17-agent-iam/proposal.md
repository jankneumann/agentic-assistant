# agent-iam — Agent Identity & Access Management (P25)

## Why

Three trust gaps remain after P13 (credential scoping, first real
guardrails) and P6 (A2A surface) landed — roadmap row P25, ecosystem
pillar 3, and the AgentCore Identity lesson (inbound vs outbound auth
must be modeled explicitly):

1. **Decisions are not attributable.** Guardrail checks carry only
   flat `persona`/`role` strings; P12's delegation chains vanish at
   the decision point, so a policy cannot distinguish the root agent
   from a fifth-hop sub-agent, nothing bounds delegation depth, and
   there is no audit trail of who was allowed to do what.
2. **Inbound: the A2A surface is unauthenticated.** Anyone who can
   reach the port can drive the persona. Safe only because the server
   binds loopback by default — a posture, not a control. The A2A spec
   already defines where auth declarations live (card
   `securitySchemes`).
3. **Outbound: secrets are ambient.** The `CredentialProvider` seam
   (P24 contract 7) and the persona-scoped `.env` tiers (P13) exist,
   but the production backend — OpenBao, already operated as a shared
   stateful service (ADR-0006) — is not implemented, so every
   credential is a long-lived env value rather than a vault-managed
   secret behind a per-persona agent principal.

## What Changes

- **`AgentIdentity` principal** (`core/capabilities/identity.py`):
  frozen dataclass (persona, role, `delegation_chain` tuple,
  session/thread id, issued_at), SPIFFE-shaped placeholder per the
  protocol-standards matrix. `ActionRequest` gains an optional
  `identity` field (default `None` — existing call sites unchanged),
  populated at the natural construction sites: the delegation
  spawner, `check_model_call` (synthesizes one from persona/role when
  not injected), and both harness `spawn_sub_agent` paths.
- **Delegation chains become attributable**: each hop derives the
  child principal via `identity.delegate_to(sub_role)` (parent role
  appended to the chain); the spawner enforces
  `guardrails.delegation.max_chain_depth` (configurable, default 5,
  `0` = unlimited) and logs the chain on every decision.
- **Identity-aware policy dimensions** on `PolicyGuardrails`
  (additive to `action_type`/resource globs): `role:` glob on the
  acting role and `min_chain_depth:` matching only sufficiently deep
  delegation chains.
- **Inbound A2A auth**: persona `auth.a2a: {type: bearer, token_env:
  ...}` — the expected token resolves through the `CredentialProvider`
  seam (never raw `os.environ`); the JSON-RPC and REST-alias routes
  return HTTP 401 (+ `WWW-Authenticate: Bearer`) without a valid
  constant-time-compared bearer token; the agent card advertises the
  scheme via `securitySchemes` + `security` and stays publicly
  readable. No declaration → current loopback-unauthenticated
  behavior with a startup WARNING; declared-but-unresolvable token →
  startup error (declared auth never silently disables). MCP-surface
  auth is explicitly OUT of scope (P17 builds that surface in
  parallel — integration follow-up recorded in design.md/tasks.md).
- **Outbound token vault — `OpenBaoCredentialProvider`**
  (`core/capabilities/openbao.py`): thin httpx client (no hvac, no
  new deps) implementing the P24 seam — KV v2 reads at
  `<mount>/data/<persona>/<ref>` (data key `value`), AppRole login
  with proactive token re-acquisition before TTL expiry, and layered
  fallback to the P13 env tiers when unconfigured/unreachable
  (WARNING, never fatal — memory's degradation posture). Persona
  `credentials: {backend: openbao, url_env, role_id_env,
  secret_id_env, mount}` validated with the actionable-error posture;
  wired through `PersonaRegistry` at the
  `credential_provider_factory` injection point P13 left (an injected
  factory still wins).
- **Audit trail**: every guardrail decision carrying an identity
  emits a structured `guardrail.decision` record through the existing
  telemetry provider's `start_span` escape hatch (no new trace op —
  the observability contract is untouched). Telemetry is the sink; a
  durable audit store is deferred with the approval interrupt flow.

## Impact

- Affected specs: `agent-identity` (NEW capability),
  `credential-provider` (OpenBao backend), `guardrail-provider`
  (identity dimensions + audit), `a2a-server` (inbound auth + card
  security schemes), `delegation-spawner` (chain attribution/depth).
- Affected code: `core/capabilities/{identity,audit,openbao}.py`
  (new), `core/capabilities/{types,guardrails,model_bindings}.py`,
  `core/persona.py`, `delegation/spawner.py`,
  `a2a/{types,agent_card,server}.py`,
  `harnesses/sdk/{deep_agents,ms_agent_fw}.py`,
  `personas/_template/persona.yaml`, CLAUDE.md.
- Behavior preserved: personas without `auth.a2a` / `credentials:`
  and requests without an identity behave exactly as before; the
  `ActionRequest` field and the delegation depth ceiling (default 5,
  far above any legitimate chain today) are the only always-on
  additions.
- Deferred (design.md): MCP-surface auth (P17 integration), identity
  propagation into nested harness principals, OpenBao dynamic/
  short-lived secret engines and JWT auth, durable audit store,
  agent-card auth for the AG-UI `/chat` surface.
