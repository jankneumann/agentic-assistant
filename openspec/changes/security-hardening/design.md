# security-hardening — Design

## D1. Persona-scoped `.env` mechanics: scoped namespace, not env mutation

The persona `.env` is parsed into an in-memory mapping held by that
persona's `EnvCredentialProvider` instance (`scoped=` constructor
argument). It is NEVER written into `os.environ`:

- **Isolation**: two personas loaded in the same process resolve the
  same ref name to different values; neither sees the other's
  namespace, and subprocesses / other libraries never inherit persona
  secrets ambiently.
- **Precedence**: a ref *present* in the persona `.env` always wins
  over the process environment — including when its value is empty,
  which deliberately masks a process variable for that persona.
  Refs absent from the `.env` fall back to `os.environ` (the P24
  default semantics), so a fresh clone with no `.env` behaves exactly
  as before.
- **Parser**: minimal and dependency-free (`KEY=VALUE`, `#` comments,
  optional `export` prefix, one pair of surrounding quotes stripped).
  Rejected alternative: adding `python-dotenv` — interpolation and
  multiline support are not needed, and a new dependency for ~30
  lines of parsing fails the repo's dependency bar. Malformed lines
  are skipped with a WARNING that names the line NUMBER only, never
  the content (which may hold a secret).
- **Leak hygiene**: `PersonaConfig.credentials` is declared with
  `repr=False` so the scoped namespace can't leak through dataclass
  reprs/logs.

**OpenBao mapping (P25, per docs/architecture-analysis/
2026-07-16-protocol-standards.md)**: the scoped namespace is exactly
the shape of a per-persona OpenBao mount. P25's provider implements
the same `CredentialProvider` protocol with `get_credential(ref)`
reading `secret/<persona>/<ref>` first and the process environment as
the standalone/dev fallback tier — same precedence order, different
backend, zero call-site changes. The injection point is
`PersonaRegistry(credential_provider_factory=...)`, which receives
`(persona_name, persona_dir)` and returns the provider stored on
`PersonaConfig.credentials`; every downstream consumer (http_tools
discovery, model bindings via the harnesses, graphiti, MSAL) reads
from that one field.

## D2. Seam coverage and the one deliberate exception

All persona-credential call-site families now flow through the seam:
persona `*_env` config resolution, tool-source auth headers, graphiti
connection settings, MSAL tenant/client/secret, and
`ModelRef.credential_ref` (already seamed in P19; harnesses now pass
the persona-scoped provider). `telemetry/config.py`'s Langfuse key
reads stay on `os.environ`: they are host-level observability
configuration owned by the operator, not persona credentials — there
is no persona in scope when telemetry initializes. Recorded here so
the exception is intentional, not an oversight.

`resolve_auth_header` semantics change slightly: a ref that resolves
to an EMPTY value now raises `KeyError` (previously only an *unset*
variable did; a set-but-empty variable produced a useless
`Bearer <empty>` header). Discovery already treated the `KeyError` as
skip-with-warning, so the observable effect is a clearer failure for
a misconfigured source.

## D3. Extension integrity: verify-before-exec, fail closed on manifests

- Verification happens in `_load_extension_instances` before
  `_load_private_extension` (which is the only path that calls
  `spec.loader.exec_module`). The manifest (`manifest.yaml`, shape
  `{version: 1, hashes: {<file>: "sha256:<hex>"}}`) lives next to the
  extension files inside the private persona repo, so tampering with
  code without updating the manifest is what the check catches; an
  attacker who can rewrite both has full control of the private repo
  and is out of scope (that is P25/P22 territory).
- **Missing manifest → allowed with WARNING**: current personas keep
  working; the warning names the `assistant persona hash-extensions`
  command.
- **Mismatch, unlisted file, or malformed manifest → blocked**: the
  extension is disabled with an ERROR and is NOT executed. There is
  deliberately NO fallback to a same-named public module — silent
  implementation swapping on tampering would be worse than losing the
  extension. A malformed manifest blocks every private extension in
  the directory (fail closed: an unreadable integrity declaration
  must not degrade to "unverified").
