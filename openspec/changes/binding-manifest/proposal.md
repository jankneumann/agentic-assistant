# Proposal: binding-manifest

## Why

Today a persona is defined by an ad-hoc mix of files: `persona.yaml`
under `personas/<name>/`, harness configuration scattered across
`harnesses.*` keys in that file, role overrides under
`personas/<name>/roles/`, environment-supplied database URLs, OpenBao
secret paths read by various scripts, and observability sink choices
inferred from environment variables. There is no single artifact that
declares "this is the deployment binding for persona X" — which model,
which harness, which memory backend, which identity provider, which
observability sink, which tool catalog, which sandbox provider.

This matters for three reasons that the architecture work in
`docs/architecture/primitives-and-providers.md` and
`docs/architecture/interface-stability.md` exposed:

1. **The SPI claim is verifiable only against a declared binding.** The
   stability ledger says providers slot behind interfaces per persona,
   but "per persona" has no formal expression today. A binding-validator
   that checks "this persona's chosen providers actually satisfy the
   capabilities the bound roles require" cannot exist without a manifest
   to validate against.
2. **Compatibility groups (cross-primitive role requirements) need an
   artifact to enforce against.** Some role requirements span multiple
   primitives (e.g. `interrupt_resume` needs harness support + session
   checkpoint support + memory replay safety). The capability matrix is
   per-interface; compatibility groups are cross-interface. Without a
   manifest, the validator has nowhere to run.
3. **`MemoryManager` has a load-bearing leak** (`src/assistant/core/memory.py`
   methods accepting `persona: str` that under git-as-multi-tenancy is
   invariant per process). The cleanup — drop the parameter, instance
   is already persona-bound — needs a declarative artifact that names
   the persona at construction so callers stop passing it around.

Defining the binding manifest now — before lifting `CapabilityRegistry`
(proposed next), before adding Pi as a third harness, before
provisioning the work-persona deployment — means those phases build
against a single declarative artifact rather than continuing the
implicit-config-everywhere pattern.

## What Changes

### 1. Binding manifest schema

Introduce a YAML schema at `personas/<name>/binding.yaml` (additive to
`persona.yaml`; `binding.yaml` is the deployment-shaped artifact,
`persona.yaml` continues to hold persona-identity fields) that
declares:

```yaml
binding:
  manifest_version: 1
  persona: personal
  providers:
    model:
      provider: anthropic
      model_id: claude-sonnet-4-5
      capabilities: [tool_calling, vision, thinking]
    harnesses:
      - kind: deep_agents
        default: true
        capabilities: [multi_agent_native, plan_mode]
      - kind: ms_agent_framework
        capabilities: [structured_output]
    memory:
      provider: postgres_graphiti
      connection: ${ASSISTANT_DATABASE_URL}
      capabilities: [semantic_search, forget, async_ingestion]
    identity:
      provider: openbao
      mount: ${ASSISTANT_VAULT_MOUNT}
      capabilities: [oauth_refresh, audit_trail]
    capability_registry:
      provider: http_tools
      sources: ${ASSISTANT_TOOL_SOURCES}
      capabilities: [openapi_discovery]
    observability:
      provider: langfuse
      endpoint: ${LANGFUSE_HOST}
      capabilities: [span_export]
    sandbox:
      provider: passthrough
      capabilities: []
  compatibility_groups:
    - name: interrupt_resume
      requires:
        harness: interrupt_resume
        session: checkpoint_mid_turn
        memory: replay_safe
```

The schema lives in `src/assistant/core/binding/schema.py` (Pydantic
models), with JSON Schema generated for editor support.

### 2. Binding validator

Introduce `src/assistant/core/binding/validator.py` that consumes a
`BindingManifest` and asserts:

- Every named provider exists in the registry of known providers
- Every advertised capability is supported by the provider implementation
- Every compatibility group's requirements are satisfied by the bound
  providers' advertised capabilities
- Every role under `personas/<name>/roles/` that declares
  `requires_capabilities:` has its requirements satisfied by at least
  one binding (per role, per harness)

