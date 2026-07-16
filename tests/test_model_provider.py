"""Tests for the model-provider capability (P19 model-provider-routing).

Covers the model-provider spec: ModelRef validation (closed dialect +
tag vocabularies, wire-identifier refinement), persona registry
parsing/validation, tag-filtered resolution with ordered fallback
chains, the StaticModelProvider / HostProvidedModelProvider defaults,
resolver slot #6 wiring, and the CredentialProvider seam.
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
    HOST_PROVIDED_MODEL_NAME,
    HostProvidedModelProvider,
    ModelProvider,
    ModelRef,
    ModelRegistry,
    ModelRegistryError,
    ModelRequest,
    ModelResolutionError,
    RegistryModelProvider,
    StaticModelProvider,
    compute_cost,
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


def test_modelrequest_rejects_unknown_consumer() -> None:
    with pytest.raises(ValueError, match="consumer"):
        ModelRequest(consumer="batch")


# ── Registry parsing + validation ────────────────────────────────────


def _registry_raw() -> dict:
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


def test_parse_registry_resolves_entries_to_modelrefs() -> None:
    registry = parse_model_registry(_registry_raw())
    ref = registry.entries["local-fast"]
    assert ref.name == "local-fast"
    assert ref.model_id == "llama-3.1-8b-instruct"
    assert ref.dialect == "openai-compatible"
    assert ref.endpoint == "http://gx10.local:8000/v1"
    assert registry.fallbacks["sonnet"] == ["local-fast"]


def test_parse_registry_rejects_unknown_dialect() -> None:
    raw = {"bad": {"dialect": "litellm"}}
    with pytest.raises(ModelRegistryError, match="litellm"):
        parse_model_registry(raw)


def test_parse_registry_rejects_unknown_tag_naming_vocabulary() -> None:
    raw = {"bad": {"dialect": "anthropic", "tags": ["fast", "sparkly"]}}
    with pytest.raises(ModelRegistryError, match="sparkly"):
        parse_model_registry(raw)


def test_parse_registry_dangling_fallback_names_both_entries() -> None:
    raw = {"primary": {"dialect": "anthropic", "fallbacks": ["missing-entry"]}}
    with pytest.raises(ModelRegistryError) as exc:
        parse_model_registry(raw)
    assert "primary" in str(exc.value)
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
        "  bad:\n"
        "    dialect: litellm\n"
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
        "  local-fast:\n"
        "    dialect: openai-compatible\n"
        "    id: llama-3.1-8b-instruct\n"
        "    endpoint: http://gx10.local:8000/v1\n"
        "    tags: [fast, local-only]\n"
    )
    cfg = PersonaRegistry(tmp_path).load("fixture")
    assert cfg.models.entries["local-fast"].model_id == "llama-3.1-8b-instruct"


# ── RegistryModelProvider ────────────────────────────────────────────


def _provider() -> RegistryModelProvider:
    return RegistryModelProvider(parse_model_registry(_registry_raw()))


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
        "primary": {
            "dialect": "anthropic",
            "tags": ["coding"],
            "fallbacks": ["secondary"],
        },
        "secondary": {"dialect": "openai-compatible", "tags": ["coding"]},
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


# ── StaticModelProvider ──────────────────────────────────────────────


def _static_persona(model: str | None) -> MagicMock:
    persona = MagicMock()
    persona.harnesses = {
        "deep_agents": {"enabled": True, **({"model": model} if model else {})}
    }
    return persona


def test_static_provider_wraps_persona_config() -> None:
    provider = StaticModelProvider(
        _static_persona("anthropic:claude-sonnet-4-20250514"),
        harness_name="deep_agents",
    )
    chain = provider.resolve(ModelRequest())
    assert len(chain) == 1
    assert chain[0].dialect == "anthropic"
    assert chain[0].model_id == "anthropic:claude-sonnet-4-20250514"


def test_static_provider_satisfies_protocol() -> None:
    assert isinstance(
        StaticModelProvider(_static_persona("openai:gpt-4o")), ModelProvider
    )


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
def test_static_provider_infers_dialect_from_prefix(
    model: str, dialect: str
) -> None:
    provider = StaticModelProvider(
        _static_persona(model), harness_name="deep_agents"
    )
    assert provider.resolve(ModelRequest())[0].dialect == dialect


def test_static_provider_falls_back_to_default_model() -> None:
    provider = StaticModelProvider(
        _static_persona(None),
        harness_name="deep_agents",
        default_model="anthropic:claude-sonnet-4-20250514",
    )
    assert (
        provider.resolve(ModelRequest())[0].model_id
        == "anthropic:claude-sonnet-4-20250514"
    )


def test_static_provider_raises_without_model_or_default() -> None:
    with pytest.raises(ModelResolutionError):
        StaticModelProvider(
            _static_persona(None), harness_name="deep_agents"
        ).resolve(ModelRequest())


def test_static_provider_raises_for_required_tags() -> None:
    provider = StaticModelProvider(
        _static_persona("openai:gpt-4o"), harness_name="deep_agents"
    )
    with pytest.raises(ModelResolutionError, match="coding"):
        provider.resolve(ModelRequest(required_tags=["coding"]))


def test_for_harness_rebinds_config_entry() -> None:
    persona = MagicMock()
    persona.harnesses = {
        "deep_agents": {"model": "anthropic:sonnet"},
        "ms_agent_framework": {"model": "openai:gpt-4o"},
    }
    provider = StaticModelProvider(persona).for_harness("ms_agent_framework")
    assert provider.resolve(ModelRequest())[0].model_id == "openai:gpt-4o"


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


def test_resolver_sdk_defaults_to_static_provider() -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    cs = CapabilityResolver().resolve(_resolver_persona(), "sdk", MagicMock())
    assert isinstance(cs.models, StaticModelProvider)
    assert isinstance(cs.models, ModelProvider)


def test_resolver_sdk_uses_registry_provider_when_declared() -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    persona = _resolver_persona(parse_model_registry(_registry_raw()))
    cs = CapabilityResolver().resolve(persona, "sdk", MagicMock())
    assert isinstance(cs.models, RegistryModelProvider)


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
