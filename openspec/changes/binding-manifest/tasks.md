# Tasks — binding-manifest

Tasks are ordered TDD-style within each phase: test tasks first,
implementation tasks depend on their corresponding tests. Phases are
ordered so each builds on a compileable/importable tree from the
prior phase.

## Phase 1 — Schema and types

- [ ] 1.1 Write `tests/core/binding/test_schema.py` encoding the
  scenarios from `specs/binding-manifest/spec.md`:
  - `BindingManifest` parses a valid `binding.yaml`
  - `BindingManifest` rejects unknown providers
  - `BindingManifest` rejects unknown capabilities for a known
    provider
  - `BindingManifest` parses compatibility groups
  - `BindingManifest` round-trips through YAML
  **Spec scenarios**: all from `binding-manifest` spec.
  **Dependencies**: none

- [ ] 1.2 Implement `src/assistant/core/binding/__init__.py` and
  `src/assistant/core/binding/schema.py`:
  - Pydantic models: `BindingManifest`, `ProvidersBinding`,
    `ModelBinding`, `HarnessBinding`, `MemoryBinding`,
    `IdentityBinding`, `CapabilityRegistryBinding`,
    `ObservabilityBinding`, `SandboxBinding`, `CompatibilityGroup`
  - `BindingManifest.load(path: Path) → BindingManifest`
  - `BindingManifest.synthesize_from_legacy(persona: PersonaConfig)
    → BindingManifest` (for backward compatibility)
  - Generate JSON Schema for editor support; commit under
    `personas/_template/schemas/binding.schema.json`
  **Design decisions**: see `design.md` (to be authored via
  /plan-feature).
  **Dependencies**: 1.1

## Phase 2 — Validator

- [ ] 2.1 Write `tests/core/binding/test_validator.py` encoding the
  scenarios from `specs/binding-validator/spec.md`:
  - Unknown provider rejected at startup
  - Provider missing an advertised capability rejected
  - Compatibility group unsatisfied rejected
  - Role with `requires_capabilities` unsatisfied rejected
  - Valid manifest passes validation
  **Spec scenarios**: all from `binding-validator` spec.
  **Dependencies**: 1.2

- [ ] 2.2 Implement `src/assistant/core/binding/validator.py`:
  - `BindingValidator.validate(manifest, role_registry, provider_registry)`
  - `ProviderRegistry` — central registry of known providers and
    their advertised capabilities; populated from existing modules
    (DeepAgentsHarness, MSAgentFrameworkHarness, MemoryManager,
    HttpToolRegistry, LangfuseProvider, etc.)
  - Failure mode: raise `BindingValidationError` with full list of
    failures (don't stop at first)
  **Dependencies**: 2.1

## Phase 3 — MemoryManager cleanup (BREAKING)

- [ ] 3.1 Write `tests/core/test_memory_persona_param_removed.py`
  encoding that `MemoryManager` methods no longer accept `persona`:
  - `get_context(role, limit=…)` signature
  - `store_fact(key, value)` signature
  - `store_interaction(…)` signature
  - `update_preference(…)` signature
  - `list_facts()` signature
  **Spec scenarios**: from modified `memory-policy` spec.
  **Dependencies**: none (independent of binding phases)

- [ ] 3.2 Refactor `src/assistant/core/memory.py`:
  - Drop `persona: str` from `get_context`, `store_fact`,
    `store_interaction`, `update_preference`, `list_facts`, and any
    other persona-parameterized method
  - Add `self._persona_name: str` set at construction (for
    logging/observability) from the session_factory's persona binding
  - Update `@trace_memory_op` to read persona from
    `self._persona_name`
  **Dependencies**: 3.1

- [ ] 3.3 Update all call sites:
  - `src/assistant/cli.py` REPL code
  - `src/assistant/harnesses/sdk/deep_agents.py`
  - `src/assistant/harnesses/sdk/ms_agent_fw.py`
  - `src/assistant/delegation/*`
  - Any extension code that touches MemoryManager
  - Existing tests in `tests/core/test_memory.py` and elsewhere
  **Dependencies**: 3.2

- [ ] 3.4 Update `MemoryPolicy` protocol in
  `src/assistant/core/capabilities/` to match new method signatures.
  **Dependencies**: 3.2

## Phase 4 — PersonaRegistry integration

- [ ] 4.1 Write `tests/core/test_persona_binding_load.py` encoding:
  - `PersonaRegistry.load(name)` returns a `PersonaConfig` with
    `binding` attribute when `binding.yaml` exists
  - `PersonaRegistry.load(name)` synthesizes a binding (with
    deprecation warning) when `binding.yaml` is absent
  - Validation fails loudly at load time for invalid bindings
  **Dependencies**: 1.2, 2.2

- [ ] 4.2 Extend `src/assistant/core/persona.py`:
  - Load `binding.yaml` if present
  - Synthesize from legacy `persona.yaml` `harnesses.*` keys if not
  - Run validator before returning the PersonaConfig
  - Attach resolved `BindingManifest` as `persona.binding`
  **Dependencies**: 4.1

## Phase 5 — Role requires_capabilities

- [ ] 5.1 Write `tests/core/test_role_requires_capabilities.py`:
  - Role with `requires_capabilities: [{capability: foo.bar}]`
    parses
  - Role with unknown capability key rejected
  - Validator integration: persona with role X but no provider for
    X's required capabilities is rejected
  **Dependencies**: 2.2

- [ ] 5.2 Extend `src/assistant/core/role.py` to parse
  `requires_capabilities`; thread through to validator at
  `PersonaRegistry.load` time.
  **Dependencies**: 5.1

## Phase 6 — CLI subcommand

- [ ] 6.1 Write `tests/cli/test_binding_subcommand.py`:
  - `assistant binding check -p personal` runs validator and exits 0
    on success
  - `assistant binding check -p personal` exits non-zero on failure
    with formatted error
  - `assistant binding show -p personal` prints resolved manifest
  - `assistant binding explain memory.semantic_search -p personal`
    names the providing implementation
  **Dependencies**: 4.2, 5.2

- [ ] 6.2 Implement `assistant binding` subcommand in
  `src/assistant/cli.py`.
  **Dependencies**: 6.1

## Phase 7 — Template + docs

- [ ] 7.1 Add `personas/_template/binding.yaml` showing the schema
  with annotated comments.

- [ ] 7.2 Add `personas/_template/schemas/binding.schema.json`
  generated from Pydantic for editor support.

- [ ] 7.3 Document the binding manifest in
  `docs/architecture/binding-manifest.md` (operational reference,
  complementary to `primitives-and-providers.md`'s architectural
  framing).

- [ ] 7.4 Update `docs/architecture/primitives-and-providers.md` to
  cross-reference the now-real binding manifest; update
  `docs/architecture/interface-stability.md` to mark
  `BindingManifest` interface as Provisional (real, one provider,
  has conformance suite).