Failures are loud (raised at process startup, before the REPL starts),
not deferred to the first turn that exercises the missing capability.

### 3. CLI `binding` subcommand

Add `assistant binding {check,show,explain}`:

- `check` — runs the validator against the current persona; exits
  non-zero on failure
- `show` — pretty-prints the resolved binding (providers, capabilities,
  satisfied compatibility groups)
- `explain <capability>` — for diagnostic use; shows which provider is
  expected to supply a named capability for the current persona

### 4. `MemoryManager` interface cleanup (BREAKING)

Drop the `persona: str` parameter from `MemoryManager` methods
(`get_context`, `store_fact`, `store_interaction`, `update_preference`,
`list_facts`, etc.). The instance is constructed from the binding
manifest's memory provider configuration, which is already
persona-scoped via the per-persona `session_factory`. The method
parameter was invariant-per-process leakage from a multi-tenant
assumption that doesn't hold under git-as-multi-tenancy.

Update `src/assistant/core/memory.py` and all call sites; update
`MemoryPolicy` protocol accordingly. Migrate tests.

### 5. `PersonaConfig` → binding integration

`src/assistant/core/persona.py` `PersonaRegistry.load(name)` is extended
to also load `binding.yaml`, validate it, and surface the resolved
`BindingManifest` as `persona.binding`. The CLI startup path
(`src/assistant/cli.py`) consumes `persona.binding` to instantiate
harness, memory, identity, observability, etc.

### 6. Compatibility group declarations on roles

Roles under `roles/<name>/role.yaml` and persona-specific overrides may
declare:

```yaml
requires_capabilities:
  - compatibility_group: interrupt_resume
  - capability: harness.streaming
  - capability: memory.semantic_search
```

The binding validator checks these declarations against the manifest's
providers at startup.

## Approaches Considered

### Approach A: Extend `persona.yaml` with a `binding:` top-level key — Effort: S

**Description**: Keep one config file per persona; add a `binding:`
section to `persona.yaml`.

- **Pros**: Single file per persona; no new artifact; minimal
  migration; backward-compatible.
- **Cons**: `persona.yaml` already mixes identity, defaults, schedules,
  and harness config; adding binding overloads it further. The
  deployment artifact is structurally different from the
  persona-identity artifact (deployment is per-deployment, identity
  is per-persona-across-deployments). Conflating them blocks future
  multi-deployment-per-persona scenarios (dev / staging / prod
  bindings of the same persona).

### Approach B (Recommended): Separate `binding.yaml` artifact alongside `persona.yaml` — Effort: M

**Description**: Add `binding.yaml` as the deployment-shaped artifact;
`persona.yaml` continues to hold persona-identity fields. Loader
composes both.

- **Pros**: Deployment artifact is structurally distinct from identity
  artifact; supports multiple bindings of the same persona (dev /
  staging / prod) via `binding.dev.yaml`, `binding.prod.yaml`;
  validator runs against the binding alone; cleaner separation of
  concerns.
- **Cons**: Two files instead of one; migration writes new files for
  existing personas. Mitigated by the loader synthesizing a default
  `binding.yaml` from the legacy `persona.yaml` `harnesses.*` keys when
  no explicit `binding.yaml` exists, deprecation-warning users to add
  an explicit file.

### Approach C: External binding registry service — Effort: L

**Description**: Manifests live in a separate service (e.g.
configuration store, OpenBao path, an HTTP endpoint); the persona's
local config declares only its name and the registry URL.

- **Pros**: Centralized binding management; bindings updatable without
  redeploying; useful for fleet-of-personas scenarios.
- **Cons**: Adds infrastructure dependency for what is fundamentally
  a per-deployment artifact; conflicts with git-as-multi-tenancy
  (each persona is its own git repo with its own config); over-engineered
  for the current ≤2 personas case.

### Selected Approach: **B — Separate `binding.yaml` artifact**

Chosen because it preserves the deployment-vs-identity distinction
that git-as-multi-tenancy makes possible, supports multi-binding
scenarios cleanly, and keeps the validator's input scope minimal.
Unselected:

