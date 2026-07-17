# agent-iam — Tasks

## 1. AgentIdentity principal

- [x] 1.1 `core/capabilities/identity.py` — frozen `AgentIdentity`
  (persona, role, delegation_chain tuple, session_id, issued_at),
  `chain_depth`, `delegate_to`, `chain_display`
- [x] 1.2 `core/capabilities/types.py` — optional
  `ActionRequest.identity` (default `None`; existing sites unchanged)
- [x] 1.3 Population sites: `check_model_call` (synthesizes from
  persona/role, accepts injected identity), MSAF `spawn_sub_agent`
  (identity on the existing delegate check), DeepAgents
  `spawn_sub_agent` (new delegate check, mirroring MSAF)

## 2. Delegation chain attribution + depth

- [x] 2.1 `guardrails.delegation.max_chain_depth` parsing
  (default 5, `0` unlimited, validated; `GuardrailConfig.__bool__`
  unchanged so resolver selection is untouched)
- [x] 2.2 `delegation/spawner.py` — root identity synthesis (or
  injected parent identity), `delegate_to` per hop, depth ceiling
  enforcement (PermissionError naming the chain), chain logged on
  every decision, audit emission for depth + guardrail decisions

## 3. Identity-aware policies + audit

- [x] 3.1 `ActionPolicy.role` glob + `min_chain_depth` (parse +
  validation + unknown-policy-key rejection); `_match_policy`
  consumes `action.identity` (depth policies skip identity-less
  requests)
- [x] 3.2 `core/capabilities/audit.py` — `emit_guardrail_audit`
  through the telemetry `start_span` escape hatch
  (`guardrail.decision`, fixed attribute set, never raises)

## 4. Inbound A2A auth

- [x] 4.1 `core/persona.py` — `A2AAuthConfig` + `parse_a2a_auth`
  (bearer only, actionable errors), `PersonaConfig.a2a_auth`
- [x] 4.2 `a2a/server.py` — token resolution through
  `PersonaConfig.credentials` in `build_a2a_state` (unresolvable →
  startup error; undeclared → WARNING), 401 + `WWW-Authenticate` on
  both POST routes (constant-time compare), card routes ungated,
  `expected_token` repr-excluded
- [x] 4.3 `a2a/{types,agent_card}.py` — `HTTPAuthSecurityScheme`,
  card `securitySchemes` + `security` when auth is declared

## 5. OpenBao credential backend

- [x] 5.1 `core/capabilities/openbao.py` —
  `OpenBaoCredentialProvider` (KV v2 read at
  `<mount>/data/<persona>/<ref>`, AppRole login, proactive renewal
  before TTL, warn-once degradation to the env tiers),
  `parse_credentials_config` (actionable errors),
  `build_credential_provider`
- [x] 5.2 `core/persona.py` — parse `credentials:` at load; backend
  selection behind the P13 `credential_provider_factory` injection
  point (injected factory still wins)

## 6. Tests

- [x] 6.1 `tests/test_agent_identity.py` — identity immutability /
  chain extension / defaults, ActionRequest attachment,
  `decision_outcome`, audit record shape, identity-less skip,
  audit-failure isolation, `check_model_call` synthesis + injection
- [x] 6.2 `tests/test_identity_policies.py` — role glob (identity +
  fallback), `min_chain_depth` (deep/shallow/no-identity), additivity
  with resource globs, parse validation, `max_chain_depth` parsing +
  falsy-default, spawner root synthesis / depth denial with chain in
  reason / hop-by-hop extension / audit on allow + deny
- [x] 6.3 `tests/a2a/test_auth.py` — parse_a2a_auth matrix, startup
  warning + fail-closed unresolvable token, 401 without/wrong/wrong-
  scheme token, 200 with token, REST alias parity, unauthenticated
  server unchanged, card securitySchemes (+ no token/ref leak), card
  omits fields when unauthenticated, state repr hygiene
- [x] 6.4 `tests/test_openbao_credentials.py` — protocol conformance,
  login + per-persona KV path, empty-value masking, 404 fallback,
  token caching + renewal-before-TTL + zero-lease, unreachable/login-
  failure/5xx degradation (warn once), `credentials:` parse matrix,
  builder wiring (env backend, unresolved bootstrap degrade,
  persona-`.env` bootstrap), persona-load validation error + degrade
  + injected-factory precedence — all via `httpx.MockTransport`
- [x] 6.5 Existing suites stay green (spawner duck-typed persona /
  harness fakes tolerated)

## 7. Docs, spec deltas, follow-ups

- [x] 7.1 Spec deltas: agent-identity (ADDED capability),
  credential-provider, guardrail-provider, a2a-server,
  delegation-spawner; `openspec validate agent-iam --strict` passes
- [x] 7.2 `personas/_template/persona.yaml` — `auth.a2a`,
  `credentials:` backend, identity policy dims, `max_chain_depth`
- [x] 7.3 CLAUDE.md — Agent IAM section
- [x] 7.4 FOLLOW-UP (P17 integration): gate the MCP server surface (owner approved 2026-07-17; 17.1 resolved via D1 addendum)
  with the same persona-declared inbound auth (`auth.mcp`, MCP
  authorization spec / OAuth 2.1 posture) + CredentialProvider
  resolution introduced here — file as a `followup` issue when P17
  lands
- [x] 7.5 FOLLOW-UP: propagate the delegation-chain identity into (owner approved 2026-07-17; 17.1 resolved via D1 addendum)
  nested harness principals (extend `spawn_sub_agent` or the harness
  constructor) so multi-hop chains survive harness boundaries
- [x] 7.6 Gates: `uv run pytest tests/`, `uv run ruff check src
  tests`, `uv run mypy src tests`
