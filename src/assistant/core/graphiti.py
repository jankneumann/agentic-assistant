"""Graphiti client factory with FalkorDB driver — per-persona caching.

P20 local-inference-node: when the persona's ``models:`` registry
declares an EXPLICIT ``embeddings`` consumer binding, the factory
resolves it (health-aware) and constructs the ``Graphiti`` client with
a :class:`RegistryEmbedder` — a graphiti-core ``EmbedderClient``
adapter over the P19 raw ``OpenAICompatibleClient`` — so semantic
memory search embeds on the local node. No binding → the default
graphiti-core embedder, byte-for-byte as before. A binding that is
declared but cannot be honored disables Graphiti for the persona
(warning + Postgres-only degradation) rather than silently embedding
through the default cloud path.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from graphiti_core import Graphiti
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig

from assistant.core.capabilities.credentials import EnvCredentialProvider
from assistant.core.capabilities.guardrails import (
    GuardrailConfig,
    GuardrailProvider,
    PolicyGuardrails,
)
from assistant.core.capabilities.model_bindings import OpenAICompatibleClient
from assistant.core.capabilities.models import (
    ModelRegistry,
    ModelRequest,
    ModelResolutionError,
    RegistryModelProvider,
)

logger = logging.getLogger(__name__)

#: Registry ``bindings:`` key that activates local-embedding wiring.
#: Explicit only — the reserved ``default`` binding does NOT spill
#: into embeddings (it almost always names a chat model).
EMBEDDINGS_CONSUMER = "embeddings"

_graphiti_cache: dict[str, Any] = {}


class EmbeddingsBindingError(RuntimeError):
    """A declared ``embeddings`` binding cannot be honored."""


class RegistryEmbedder(EmbedderClient):
    """graphiti-core embedder backed by the raw OpenAI-compatible binding.

    Vectors are truncated to ``embedding_dim`` (default: graphiti's own
    ``EmbedderConfig`` default, env-tunable via ``EMBEDDING_DIM``) —
    matching ``OpenAIEmbedder`` behavior so index dimensions stay
    consistent. Credential resolution and the ``model_call`` budget
    hook ride on the wrapped :class:`OpenAICompatibleClient`.
    """

    def __init__(
        self,
        client: OpenAICompatibleClient,
        *,
        embedding_dim: int | None = None,
    ) -> None:
        self._client = client
        self._embedding_dim = (
            embedding_dim
            if embedding_dim is not None
            else EmbedderConfig().embedding_dim
        )

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> list[float]:
        if isinstance(input_data, str):
            payload: Any = input_data
        else:
            payload = list(input_data)
        result = await self._client.embeddings(payload)
        embedding: list[float] = result["data"][0]["embedding"]
        return embedding[: self._embedding_dim]

    async def create_batch(
        self, input_data_list: list[str]
    ) -> list[list[float]]:
        result = await self._client.embeddings(input_data_list)
        return [
            item["embedding"][: self._embedding_dim]
            for item in result["data"]
        ]


def _persona_guardrails(persona: Any) -> GuardrailProvider | None:
    """Persona guardrails for the embedding budget hook.

    Mirrors ``CapabilityResolver._resolve_guardrails`` (P13): a
    non-empty ``guardrails:`` section selects :class:`PolicyGuardrails`;
    anything else means no gating (allow-all equivalent).
    """
    config = getattr(persona, "guardrails", None)
    if isinstance(config, GuardrailConfig) and config:
        return PolicyGuardrails(config, persona=getattr(persona, "name", ""))
    return None


def _create_registry_embedder(persona: Any) -> RegistryEmbedder | None:
    """Resolve the persona's explicit ``embeddings`` binding, if any.

    Returns ``None`` when no explicit binding is declared (default
    embedder path). Raises :class:`EmbeddingsBindingError` or
    :class:`ModelResolutionError` when a declared binding cannot be
    honored — the caller disables Graphiti rather than falling back to
    the default cloud embedder.
    """
    registry = getattr(persona, "models", None)
    if not isinstance(registry, ModelRegistry) or not registry:
        return None
    if EMBEDDINGS_CONSUMER not in registry.bindings:
        return None

    provider = RegistryModelProvider(registry)
    refs = provider.resolve(ModelRequest(consumer=EMBEDDINGS_CONSUMER))
    ref = next(
        (
            r
            for r in refs
            if r.dialect == "openai-compatible" and r.endpoint
        ),
        None,
    )
    if ref is None:
        raise EmbeddingsBindingError(
            f"the '{EMBEDDINGS_CONSUMER}' binding resolved to "
            f"{[r.name for r in refs]}, none of which is an "
            f"'openai-compatible' entry with an endpoint — the raw "
            f"embeddings binding needs both."
        )

    credentials = (
        getattr(persona, "credentials", None) or EnvCredentialProvider()
    )
    client = OpenAICompatibleClient(
        ref,
        credentials=credentials,
        guardrails=_persona_guardrails(persona),
        persona=getattr(persona, "name", ""),
        role="memory",
    )
    logger.info(
        "Persona '%s': Graphiti embeddings via registry entry '%s' (%s)",
        getattr(persona, "name", ""),
        ref.name,
        ref.endpoint,
    )
    return RegistryEmbedder(client)


def create_graphiti_client(persona: Any) -> Any | None:
    graphiti_url = persona.graphiti_url
    if not graphiti_url:
        return None

    cache_key = f"{persona.name}:{graphiti_url}"
    if cache_key in _graphiti_cache:
        return _graphiti_cache[cache_key]

    # P20: an explicit `embeddings` binding selects the local embedder.
    # A declared-but-unhonorable binding disables Graphiti (memory
    # degrades to Postgres-only) — never a silent cloud fallback.
    try:
        embedder = _create_registry_embedder(persona)
    except (EmbeddingsBindingError, ModelResolutionError) as exc:
        logger.warning(
            "Persona '%s' declares an '%s' model binding that cannot be "
            "honored (%s); disabling Graphiti rather than falling back "
            "to the default cloud embedder.",
            persona.name,
            EMBEDDINGS_CONSUMER,
            exc,
        )
        return None

    graphiti_cfg = persona.raw.get("graphiti", {})

    # P13 security-hardening: graphiti connection secrets resolve
    # through the persona-scoped CredentialProvider (persona .env
    # first, process env fallback), matching persona load.
    credentials = getattr(persona, "credentials", None) or EnvCredentialProvider()

    def _cred(ref: Any) -> str:
        return credentials.get_credential(str(ref)) if ref else ""

    host = _cred(graphiti_cfg.get("host_env")) or "localhost"
    port_str = _cred(graphiti_cfg.get("port_env")) or "6379"
    port = int(port_str)
    password = _cred(graphiti_cfg.get("password_env")) or ""
    database = graphiti_cfg.get("database", f"{persona.name}_graph")

    driver = FalkorDriver(
        host=host,
        port=port,
        username="",
        password=password,
        database=database,
    )
    if embedder is not None:
        client = Graphiti(graph_driver=driver, embedder=embedder)
    else:
        client = Graphiti(graph_driver=driver)
    _graphiti_cache[cache_key] = client
    logger.info(
        "Created Graphiti client for persona '%s' at %s:%d/%s",
        persona.name, host, port, database,
    )
    return client


def _clear_graphiti_cache() -> None:
    _graphiti_cache.clear()
