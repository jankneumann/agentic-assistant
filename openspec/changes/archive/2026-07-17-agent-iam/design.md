# agent-iam — Design

## D1. AgentIdentity shape (SPIFFE-shaped placeholder)

Frozen dataclass in `core/capabilities/identity.py`:

```python
@dataclass(frozen=True)
class AgentIdentity:
    persona: str                      # execution boundary
    role: str                         # acting behavioral pattern
    delegation_chain: tuple[str, ...] = ()   # ancestor ROLE names, root-first
    session_id: str = ""              # harness thread_id / A2A contextId
    issued_at: datetime               # UTC, default now
```

Chain semantics: the chain EXCLUDES the current role — a root
identity has `()` and `chain_depth == len(chain)` equals the number
of completed hops. `delegate_to(sub_role)` returns a NEW principal
(persona inherited — delegation switches role, never persona; parent
role appended; session carried; fresh `issued_at`). Frozen dataclass
plus tuple chain makes mutation impossible; extension always builds a
new value.

Per the protocol-standards matrix (auth row): no converged standard
exists for agent identity; SPIFFE workload identity is the nearest
analogue, so the fields deliberately map onto it (persona/role ≈
trust domain/workload path, chain ≈ attestation path, issued_at ≈
SVID issuance). Migration is a mapping, not a rewrite.

## D2. Identity population sites (and only these, for now)

- `DelegationSpawner` — synthesizes the root principal from persona +
  parent role + harness `thread_id` (tolerating harnesses without
  one) unless an `identity` is injected; nested/hop identities are
  injected by whoever constructs the nested spawner.
- `check_model_call` — accepts an optional `identity`; synthesizes
  `AgentIdentity(persona, role)` from its existing string args when
  absent, so all P19 model-call gating becomes attributable without
  touching binding call sites.
- Harness `spawn_sub_agent` (DeepAgents + MSAF) — attaches
  `AgentIdentity(persona, role, session_id=thread_id)` to the
  `action_type="delegate"` check. DeepAgents previously had NO
  guardrail check on this path; it now mirrors MSAF's documented
  check (additive: `AllowAllGuardrails` default keeps behavior).

NOT population sites yet: tool-call checks (P24 ToolSpec wrap points
own that) and nested harness principals (`spawn_sub_agent` does not
thread an identity into the child harness — the child synthesizes a
fresh root; propagating the chain through the harness adapter API is
a follow-up recorded in tasks.md).

## D3. Chain depth enforcement lives in the spawner

`guardrails.delegation.max_chain_depth` (default 5, `0` unlimited)
is parsed into `DelegationConstraints`, but enforcement is in
`DelegationSpawner.delegate()` — before `check_delegation` — because
the depth is a property of the identity the spawner owns, and the
`check_delegation(parent_role, sub_role, task)` protocol signature is
frozen (widening it would break every conforming provider). The
default is enforced even for personas WITHOUT a `guardrails:` section
(read via the `GuardrailConfig` default), while `GuardrailConfig.
__bool__` deliberately ignores `max_chain_depth` so resolver
selection (PolicyGuardrails vs AllowAllGuardrails) is unchanged.

## D4. Identity-aware policy dimensions

`ActionPolicy` gains `role: str = "*"` (glob against `identity.role`,
falling back to `ActionRequest.role` for identity-less requests) and
`min_chain_depth: int = 0`. A depth-scoped policy can never match an
identity-less request — depth cannot be established, so the policy is
SKIPPED (evaluation falls through to the next policy) rather than
treated as matching or as a deny. First-match-wins ordering and all
P13 effects are unchanged.

## D5. Audit through the telemetry escape hatch (no new trace op)

The observability contract defines `start_span` as the sanctioned
escape hatch for non-first-class operations, so audit records are
spans named `guardrail.decision` with a fixed attribute set
(action_type, resource, persona, role, delegation_chain, chain_depth,
session_id, issued_at, decision ∈ {allow, deny, require_confirmation},
reason). The P27 precedent (extend the closed op vocabulary via spec
delta) was considered and NOT needed — no provider-protocol change,
no observability delta. Emission is call-site based
(`emit_guardrail_audit(request, decision)`) so `AllowAllGuardrails`
decisions are audited too; identity-less requests are skipped by
contract. Emission never raises (WARNING on failure) — audit must not
change enforcement outcomes. Task strings are NOT included in audit
attributes (they may hold user content; the `trace_delegation` span
already carries the hashed form).

