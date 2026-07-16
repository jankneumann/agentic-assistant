"""ModelProvider seam — model-provider-routing (P19).

One model seam, not two (ADR-0005): the ``ModelProvider`` protocol
resolves capability requirements to harness-neutral ``ModelRef``
values; thin per-consumer bindings (``model_bindings.py``) adapt a
``ModelRef`` to each consumer's native client. Catalog metadata
mirrors the OpenRouter ``/models`` schema (pricing, context length,
modalities) so cloud entries sync verbatim and local entries are
hand-authored in the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

#: Closed wire-dialect vocabulary — the five converged wire protocols
#: (model-provider spec "ModelRef Type"). No new wire protocol is
#: invented; local backends (vLLM, Ollama, NIM) and OpenRouter are all
#: ``openai-compatible``.
DIALECTS: frozenset[str] = frozenset(
    {"openai-compatible", "anthropic", "gemini", "bedrock", "vertex"}
)

#: Shared capability-tag vocabulary (model-provider spec "Capability
#: Tag Vocabulary"). Shared data with agentic-coding-tools' cost-aware
#: routing (contracts and data, not code — ADR-0006); additions extend
#: the spec rather than forking per consumer.
CAPABILITY_TAGS: frozenset[str] = frozenset(
    {
        "fast",
        "cheap",
        "long-context",
        "coding",
        "vision",
        "local-only",
        "private-data-ok",
    }
)

#: Valid ``ModelRequest.consumer`` values.
CONSUMERS: frozenset[str] = frozenset({"chat", "embedding"})

#: Sentinel ``ModelRef.name`` returned by :class:`HostProvidedModelProvider`
#: — identifies the model slot as owned by the host seat rather than
#: naming a concrete endpoint.
HOST_PROVIDED_MODEL_NAME: str = "host-provided"

#: LangChain ``init_chat_model`` provider-prefix → wire dialect, used
#: by :class:`StaticModelProvider` to infer the dialect from the
#: persona's existing ``provider:model`` config strings.
_PREFIX_TO_DIALECT: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai-compatible",
    "google_genai": "gemini",
    "gemini": "gemini",
    "google_vertexai": "vertex",
    "vertex": "vertex",
    "bedrock": "bedrock",
    "bedrock_converse": "bedrock",
    # Ollama serves an OpenAI-compatible endpoint; the LangChain
    # binding preserves the original prefixed string verbatim so
    # ``init_chat_model`` still routes to the native connector.
    "ollama": "openai-compatible",
}


class ModelResolutionError(Exception):
    """No registry entry satisfies the request's required tags."""


class ModelRegistryError(ValueError):
    """A persona ``models:`` registry failed validation at load time."""


@dataclass
class ModelRef:
    """Harness-neutral description of one callable model.

    ``name`` is the registry entry name; ``model_id`` is the wire
    identifier sent to the provider (registry key ``id``, mirroring
    the OpenRouter ``/models`` schema — defaults to ``name`` when
    omitted). ``credential_ref`` is a :class:`CredentialProvider`
    lookup key — a ``ModelRef`` never carries a resolved secret value.
    """

    name: str
    dialect: str
    model_id: str = ""
    endpoint: str = ""
    credential_ref: str = ""
    tags: list[str] = field(default_factory=list)
    pricing: dict[str, Any] = field(default_factory=dict)
    context_length: int = 0
    modalities: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.dialect not in DIALECTS:
            raise ValueError(
                f"ModelRef {self.name!r}: unknown dialect {self.dialect!r}. "
                f"The dialect vocabulary is closed to the converged wire "
                f"protocols: {sorted(DIALECTS)}."
            )
        unknown_tags = [t for t in self.tags if t not in CAPABILITY_TAGS]
        if unknown_tags:
            raise ValueError(
                f"ModelRef {self.name!r}: unknown capability tags "
                f"{unknown_tags}. Allowed vocabulary: "
                f"{sorted(CAPABILITY_TAGS)}."
            )
        if not self.model_id:
            self.model_id = self.name


