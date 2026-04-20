# Tasks — capability-protocols

Tasks are ordered TDD-style within each phase: test tasks first,
implementation tasks depend on their corresponding tests. Phases are
ordered so each builds on a compileable/importable tree from the prior
phase.

## Phase 1 — Capability types and protocols

- [x] 1.1 Write `tests/test_capabilities.py` encoding the following
  scenarios from capability protocol specs:
  - `ActionRequest` captures action context
  - `ActionDecision` defaults
  - `RiskLevel` ordering
  - `ExecutionContext` captures sandbox state
  - `MemoryConfig` captures backend selection
  - `MemoryScoping` default scoping is per-persona only
  - `CapabilitySet` holds all five capabilities
  **Spec scenarios**: guardrail-provider (ActionRequest, ActionDecision,
  RiskLevel), sandbox-provider (ExecutionContext), memory-policy
  (MemoryConfig, MemoryScoping), capability-resolver (CapabilitySet).
  **Dependencies**: none

- [x] 1.2 Implement `src/assistant/core/capabilities/__init__.py` and
  type modules:
  - `types.py`: `ActionRequest`, `ActionDecision`, `RiskLevel`,
    `ExecutionContext`, `SandboxConfig`, `MemoryConfig`,
    `MemoryScoping`, `CapabilitySet`
  **Design decisions**: D5 (CapabilitySet is a plain dataclass)
  **Dependencies**: 1.1

- [x] 1.3 Write `tests/test_guardrail_protocol.py` encoding:
  - Stub implementation satisfies Protocol
  - Non-conforming class rejected
  - Stub allows all actions
  - Stub allows all delegations
  - Stub declares low risk
  **Spec scenarios**: all 5 scenarios from guardrail-provider spec.
  **Dependencies**: 1.2

- [x] 1.4 Implement `src/assistant/core/capabilities/guardrails.py`:
  `GuardrailProvider` Protocol and `AllowAllGuardrails` stub.
  **Design decisions**: D2 (genuinely new protocol), D7 (stub defaults
  to allow_all)
  **Dependencies**: 1.3

- [x] 1.5 Write `tests/test_sandbox_protocol.py` encoding:
  - Stub implementation satisfies Protocol
  - Stub returns current directory
  - Stub cleanup is safe to call
  **Spec scenarios**: all 3 scenarios from sandbox-provider spec.
  **Dependencies**: 1.2

- [x] 1.6 Implement `src/assistant/core/capabilities/sandbox.py`:
  `SandboxProvider` Protocol and `PassthroughSandbox` stub.
  **Design decisions**: D2 (genuinely new protocol)
  **Dependencies**: 1.5

- [x] 1.7 Write `tests/test_memory_policy.py` encoding:
  - Stub implementation satisfies Protocol
  - Reads memory_files from persona config
  - Defaults to AGENTS.md
  - export_memory_context returns persona memory content
  **Spec scenarios**: all 4 scenarios from memory-policy spec
  (FileMemoryPolicy).
  **Dependencies**: 1.2
  
- [x] 1.8 Implement `src/assistant/core/capabilities/memory.py`:
  `MemoryPolicy` Protocol and `FileMemoryPolicy` implementation.
  **Design decisions**: D1 (policy over SDK-native types), D6
  (formalizes existing behavior)
  **Dependencies**: 1.7

- [x] 1.9 Write `tests/test_tool_policy.py` encoding:
  - Stub implementation satisfies Protocol
  - All extension tools when preferred_tools is empty
  - Filtered by preferred_tools
  - Extension authorization delegates to load_extensions
  - Manifest includes extension metadata
  - Manifest includes tool_sources
  **Spec scenarios**: all 6 scenarios from tool-policy spec.
  **Dependencies**: 1.2

- [x] 1.10 Implement `src/assistant/core/capabilities/tools.py`:
  `ToolPolicy` Protocol and `DefaultToolPolicy` implementation.
  **Design decisions**: D1 (policy over SDK-native types)
  **Dependencies**: 1.9

## Phase 2 — Capability resolver

- [x] 2.1 Write `tests/test_capability_resolver.py` encoding:
  - SDK harness resolves concrete providers
  - Host harness marks host-provided capabilities
  - Custom guardrail provider injected
  - Unset overrides use defaults
  **Spec scenarios**: all 4 scenarios from capability-resolver spec.
  **Dependencies**: 1.4, 1.6, 1.8, 1.10

- [x] 2.2 Implement `src/assistant/core/capabilities/resolver.py`:
  `CapabilityResolver` with `resolve()` method.
  **Design decisions**: D3 (two-tier, not three-tier)
  **Dependencies**: 2.1

## Phase 3 — Harness restructure (TDD)

