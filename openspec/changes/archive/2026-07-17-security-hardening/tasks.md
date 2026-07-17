# security-hardening — Tasks

## 1. Per-persona credential scoping

- [x] 1.1 `core/capabilities/credentials.py` — `EnvCredentialProvider`
  scoped-namespace layer, dependency-free `.env` parser
  (`parse_env_file` / `load_env_file`), `persona_credential_provider`
- [x] 1.2 `core/persona.py` — persona load resolves every `*_env`
  secret through the persona-scoped provider;
  `PersonaConfig.credentials` (repr=False);
  `PersonaRegistry(credential_provider_factory=...)` injection point;
  module-level `_env()` removed
- [x] 1.3 `http_tools/auth.py` + `discovery.py` — `resolve_auth_header`
  and `discover_tools` accept the persona provider; empty resolution
  raises `KeyError` naming the ref
- [x] 1.4 Call sites pass the persona provider — `cli.py` (REPL +
  `--list-tools`), `web/app.py`, `core/graphiti.py`,
  `core/msal_auth.py`, harness `_resolve_credential_provider`
  (DeepAgents + MSAF prefer `persona.credentials`)

## 2. Extension integrity

- [x] 2.1 `core/extension_integrity.py` — manifest load/verify
  (`sha256:` digests, bare-hex accepted), `generate_manifest`,
  verdicts (verified / unverified / mismatch / unlisted / malformed)
- [x] 2.2 `core/persona.py` — verify BEFORE
  `spec.loader.exec_module()`; missing manifest → WARNING + load;
  blocked verdicts → ERROR + extension disabled, no public fallback
- [x] 2.3 `cli.py` — `assistant persona hash-extensions -p <name>`

## 3. PolicyGuardrails

- [x] 3.1 `core/capabilities/guardrails.py` — `GuardrailConfig` +
  `parse_guardrail_config` validation; `ActionPolicy` /
  `ModelCallBudget` / `DelegationConstraints`
- [x] 3.2 `PolicyGuardrails` — policy-first check_action, model_call
  ceilings (estimation ladder, UTC calendar windows, deny-not-record),
  check_delegation (denied globs + max task chars), declare_risk tiers
- [x] 3.3 Budget ledgers — `BudgetLedger` protocol,
  `InMemoryBudgetLedger`, `JsonFileBudgetLedger`
  (`.cache/guardrails/spend.json`, prune, corrupt-file degrade),
  process-wide registry + `_clear_budget_ledgers()` test hook
- [x] 3.4 `core/persona.py` — parse + validate `guardrails:` at load
  (`PersonaConfig.guardrails`)
- [x] 3.5 `core/capabilities/resolver.py` — `_resolve_guardrails` on
  host + sdk branches; factory override preserved

## 4. Tests

- [x] 4.1 `tests/test_credential_scoping.py` — parsing, precedence,
  empty-value masking, two-persona isolation without os.environ
  pollution, injected-provider persona load, auth-header via
  provider, repr hygiene
- [x] 4.2 `tests/test_extension_integrity.py` — generate/verify,
  verdicts, tampered file never executes + sibling isolation, no
  public fallback, malformed-manifest fail-closed, CLI subcommand
- [x] 4.3 `tests/test_policy_guardrails.py` — protocol conformance,
  config validation errors, policy allow/deny/require_confirmation,
  require_confirmation=deny for model_call via check_model_call,
  budget allows-then-denies across calls (daily/monthly windows,
  P19 pricing metadata, file ledger, resolver-rebuild persistence),
  delegation constraints + spawner PermissionError, declare_risk,
  resolver selection
- [x] 4.4 Existing suites adjusted minimally: fake `discover_tools`
  signatures widened (`credentials` kwarg); lifecycle test helper
  writes a manifest; conftest autouse ledger clear

## 5. Docs + gates

- [x] 5.1 Spec deltas: credential-provider, guardrail-provider,
  persona-registry, http-tools, cli-interface;
  `openspec validate security-hardening --strict` passes
- [x] 5.2 `personas/_template/persona.yaml` — commented `guardrails:`
  example; template README note not required (`.env` already
  gitignored by template)
- [x] 5.3 CLAUDE.md — guardrails no longer described as allow-all-only
- [x] 5.4 Gates: `uv run pytest tests/`, `uv run ruff check src
  tests`, `uv run mypy src tests`
