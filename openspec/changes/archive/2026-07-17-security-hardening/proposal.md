# security-hardening — Credential Scoping, Extension Integrity, First Real Guardrails (P13)

## Why

Three security gaps remain open after P10/P19/P24 landed their
contracts (roadmap row P13; perplexity §4/§8.12):

1. **Credential scoping is process-global.** The `CredentialProvider`
   seam exists (P24 contract, P19 `EnvCredentialProvider`), but only
   the model bindings consume it — persona loading (`_env()`),
   HTTP tool-source auth, graphiti, and MSAL still read `os.environ`
   directly, and every persona shares one flat process namespace. Two
   personas cannot hold different values for the same credential name,
   and a compromised extension in one persona sees every persona's
   secrets.
2. **Private persona extensions execute unverified.** `PersonaRegistry`
   `exec_module()`s whatever `.py` file sits in the persona submodule's
   `extensions/` dir. A tampered private config repo becomes arbitrary
   code execution with no detection point.
3. **Guardrails are allow-all everywhere.** P19 gated every model
   dispatch through `GuardrailProvider.check_action(action_type=
   "model_call")` and P24 specced the protocol — but the only
   implementation is `AllowAllGuardrails`. Budgets, action policies,
   and delegation constraints have a seam and no policy.

## What Changes

- **Finish `CredentialProvider` wiring** so no secret read bypasses
  the seam: persona loading (`core/persona.py`), tool-source auth
  (`http_tools/auth.py` + `discovery.py`), graphiti factory
  (`core/graphiti.py`), and MSAL strategy construction
  (`core/msal_auth.py`) all resolve through the persona's provider;
  the model bindings and both SDK harnesses now receive the
  persona-scoped provider instead of a fresh process-env one.
- **Per-persona `.env` files**: a persona directory may contain a
  git-ignored `.env` loaded into a persona-SCOPED credential
  namespace — never into process `os.environ`. Resolution order:
  persona `.env` first, process environment fallback. A key present
  in the `.env` wins even when empty (deliberate masking). The scoped
  namespace maps 1:1 onto per-persona OpenBao mounts when P25 lands.
- **Extension integrity manifests**: an optional `manifest.yaml` next
  to private persona extensions lists SHA-256 hashes per extension
  file; `PersonaRegistry.load_extensions*` verifies BEFORE
  `spec.loader.exec_module()`. Missing manifest → allowed with a
  WARNING (current personas keep working). Present-but-mismatched
  (or unlisted, or malformed manifest) → the extension is NOT
  executed and is disabled with an ERROR (P10 failure-isolation),
  with no fallback to a same-named public module. New CLI:
  `assistant persona hash-extensions -p <name>` generates/updates
  the manifest.
- **First non-allow-all `GuardrailProvider`**: `PolicyGuardrails`,
  configured from a persona `guardrails:` section — (a) `model_call`
  budgets (per-persona daily/monthly USD ceilings fed by P19 cost
  metadata on `ActionRequest.metadata`; process-wide in-memory ledger
  by default, optional JSON-file persistence under the persona's
  git-ignored `.cache/`), (b) action policies
  (allow/deny/require_confirmation by `action_type` + resource glob,
  first match wins), (c) delegation constraints (denied sub-role
  globs + max task length; existing `check_delegation` semantics
  preserved). Per the P19 owner-review verdict #2,
  `require_confirmation` on `model_call` DENIES at the budget hook
  until the approval interrupt flow exists — this change does NOT
  build interrupt/resume (needs durable sessions).
- **Resolver wiring**: both host and sdk branches select
  `PolicyGuardrails` when the persona declares a non-empty
  `guardrails:` section, else `AllowAllGuardrails` (unchanged
  default); the `guardrail_factory` override is preserved.

## Impact

- Affected specs: `credential-provider` (persona scoping + `.env`),
  `guardrail-provider` (PolicyGuardrails requirements),
  `persona-registry` (credential-provider loading + manifest
  verification + `guardrails:` parsing), `http-tools` (auth header
  resolution through the seam), `cli-interface` (new subcommand).
- Affected code: `core/capabilities/{credentials,guardrails,resolver}.py`,
  `core/{persona,graphiti,msal_auth}.py`, new
  `core/extension_integrity.py`, `http_tools/{auth,discovery}.py`,
  `harnesses/sdk/{deep_agents,ms_agent_fw}.py`, `web/app.py`,
  `cli.py`.
- Behavior preserved: personas without `.env`, manifest, or
  `guardrails:` behave exactly as before (process-env resolution,
  unverified-with-warning load, allow-all guardrails).
- Deferred (documented in design.md): persona-DB-backed budget
  ledger, approval interrupt/resume, OpenBao backend (P25), Langfuse
  key reads in `telemetry/config.py` (host observability config, not
  persona credentials).