@dataclass
class ModelRequest:
    """Capability requirements for one model resolution.

    ``required_tags`` are hard constraints — every ``ModelRef`` in the
    resolved chain carries all of them. ``preferred_tags`` bias
    ordering only. ``consumer`` selects the binding family (``"chat"``
    or ``"embedding"``); it is carried and validated but not yet used
    for registry filtering (the embedding consumers land in P20/P21).
    """

    required_tags: list[str] = field(default_factory=list)
    preferred_tags: list[str] = field(default_factory=list)
    consumer: str = "chat"

    def __post_init__(self) -> None:
        if self.consumer not in CONSUMERS:
            raise ValueError(
                f"ModelRequest: unknown consumer {self.consumer!r}. "
                f"Allowed: {sorted(CONSUMERS)}."
            )


@runtime_checkable
class ModelProvider(Protocol):
    """Resolve capability requirements to an ordered ModelRef chain."""

    def resolve(self, request: ModelRequest) -> list[ModelRef]: ...
    def list_models(self) -> list[ModelRef]: ...


@dataclass
class ModelRegistry:
    """Parsed persona ``models:`` section.

    ``entries`` preserves declaration order (dict insertion order);
    ``fallbacks`` maps entry name → ordered fallback entry names.
    """

    entries: dict[str, ModelRef] = field(default_factory=dict)
    fallbacks: dict[str, list[str]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.entries)


def parse_model_registry(raw: dict[str, Any] | None) -> ModelRegistry:
    """Parse and validate a persona-level ``models:`` registry.

    Entries with unknown dialects, out-of-vocabulary tags, or fallback
    references to undeclared entries fail with a
    :class:`ModelRegistryError` naming the offending entry — persona
    load surfaces this as an actionable error.
    """
    raw = raw or {}
    entries: dict[str, ModelRef] = {}
    fallbacks: dict[str, list[str]] = {}

    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ModelRegistryError(
                f"models entry {name!r}: expected a mapping, got "
                f"{type(spec).__name__}."
            )
        try:
            entries[name] = ModelRef(
                name=name,
                dialect=spec.get("dialect", ""),
                model_id=str(spec.get("id", "") or ""),
                endpoint=spec.get("endpoint", "") or "",
                credential_ref=spec.get("credential_ref", "") or "",
                tags=list(spec.get("tags") or []),
                pricing=dict(spec.get("pricing") or {}),
                context_length=int(spec.get("context_length") or 0),
                modalities=dict(spec.get("modalities") or {}),
            )
        except ValueError as exc:
            raise ModelRegistryError(f"models entry {name!r}: {exc}") from exc
        fallbacks[name] = list(spec.get("fallbacks") or [])

    for name, chain in fallbacks.items():
        for fallback_name in chain:
            if fallback_name not in entries:
                raise ModelRegistryError(
                    f"models entry {name!r} declares fallback "
                    f"{fallback_name!r}, but no entry named "
                    f"{fallback_name!r} exists."
                )

    return ModelRegistry(entries=entries, fallbacks=fallbacks)


class RegistryModelProvider:
    """Registry-backed provider — tag-filtered, ordered fallback chains.

    Resolution: entries carrying every ``required_tags`` tag are
    candidates, ordered by preferred-tag match count (descending) then
    declaration order; each candidate is followed by its declared
    ``fallbacks`` (also filtered by ``required_tags`` — a fallback that
    drops a required capability such as ``private-data-ok`` never
    enters the chain). Duplicates keep their first position.
    """

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def list_models(self) -> list[ModelRef]:
        return list(self._registry.entries.values())

    def resolve(self, request: ModelRequest) -> list[ModelRef]:
        required = set(request.required_tags)
        preferred = set(request.preferred_tags)
        order = {name: i for i, name in enumerate(self._registry.entries)}

        candidates = [
            ref
            for ref in self._registry.entries.values()
            if required.issubset(ref.tags)
        ]
        if not candidates:
            raise ModelResolutionError(
                f"No models entry satisfies required_tags="
                f"{sorted(required)} (consumer={request.consumer!r}). "
                f"Declared entries: {list(self._registry.entries)}."
            )

        candidates.sort(
            key=lambda ref: (
                -len(preferred.intersection(ref.tags)),
                order[ref.name],
            )
        )

        chain: list[ModelRef] = []
        seen: set[str] = set()

        def _append(ref: ModelRef) -> None:
            if ref.name in seen:
                return
            seen.add(ref.name)
            chain.append(ref)

        for ref in candidates:
            _append(ref)
            for fallback_name in self._registry.fallbacks.get(ref.name, []):
                fallback = self._registry.entries[fallback_name]
                if required.issubset(fallback.tags):
                    _append(fallback)
        return chain