- **A** rejected: overloads `persona.yaml` and blocks
  multi-binding-per-persona. The marginal simplicity of "one file"
  is not worth the conflation.
- **C** rejected: contradicts git-as-multi-tenancy; over-engineered
  for current scale.

## Capabilities

### New Capabilities

- `binding-manifest`: Declarative YAML artifact at
  `personas/<name>/binding.yaml` enumerating providers, advertised
  capabilities, and compatibility groups for a persona deployment.
  Validated at process startup; surfaced as `persona.binding`.
- `binding-validator`: Runtime validator that asserts every named
  provider exists, every advertised capability is supported, every
  compatibility group is satisfied, and every role's required
  capabilities are met by the bound providers.
- `binding-cli`: `assistant binding {check,show,explain}` subcommands
  for human and CI use.

### Modified Capabilities

- `memory-policy`: `MemoryManager` methods drop the `persona: str`
  parameter. Instance is persona-bound at construction via the
  manifest's memory provider configuration. **BREAKING**.
- `persona-registry`: `PersonaRegistry.load(name)` extended to load
  `binding.yaml`, validate it, and attach a resolved
  `BindingManifest` to the `PersonaConfig` as `persona.binding`.
  Backward-compatible synthesizer: when `binding.yaml` is absent, a
  default manifest is generated from the legacy `persona.yaml`
  `harnesses.*` keys plus environment-supplied connection strings,
  with a deprecation warning.
- `role-registry`: Role definitions may declare
  `requires_capabilities:` (compatibility group or capability). The
  validator enforces these against the binding.

## Impact

- **Affected code**: `src/assistant/core/binding/` (new), `src/assistant/core/persona.py` (loader),
  `src/assistant/core/memory.py` (drop persona param),
  `src/assistant/core/role.py` (parse `requires_capabilities`),
  `src/assistant/cli.py` (binding subcommand + startup validation),
  most call sites of `MemoryManager.*` methods (drop persona arg).
- **Affected specs**: `memory-policy` (modified — persona param drop),
  `persona-registry` (modified — binding attached), `role-registry`
  (modified — `requires_capabilities` field), new: `binding-manifest`,
  `binding-validator`, `binding-cli`.
- **Dependencies**: P1.8 capability-protocols (CapabilitySet exists),
  P2 memory-architecture (MemoryManager exists and needs cleanup),
  P3 http-tools-layer (HttpToolRegistry exists as one provider),
  P4 observability (Langfuse provider exists), P5 ms-graph-extension
  (MS Agent Framework harness exists). All archived; no blockers.
- **Breaking changes**: `MemoryManager` method signatures; all
  call sites updated in this change. Personas without
  `binding.yaml` continue to work via the legacy-synthesizer with
  a deprecation warning; behaviour unchanged until they explicitly
  migrate.

## Out of Scope (deferred to later phases)

- **`CapabilityRegistry` lifting** — unifying `HttpToolRegistry`,
  extension tools, and MCP servers behind a single registry with
  multiple projections is the proposed `capability-registry` phase,
  which depends on this one (the binding declares which
  CapabilityRegistry provider is in use).
- **Pi harness** — `pi-harness` phase depends on `capability-registry`
  for MCP projection of tools; not in scope here.
- **Persona deployment kit** — the scripts and templates that
  scaffold a new persona deployment end-to-end (DB provisioning,
  vault provisioning, etc.) are the proposed `persona-deployment-kit`
  phase. This change defines the manifest the kit will populate;
  the kit itself is separate.
- **Conformance test harness** — `tests/conformance/` infrastructure
  for SPI conformance is the proposed `conformance-test-harness`
  phase. This change writes scenario-level tests for the binding
  validator only.
- **Multi-binding-per-persona** (dev / staging / prod bindings) —
  the schema is designed to support `binding.dev.yaml` /
  `binding.prod.yaml` selection, but the loader only handles the
  default `binding.yaml` in this change.
- **Hot-reload of bindings** — bindings are read at startup; runtime
  rebinding is not supported.