- [x] 3.1 Write `tests/test_harness_restructure.py` encoding:
  - harness_type identifies adapter category (sdk)
  - SdkHarnessAdapter.create_agent receives capabilities
  - SdkHarnessAdapter.invoke signature unchanged
  - Harness name and type (claude_code)
  - export_context includes persona and role prompts
  - export_context returns string artifacts
  - export_tool_manifest returns tool descriptions
  - Factory creates SDK harness
  - Factory creates host harness
  - Unknown harness name raises
  **Spec scenarios**: 10 scenarios from harness-adapter spec delta.
  **Dependencies**: 2.2

- [x] 3.2 Restructure `src/assistant/harnesses/`:
  - Create `src/assistant/harnesses/sdk/__init__.py`
  - Create `src/assistant/harnesses/host/__init__.py`
  - Move `deep_agents.py` → `sdk/deep_agents.py`
  - Move `ms_agent_fw.py` → `sdk/ms_agent_fw.py`
  - Refactor `base.py`: add `harness_type` property, create
    `SdkHarnessAdapter` and `HostHarnessAdapter` ABCs
  - Add re-exports in `harnesses/__init__.py` for backward compat
  **Design decisions**: D8 (directory restructure), D3 (two-tier)
  **Dependencies**: 3.1

- [x] 3.3 Refactor `DeepAgentsHarness` to extend `SdkHarnessAdapter`
  and accept `CapabilitySet`:
  - `create_agent(capabilities)` uses `capabilities.memory.resolve()`
    instead of reading `memory_files` directly
  - `create_agent(capabilities)` uses
    `capabilities.tools.authorized_tools()` instead of receiving tools
    as a parameter
  **Design decisions**: D1 (policy over SDK-native types)
  **Dependencies**: 3.2

- [x] 3.4 Implement `src/assistant/harnesses/host/claude_code.py`:
  `ClaudeCodeHarness` with `export_context()`,
  `export_guardrail_declarations()`, `export_tool_manifest()`.
  **Design decisions**: D4 (exports generated artifacts)
  **Dependencies**: 3.2

- [x] 3.5 Update `src/assistant/harnesses/factory.py`: register both
  SDK and host harnesses, update validation for two-tier routing.
  **Dependencies**: 3.3, 3.4

## Phase 4 — Delegation guardrail integration

- [x] 4.1 Write additional tests in `tests/test_delegation.py` encoding:
  - Guardrail denies delegation
  - Guardrail allows delegation
  - Role ACL checked before guardrail
  - Default guardrails allow everything
  - Custom guardrails injected
  **Spec scenarios**: all 5 scenarios from delegation-spawner spec delta.
  **Dependencies**: 3.5

- [x] 4.2 Update `src/assistant/delegation/spawner.py`:
  - Add optional `guardrails: GuardrailProvider` parameter to
    `__init__()`, defaulting to `AllowAllGuardrails()`
  - Call `guardrails.check_delegation()` after role ACL check, before
    spawning
  - Raise `PermissionError` on denied delegations
  **Dependencies**: 4.1

## Phase 5 — CLI export mode

- [x] 5.1 Write tests in `tests/test_cli.py` encoding:
  - Export generates context artifacts
  - Export requires persona
  - Export rejects SDK harness names
  - Bare invocation defaults to run
  - Explicit run subcommand
  **Spec scenarios**: all 5 scenarios from cli-interface spec delta.
  **Dependencies**: 3.5

- [x] 5.2 Refactor `src/assistant/cli.py`:
  - Convert to `click.Group` with `run` (default) and `export`
    subcommands
  - `run` preserves existing REPL behavior
  - `export` creates `HostHarnessAdapter`, calls `export_context()`,
    prints artifacts
  **Design decisions**: D9 (export is a subcommand)
  **Dependencies**: 5.1

## Phase 6 — Extension registry integration

- [x] 6.1 Write tests in `tests/test_extensions.py` encoding:
  - Extensions accessible via ToolPolicy
  **Spec scenarios**: extension-registry spec delta scenario.
  **Dependencies**: 3.5

- [x] 6.2 Verify `DefaultToolPolicy.authorized_extensions()` correctly
  delegates to `PersonaRegistry.load_extensions()`. No code changes
  expected if 1.10 implementation is correct — this task validates the
  integration seam.
  **Dependencies**: 6.1

## Phase 7 — Update existing tests and validation

- [x] 7.1 Update `tests/test_harnesses.py` for new import paths and
  `SdkHarnessAdapter` base class. All existing scenarios MUST continue
  to pass.
  **Dependencies**: 3.5

- [x] 7.2 Update `tests/test_cli.py` existing tests for `click.Group`
  structure. All existing scenarios MUST continue to pass.
  **Dependencies**: 5.2

- [x] 7.3 Run `uv run ruff check .` — zero errors.
  **Dependencies**: 7.1, 7.2

- [x] 7.4 Run `uv run pytest` — all tests pass.
  **Dependencies**: 7.3

- [x] 7.5 `openspec validate capability-protocols --strict` passes.
  **Dependencies**: 7.4