## D6. Inbound A2A auth: static bearer, card-advertised

- Persona declares `auth.a2a: {type: bearer, token_env: REF}`;
  the REF resolves through `PersonaConfig.credentials` at
  `build_a2a_state` time. Three postures:
  - undeclared → unauthenticated (current loopback behavior) +
    startup WARNING naming the risk;
  - declared + resolvable → enforced on `POST /a2a/v1` and
    `POST /a2a/v1/message:stream`: HTTP 401 with `WWW-Authenticate:
    Bearer` (problem+json body) on missing/wrong token —
    HTTP-level, NOT a JSON-RPC error, per the A2A transport-auth
    convention; comparison via `secrets.compare_digest`;
  - declared + unresolvable → `build_a2a_state` raises (fail closed:
    declared auth must never silently turn off).
- The agent card is NOT gated (it is how clients discover the
  scheme) and advertises `securitySchemes: {bearer: {type: http,
  scheme: bearer}}` + `security: [{bearer: []}]`. Neither the token
  nor its ref appears on the card. `A2AServerState.expected_token`
  is `repr=False`.
- Only `bearer` exists today; OAuth 2.1 flows ride on the same
  declaration shape later.

**MCP-surface auth is explicitly out of scope**: P17 is building the
MCP server surface in parallel with this change. Integration
follow-up (recorded in tasks.md §7): when P17 lands, the same
persona-declared inbound auth (and the MCP authorization spec /
OAuth 2.1 posture from the standards matrix) must gate that surface,
reusing `auth.<surface>` declarations and the CredentialProvider
resolution introduced here.

## D7. OpenBao backend: mapping, auth, degradation

- **Namespace mapping (1:1 with P13)** — the persona-scoped `.env`
  namespace's vault image: ref `<REF>` for persona `<p>` is the KV
  v2 secret `<mount>/data/<p>/<REF>` with the credential under data
  key `value`. HTTP 200 → the ref is *present* (even an empty value
  masks the lower tiers, exactly like a present-but-empty `.env`
  key); 404 → *absent* → fall through to the layered
  `EnvCredentialProvider` (persona `.env` first, process env
  second). One secret per ref (rather than one blob per persona)
  keeps per-ref vault policies and versioning possible.
- **Auth** — AppRole (`POST /v1/auth/approle/login`); the client
  token is cached and proactively re-acquired
  `renew_margin_seconds` (60) before `lease_duration` elapses;
  `lease_duration: 0` = non-expiring. Re-login (rather than
  `renew-self`) keeps the client one-endpoint simple; noted as a
  possible optimization.
- **Bootstrap** — the `credentials:` section's `url_env` /
  `role_id_env` / `secret_id_env` refs resolve through the persona
  env provider (the vault cannot store its own bootstrap secret);
  unresolved bootstrap refs degrade to env with a WARNING.
- **Degradation** — any OpenBao failure (network, non-200, malformed
  body) logs ONE warning (re-armed after recovery) and falls back to
  the env tiers; never fatal, mirroring the memory posture. A fresh
  clone with no vault boots unchanged.
- **Client** — thin sync `httpx.Client` (the protocol method is
  sync); injectable transport for tests; NO hvac (ADR-0006: the
  OpenBao *server* is the shared stateful service; this client is
  freely-duplicated stateless mechanism). No OpenBao server exists in
  dev/CI — all tests run against `httpx.MockTransport`.
- **Wiring** — `PersonaRegistry.load` parses `credentials:` and calls
  `build_credential_provider(...)`; an injected
  `credential_provider_factory` still wins (the P13 injection point,
  unchanged).

Deferred: dynamic/short-lived secret engines, JWT auth methods,
per-principal vault policies management, and writing secrets (this
change is read-only KV).

## D8. What stays untouched

AG-UI `/chat` auth (loopback posture, P25 follow-up), approval
interrupt/resume (durable sessions), the `GuardrailProvider` and
`CredentialProvider` protocol signatures, the observability provider
protocol, and the a2a-server session/task semantics.
