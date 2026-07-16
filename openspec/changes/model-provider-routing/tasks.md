# model-provider-routing — Tasks

## 1. Core capability implementation

- [x] 1.1 `core/capabilities/credentials.py` — `CredentialProvider`
  protocol + `EnvCredentialProvider` (exact `_env()` semantics)
- [x] 1.2 `core/capabilities/models.py` — `ModelRef` (closed 5-dialect
  vocabulary, tag vocabulary, OpenRouter-mirrored metadata,
  `model_id` refinement), `ModelRequest`, `ModelProvider` protocol,
  `parse_model_registry` validation, `RegistryModelProvider`,
  `StaticModelProvider`, `HostProvidedModelProvider`, `compute_cost`
- [x] 1.3 `core/capabilities/model_bindings.py` — budget hook
  (`check_model_call`), LangChain binding, MSAF binding, raw
  OpenAI-compatible client (chat + embeddings, httpx)
- [x] 1.4 Slot #6 wiring — `CapabilitySet.models`,
  `CapabilityResolver(model_factory=...)`, host/sdk branch selection
- [x] 1.5 `core/persona.py` — parse + validate `models:` at load;
  `PersonaConfig.models` field

## 2. Harness integration

- [x] 2.1 `DeepAgentsHarness` — `_resolve_model_provider` /
  `_build_model` fallback iteration through `bind_langchain`;
  `model_provider` / `credential_provider` / `guardrail_provider`
  injection kwargs; `_active_model_ref` stash
- [x] 2.2 `MSAgentFrameworkHarness` — openai branch through
  `bind_msaf_chat_client`; azure branch unchanged (install-error
  degrade); injection kwargs + sub-agent passthrough
- [x] 2.3 `telemetry/decorators.py` — cost attribution metadata
  (`model_ref`, `model_dialect`, `cost_usd`) merged into
  `trace_llm_call` spans via the `_active_model_ref` pattern

## 3. Config + docs

- [x] 3.1 `personas/_template/persona.yaml` — commented `models:`
  registry example documenting the schema
- [x] 3.2 CLAUDE.md "What's Not Yet Wired" — P19 status note
- [x] 3.3 `openspec/roadmap.md` — P19 row → in-progress

## 4. Tests

- [x] 4.1 `tests/test_model_provider.py` — ModelRef validation,
  registry parsing + persona-load failures, tag-filtered resolution +
  fallback ordering, StaticModelProvider, HostProvidedModelProvider,
  resolver slot wiring, EnvCredentialProvider
- [x] 4.2 `tests/test_model_bindings.py` — LangChain dialect mapping,
  budget-hook denial paths, MSAF binding kwargs + dialect guard, raw
  client wire shape (httpx.MockTransport, no network)
- [x] 4.3 Harness integration tests — registry-backed create_agent,
  denial propagation, fallback-chain binding, cost metadata on spans;
  existing suites pass unchanged

## 5. Gates

- [x] 5.1 `uv run pytest tests/`
- [x] 5.2 `uv run ruff check src tests`
- [x] 5.3 `uv run mypy src tests`
- [x] 5.4 `openspec validate model-provider-routing --strict`

## 6. Review

- [ ] 6.1 Owner review + archive (left unarchived for review)