- **TOCTOU**: the check hashes the file and `importlib` re-reads it
  microseconds later. Accepted: the manifest defends against at-rest
  tampering of the config repo, not against an attacker racing writes
  inside the running process.
- **CLI UX**: `assistant persona hash-extensions -p <name>` hashes
  every `*.py` in the persona's `extensions_dir` and (re)writes the
  manifest, printing each digest. Regeneration after an intentional
  edit is the documented operator flow. Rejected alternative: a
  `--verify` dry-run mode — `load_extensions` already logs the
  verdicts, and the minimal CLI keeps P13 small.

## D4. PolicyGuardrails: policy-first, budgets as ceilings

Evaluation order in `check_action`: action policies (declaration
order, first match wins) → model-call budget ceilings. An explicit
`allow` policy does not bypass ceilings — policies are per-action
rules, budgets are per-persona ceilings; both must pass.

**Budget cost estimation** (pre-call, so real token counts don't
exist yet), in order:

1. `metadata["estimated_cost_usd"]` when a caller provides one;
2. `compute_cost(metadata["pricing"], estimate_input_tokens,
   estimate_output_tokens)` — P19's `check_model_call` already puts
   `ModelRef.pricing` on the request; the token estimates are
   configurable per persona (defaults 2000/500);
3. `default_call_cost_usd` (default `0.0`).

Cost is never guessed (mirrors `compute_cost`'s degradation): with
the default of `0.0`, entries without pricing metadata pass without
consuming budget — a persona that wants unpriced models limited sets
`default_call_cost_usd`. A denied call does not record spend; an
allowed call records its estimate. Windows are calendar-day and
calendar-month in UTC (simple, deterministic, matches how ceilings
are stated); rejected alternative: rolling 24h/30d windows — harder
to reason about ("why am I still blocked?") for no security gain.

**`require_confirmation`**: `PolicyGuardrails` returns the decision
faithfully (`allowed=True, require_confirmation=True`). For
`model_call`, P19's `check_model_call` hook already treats that as a
deny until the approval interrupt flow exists (owner review verdict
#2, preserved verbatim); interrupt/resume is NOT built here — it
rides on durable sessions (capability-protocols-v2 deferral).

## D5. Budget persistence: process ledger registry + optional file ledger

Harnesses construct a fresh `CapabilityResolver` (and therefore a
fresh `PolicyGuardrails`) per lookup, so budget state cannot live on
the provider instance. Ledgers are process-wide singletons keyed by
`persona:persistence-target` (`budget_ledger_for`), with a
`_clear_budget_ledgers()` test hook (cleared by an autouse conftest
fixture).

- Default: `InMemoryBudgetLedger` — ceilings reset on process
  restart. Documented and acceptable for the interactive-CLI usage
  pattern.
- `budgets.model_call.persist: file` → `JsonFileBudgetLedger` at
  `<persona_dir>/.cache/guardrails/spend.json` (the persona
  template's `.gitignore` already excludes `.cache/`). Entries older
  than the previous month's start are pruned on write. A corrupt
  spend file degrades to empty with a WARNING — the permissive
  direction, chosen because bricking every model call on a corrupt
  counter file is worse than a one-day ceiling reset.
- **Deferred: persona-DB-backed ledger.** The mission allows it
  ("optional persisted counter via the persona DB if present — keep
  simple"); it was deliberately NOT built: `check_action` is a sync
  protocol method while the persona DB stack is async SQLAlchemy, so
  a DB ledger needs either a sync engine bridge or a protocol change,
  plus an Alembic migration. The `BudgetLedger` protocol is the seam
  a `PostgresBudgetLedger` plugs into when durable sessions / P25
  make it worth the machinery.

## D6. Resolver selection

`CapabilityResolver._resolve_guardrails`: factory override wins
(unchanged); else `PolicyGuardrails(persona.guardrails,
persona=persona.name)` when the parsed `GuardrailConfig` is truthy
(any policy, budget, or delegation constraint); else
`AllowAllGuardrails`. Applied identically on the host and sdk
branches — host harnesses get the same policy floor. `guardrails:`
parsing failures at persona load raise the same actionable
`ValueError` shape as the `models:` registry.
