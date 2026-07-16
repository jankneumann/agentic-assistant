"""Tests for the model-provider capability (P19 model-provider-routing).

Covers the model-provider spec: ModelRef validation (closed dialect +
tag vocabularies, wire-identifier refinement), persona registry
parsing/validation (entries + consumer bindings), binding-first
resolution with tag-filtered ordered fallback chains, the synthesized
default registry (registry-only per owner review verdict #3) and
HostProvidedModelProvider, resolver slot #6 wiring, and the
CredentialProvider seam.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from assistant.core.capabilities.credentials import (
    CredentialProvider,
    EnvCredentialProvider,
)
from assistant.core.capabilities.models import (
    CAPABILITY_TAGS,
    DEFAULT_HARNESS_MODELS,
    HOST_PROVIDED_MODEL_NAME,
    HostProvidedModelProvider,
    ModelProvider,
    ModelRef,
    ModelRegistry,
    ModelRegistryError,
    ModelRequest,
    ModelResolutionError,
    RegistryModelProvider,
    compute_cost,
    default_model_registry,
    parse_model_registry,
)

# ── ModelRef ─────────────────────────────────────────────────────────


def test_modelref_captures_metered_cloud_model() -> None:
    ref = ModelRef(
        name="sonnet",
        dialect="anthropic",
        credential_ref="ANTHROPIC_API_KEY",
        tags=["coding", "long-context"],
        pricing={"prompt": "0.000003", "completion": "0.000015"},
        context_length=200_000,
        modalities={"input": ["text", "image"], "output": ["text"]},
    )
    assert ref.name == "sonnet"
    assert ref.dialect == "anthropic"
    assert ref.credential_ref == "ANTHROPIC_API_KEY"
    assert ref.tags == ["coding", "long-context"]
    assert ref.pricing["prompt"] == "0.000003"
    assert ref.context_length == 200_000
    # credential_ref is a lookup key, never a resolved secret value
    assert ref.credential_ref == "ANTHROPIC_API_KEY"


def test_modelref_captures_local_endpoint_without_hosted_identifier() -> None:
    ref = ModelRef(
        name="local",
        dialect="openai-compatible",
        endpoint="http://gx10.local:8000/v1",
    )
    assert ref.endpoint == "http://gx10.local:8000/v1"
    assert ref.credential_ref == ""


def test_modelref_rejects_unknown_dialect() -> None:
    with pytest.raises(ValueError, match="litellm"):
        ModelRef(name="x", dialect="litellm")


def test_modelref_rejects_out_of_vocabulary_tags() -> None:
    with pytest.raises(ValueError) as exc:
        ModelRef(name="x", dialect="anthropic", tags=["fast", "sparkly"])
    # error must name the allowed vocabulary
    for tag in sorted(CAPABILITY_TAGS):
        assert tag in str(exc.value)
    assert "sparkly" in str(exc.value)


def test_modelref_model_id_defaults_to_name() -> None:
    ref = ModelRef(name="sonnet", dialect="anthropic")
    assert ref.model_id == "sonnet"


def test_modelrequest_consumer_defaults_to_default_binding() -> None:
    # Open consumer vocabulary (verdict #3): harness names today,
    # embeddings/memory later — no closed-set validation.
    assert ModelRequest().consumer == "default"
    assert ModelRequest(consumer="embeddings").consumer == "embeddings"


# ── Registry parsing + validation ────────────────────────────────────


def _entries_raw() -> dict:
    return {
        "sonnet": {
            "dialect": "anthropic",
            "id": "claude-sonnet-4-20250514",
            "credential_ref": "ANTHROPIC_API_KEY",
            "tags": ["coding", "long-context"],
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "context_length": 200000,
            "fallbacks": ["local-fast"],
        },
        "local-fast": {
            "dialect": "openai-compatible",
            "id": "llama-3.1-8b-instruct",
            "endpoint": "http://gx10.local:8000/v1",
            "tags": ["fast", "cheap", "local-only", "private-data-ok"],
        },
    }


def _registry_raw(bindings: dict | None = None) -> dict:
    raw: dict = {"entries": _entries_raw()}
    if bindings is not None:
        raw["bindings"] = bindings
    return raw


def test_parse_registry_resolves_entries_to_modelrefs() -> None:
    registry = parse_model_registry(_registry_raw())
    ref = registry.entries["local-fast"]
    assert ref.name == "local-fast"
    assert ref.model_id == "llama-3.1-8b-instruct"
    assert ref.dialect == "openai-compatible"
    assert ref.endpoint == "http://gx10.local:8000/v1"
    assert registry.fallbacks["sonnet"] == ["local-fast"]


def test_parse_registry_rejects_unknown_dialect() -> None:
    raw = {"entries": {"bad": {"dialect": "litellm"}}}
    with pytest.raises(ModelRegistryError, match="litellm"):
        parse_model_registry(raw)


def test_parse_registry_rejects_unknown_tag_naming_vocabulary() -> None:
    raw = {"entries": {"bad": {"dialect": "anthropic", "tags": ["fast", "sparkly"]}}}
    with pytest.raises(ModelRegistryError, match="sparkly"):
        parse_model_registry(raw)


def test_parse_registry_dangling_fallback_names_both_entries() -> None:
    raw = {
        "entries": {
            "primary": {"dialect": "anthropic", "fallbacks": ["missing-entry"]}
        }
    }
    with pytest.raises(ModelRegistryError) as exc:
        parse_model_registry(raw)
    assert "primary" in str(exc.value)
    assert "missing-entry" in str(exc.value)


def test_parse_registry_rejects_pre_verdict3_flat_shape() -> None:
    """Old flat entry maps must fail with a pointer to the new shape."""
    with pytest.raises(ModelRegistryError, match="entries"):
        parse_model_registry({"sonnet": {"dialect": "anthropic"}})


def test_parse_registry_parses_bindings() -> None:
    registry = parse_model_registry(
        _registry_raw({"default": "sonnet", "ms_agent_framework": "local-fast"})
    )
    assert registry.bindings == {
        "default": "sonnet",
        "ms_agent_framework": "local-fast",
    }


def test_parse_registry_unknown_binding_target_fails_load() -> None:
    with pytest.raises(ModelRegistryError) as exc:
        parse_model_registry(_registry_raw({"deep_agents": "missing-entry"}))
    assert "deep_agents" in str(exc.value)
    assert "missing-entry" in str(exc.value)


def test_parse_registry_empty_is_falsy() -> None:
    assert not parse_model_registry({})
    assert not parse_model_registry(None)
    assert parse_model_registry(_registry_raw())


def test_persona_load_fails_on_invalid_registry(tmp_path: Path) -> None:
    from assistant.core.persona import PersonaRegistry

    persona_dir = tmp_path / "fixture"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        "name: fixture\n"
        "models:\n"
        "  entries:\n"
        "    bad:\n"
        "      dialect: litellm\n"
    )
    registry = PersonaRegistry(tmp_path)
    with pytest.raises(ValueError, match="litellm"):
        registry.load("fixture")


def test_persona_load_parses_valid_registry(tmp_path: Path) -> None:
    from assistant.core.persona import PersonaRegistry

    persona_dir = tmp_path / "fixture"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        "name: fixture\n"
        "models:\n"
        "  entries:\n"
        "    local-fast:\n"
        "      dialect: openai-compatible\n"
        "      id: llama-3.1-8b-instruct\n"
        "      endpoint: http://gx10.local:8000/v1\n"
        "      tags: [fast, local-only]\n"
        "  bindings:\n"
        "    default: local-fast\n"
    )
    cfg = PersonaRegistry(tmp_path).load("fixture")
    assert cfg.models.entries["local-fast"].model_id == "llama-3.1-8b-instruct"
    assert cfg.models.bindings == {"default": "local-fast"}


# ── RegistryModelProvider — unbound tag resolution ───────────────────


def _provider(bindings: dict | None = None) -> RegistryModelProvider:
    return RegistryModelProvider(parse_model_registry(_registry_raw(bindings)))


def test_registry_provider_satisfies_protocol() -> None:
    assert isinstance(_provider(), ModelProvider)


def test_resolution_returns_ordered_fallback_chain() -> None:
    chain = _provider().resolve(ModelRequest(required_tags=["coding"]))
    # spec scenario: primary first, declared fallback after — but the
    # fallback lacks the required tag here, so it is excluded.
    assert [r.name for r in chain] == ["sonnet"]

    chain = _provider().resolve(ModelRequest())
    names = [r.name for r in chain]
    assert names[0] == "sonnet"
    assert "local-fast" in names
    assert names.index("sonnet") < names.index("local-fast")


def test_fallback_declared_entry_follows_primary() -> None:
    raw = {
        "entries": {
            "primary": {
                "dialect": "anthropic",
                "tags": ["coding"],
                "fallbacks": ["secondary"],
            },
            "secondary": {"dialect": "openai-compatible", "tags": ["coding"]},
        }
    }
    chain = RegistryModelProvider(parse_model_registry(raw)).resolve(
        ModelRequest(required_tags=["coding"])
    )
    assert [r.name for r in chain] == ["primary", "secondary"]


def test_required_tag_filters_entire_chain() -> None:
    """Privacy scenario: every ref in the chain carries private-data-ok."""
    chain = _provider().resolve(
        ModelRequest(required_tags=["private-data-ok"])
    )
    assert chain, "chain must be non-empty"
    for ref in chain:
        assert "private-data-ok" in ref.tags


def test_unsatisfiable_requirements_raise_naming_tag() -> None:
    with pytest.raises(ModelResolutionError, match="vision"):
        _provider().resolve(ModelRequest(required_tags=["vision"]))


def test_preferred_tags_bias_ordering() -> None:
    chain = _provider().resolve(ModelRequest(preferred_tags=["cheap"]))
    assert chain[0].name == "local-fast"


def test_list_models_returns_declared_entries() -> None:
    names = [r.name for r in _provider().list_models()]
    assert names == ["sonnet", "local-fast"]


# ── RegistryModelProvider — consumer bindings ────────────────────────


def test_consumer_binding_selects_bound_entry() -> None:
    provider = _provider(
        {"default": "sonnet", "ms_agent_framework": "local-fast"}
    )
    chain = provider.resolve(ModelRequest(consumer="ms_agent_framework"))
    assert [r.name for r in chain] == ["local-fast"]


def test_unbound_consumer_falls_back_to_default_binding() -> None:
    provider = _provider({"default": "sonnet"})
    chain = provider.resolve(ModelRequest(consumer="deep_agents"))
    # bound entry first, then its declared fallbacks
    assert [r.name for r in chain] == ["sonnet", "local-fast"]


def test_binding_chain_filtered_by_required_tags() -> None:
    """Privacy scenario on the bound path: a fallback that drops a
    required tag never enters the chain."""
    provider = _provider({"default": "sonnet"})
    chain = provider.resolve(
        ModelRequest(consumer="deep_agents", required_tags=["coding"])
    )
    # local-fast lacks `coding`, so only the bound entry survives
    assert [r.name for r in chain] == ["sonnet"]


def test_binding_unsatisfiable_required_tags_raise() -> None:
    provider = _provider({"default": "local-fast"})
    with pytest.raises(ModelResolutionError, match="coding"):
        provider.resolve(
            ModelRequest(consumer="deep_agents", required_tags=["coding"])
        )


def test_no_binding_falls_back_to_tag_resolution() -> None:
    chain = _provider().resolve(ModelRequest(consumer="deep_agents"))
    assert [r.name for r in chain] == ["sonnet", "local-fast"]


# ── Synthesized default registry (verdict #3 — registry-only) ────────


def test_default_registry_binds_every_known_harness() -> None:
    registry = default_model_registry()
    assert set(registry.bindings) == set(DEFAULT_HARNESS_MODELS)
    for consumer, model in DEFAULT_HARNESS_MODELS.items():
        assert registry.bindings[consumer] == model
        assert registry.entries[model].model_id == model


@pytest.mark.parametrize(
    ("model", "dialect"),
    [
        ("anthropic:claude-sonnet-4-20250514", "anthropic"),
        ("openai:gpt-4o", "openai-compatible"),
        ("google_genai:gemini-2.0-flash", "gemini"),
        ("google_vertexai:gemini-2.0-pro", "vertex"),
        ("bedrock_converse:claude-3", "bedrock"),
        ("ollama:llama3", "openai-compatible"),
    ],
)
def test_default_registry_infers_dialect_from_prefix(
    model: str, dialect: str
) -> None:
    registry = default_model_registry({"deep_agents": model})
    assert registry.entries[model].dialect == dialect


def test_default_registry_resolves_per_harness_consumer() -> None:
    provider = RegistryModelProvider(default_model_registry())
    assert isinstance(provider, ModelProvider)
    deep = provider.resolve(ModelRequest(consumer="deep_agents"))
    msaf = provider.resolve(ModelRequest(consumer="ms_agent_framework"))
    assert [r.model_id for r in deep] == [DEFAULT_HARNESS_MODELS["deep_agents"]]
    assert [r.model_id for r in msaf] == [
        DEFAULT_HARNESS_MODELS["ms_agent_framework"]
    ]


def test_default_registry_entries_carry_no_tags_so_tagged_requests_raise() -> None:
    """A synthesized default carries no capability tags — a tagged
    request must raise rather than silently return a non-matching
    model."""
    provider = RegistryModelProvider(default_model_registry())
    with pytest.raises(ModelResolutionError, match="coding"):
        provider.resolve(
            ModelRequest(consumer="deep_agents", required_tags=["coding"])
        )


# ── HostProvidedModelProvider ────────────────────────────────────────


def test_host_provider_defers_to_host() -> None:
    provider = HostProvidedModelProvider()
    assert isinstance(provider, ModelProvider)
    chain = provider.resolve(ModelRequest())
    assert len(chain) == 1
    assert chain[0].name == HOST_PROVIDED_MODEL_NAME
    assert chain[0].endpoint == ""  # never names a concrete endpoint
    assert chain[0].modalities.get("host_provided") is True


# ── Resolver slot #6 wiring ──────────────────────────────────────────


def _resolver_persona(models: ModelRegistry | None = None) -> MagicMock:
    persona = MagicMock()
    persona.harnesses = {"deep_agents": {"enabled": True}}
    persona.memory_content = ""
    persona.extensions = []
    persona.tool_sources = {}
    persona.database_url = ""
    persona.models = models if models is not None else ModelRegistry()
    return persona


def test_resolver_sdk_synthesizes_default_registry_without_models() -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    cs = CapabilityResolver().resolve(_resolver_persona(), "sdk", MagicMock())
    assert isinstance(cs.models, RegistryModelProvider)
    assert isinstance(cs.models, ModelProvider)
    chain = cs.models.resolve(ModelRequest(consumer="deep_agents"))
    assert [r.model_id for r in chain] == [
        DEFAULT_HARNESS_MODELS["deep_agents"]
    ]


def test_resolver_sdk_uses_declared_registry_when_present() -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    persona = _resolver_persona(parse_model_registry(_registry_raw()))
    cs = CapabilityResolver().resolve(persona, "sdk", MagicMock())
    assert isinstance(cs.models, RegistryModelProvider)
    assert [r.name for r in cs.models.list_models()] == ["sonnet", "local-fast"]


def test_resolver_host_gets_host_provided_model_provider() -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    cs = CapabilityResolver().resolve(_resolver_persona(), "host", MagicMock())
    assert isinstance(cs.models, HostProvidedModelProvider)


def test_resolver_model_factory_override_wins() -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    custom = HostProvidedModelProvider()
    resolver = CapabilityResolver(model_factory=lambda: custom)
    cs = resolver.resolve(_resolver_persona(), "sdk", MagicMock())
    assert cs.models is custom


# ── CredentialProvider seam ──────────────────────────────────────────


def test_env_provider_satisfies_protocol() -> None:
    assert isinstance(EnvCredentialProvider(), CredentialProvider)


def test_env_provider_resolves_present_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_TOKEN", "abc123")
    assert EnvCredentialProvider().get_credential("GMAIL_TOKEN") == "abc123"


def test_env_provider_missing_or_empty_ref_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UNSET_VAR", raising=False)
    provider = EnvCredentialProvider()
    assert provider.get_credential("UNSET_VAR") == ""
    assert provider.get_credential("") == ""


# ── Cost computation ─────────────────────────────────────────────────


def test_compute_cost_from_openrouter_shaped_pricing() -> None:
    pricing = {"prompt": "0.000003", "completion": "0.000015"}
    assert compute_cost(pricing, 1000, 100) == pytest.approx(0.0045)


def test_compute_cost_missing_pricing_returns_none() -> None:
    assert compute_cost({}, 1000, 100) is None
    assert compute_cost({"prompt": "not-a-number"}, 10, 10) is None