class StaticModelProvider:
    """Wraps the persona's per-harness ``model`` config string.

    Default SDK provider when the persona declares no ``models:``
    registry — keeps the capability slot total (model-provider spec
    "Default Model Providers"). The single-entry chain preserves the
    configured ``provider:model`` string verbatim in ``model_id`` so
    the LangChain binding reconstructs today's exact
    ``init_chat_model`` call; the dialect is inferred from the
    provider prefix.
    """

    def __init__(
        self,
        persona: Any,
        harness_name: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self._persona = persona
        self._harness_name = harness_name
        self._default_model = default_model

    def for_harness(
        self, harness_name: str, default_model: str | None = None
    ) -> StaticModelProvider:
        """Copy bound to one harness's config entry (and its default)."""
        return StaticModelProvider(
            self._persona,
            harness_name=harness_name,
            default_model=default_model or self._default_model,
        )

    def _configured_model(self) -> str:
        harnesses = getattr(self._persona, "harnesses", None) or {}
        if not isinstance(harnesses, dict):
            harnesses = {}
        if self._harness_name is not None:
            cfg = harnesses.get(self._harness_name) or {}
            model = cfg.get("model") if isinstance(cfg, dict) else None
            if isinstance(model, str) and model:
                return model
        else:
            for cfg in harnesses.values():
                if isinstance(cfg, dict):
                    model = cfg.get("model")
                    if isinstance(model, str) and model:
                        return model
        return self._default_model or ""

    def _ref(self) -> ModelRef | None:
        model = self._configured_model()
        if not model:
            return None
        prefix, _, _ = model.partition(":")
        dialect = _PREFIX_TO_DIALECT.get(prefix, "openai-compatible")
        return ModelRef(name=model, dialect=dialect, model_id=model)

    def list_models(self) -> list[ModelRef]:
        ref = self._ref()
        return [ref] if ref is not None else []

    def resolve(self, request: ModelRequest) -> list[ModelRef]:
        if request.required_tags:
            # A static config string carries no capability tags — a
            # tagged request is unsatisfiable and must raise rather
            # than silently return a non-matching model.
            raise ModelResolutionError(
                f"StaticModelProvider cannot satisfy required_tags="
                f"{sorted(request.required_tags)}: the persona declares "
                f"no models: registry (tags require registry entries)."
            )
        ref = self._ref()
        if ref is None:
            raise ModelResolutionError(
                "StaticModelProvider: persona declares no harness "
                "'model' string and no default was supplied."
            )
        return [ref]


class HostProvidedModelProvider:
    """Model selection is owned by the host seat (host harnesses).

    The resolved chain identifies the slot as host-provided (via
    :data:`HOST_PROVIDED_MODEL_NAME` and a ``host_provided`` modality
    marker) rather than naming a concrete endpoint.
    """

    def _ref(self) -> ModelRef:
        return ModelRef(
            name=HOST_PROVIDED_MODEL_NAME,
            dialect="openai-compatible",
            modalities={"host_provided": True},
        )

    def list_models(self) -> list[ModelRef]:
        return [self._ref()]

    def resolve(self, request: ModelRequest) -> list[ModelRef]:
        return [self._ref()]


def compute_cost(
    pricing: dict[str, Any], input_tokens: int, output_tokens: int
) -> float | None:
    """Cost from OpenRouter-shaped per-token rates; ``None`` when unknown.

    OpenRouter ``pricing`` carries per-token USD rates as strings
    (``{"prompt": "0.000003", "completion": "0.000015"}``). Missing or
    unparseable rates degrade to ``None`` — cost is never guessed
    (model-provider spec "Missing pricing degrades gracefully").
    """
    try:
        prompt_rate = float(pricing["prompt"])
        completion_rate = float(pricing["completion"])
    except (KeyError, TypeError, ValueError):
        return None
    return prompt_rate * input_tokens + completion_rate * output_tokens
