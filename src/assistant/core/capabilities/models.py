"""ModelProvider seam — model-provider-routing (P19).

One model seam, not two (ADR-0005): the ``ModelProvider`` protocol
resolves capability requirements to harness-neutral ``ModelRef``
values; thin per-consumer bindings (``model_bindings.py``) adapt a
``ModelRef`` to each consumer's native client. Catalog metadata
mirrors the OpenRouter ``/models`` schema (pricing, context length,
modalities) so cloud entries sync verbatim and local entries are
hand-authored in the same shape.

The persona ``models:`` registry is the ONLY model-selection
mechanism (P19 owner review verdict #3 — registry-only, the legacy
``harnesses.<name>.model`` strings are gone): ``entries:`` declare
the callable models, ``bindings:`` map consumer names (harness names
today; ``embeddings`` / ``memory`` later) to entries, and personas
without a ``models:`` section get a registry synthesized from
:data:`DEFAULT_HARNESS_MODELS` by :func:`default_model_registry`.
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

#: Binding key applied when a consumer has no explicit entry in the
#: registry's ``bindings:`` map (and default of ``ModelRequest.consumer``).
DEFAULT_BINDING: str = "default"

#: Per-harness default model strings (LangChain ``provider:model``
#: shape) used to synthesize a registry when the persona declares no
#: ``models:`` section — see :func:`default_model_registry`. Harness
#: classes reference this table for their span-default ``_DEFAULT_MODEL``
#: so core never imports harness modules.
DEFAULT_HARNESS_MODELS: dict[str, str] = {
    "deep_agents": "anthropic:claude-sonnet-4-20250514",
    "ms_agent_framework": "openai:gpt-4o",
}

#: Sentinel ``ModelRef.name`` returned by :class:`HostProvidedModelProvider`
#: — identifies the model slot as owned by the host seat rather than
#: naming a concrete endpoint.
HOST_PROVIDED_MODEL_NAME: str = "host-provided"

#: LangChain ``init_chat_model`` provider-prefix → wire dialect, used
#: by :func:`default_model_registry` to infer the dialect from the
#: synthesized ``provider:model`` default strings.
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
    ordering only (and only on the unbound tag-resolution path).
    ``consumer`` is the registry ``bindings:`` lookup key — a harness
    name (``"deep_agents"``, ``"ms_agent_framework"``) today, and
    non-harness consumers (``"embeddings"``, ``"memory"``) as they
    land. An open vocabulary: an unbound consumer falls back to the
    ``default`` binding, then to tag-filtered resolution.
    """

    required_tags: list[str] = field(default_factory=list)
    preferred_tags: list[str] = field(default_factory=list)
    consumer: str = DEFAULT_BINDING


@runtime_checkable
class ModelProvider(Protocol):
    """Resolve capability requirements to an ordered ModelRef chain."""

    def resolve(self, request: ModelRequest) -> list[ModelRef]: ...
    def list_models(self) -> list[ModelRef]: ...


@dataclass
class ModelRegistry:
    """Parsed persona ``models:`` section.

    ``entries`` preserves declaration order (dict insertion order);
    ``fallbacks`` maps entry name → ordered fallback entry names;
    ``bindings`` maps consumer name → entry name (the ``default``
    binding key applies to any consumer without an explicit binding).
    """

    entries: dict[str, ModelRef] = field(default_factory=dict)
    fallbacks: dict[str, list[str]] = field(default_factory=dict)
    bindings: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.entries)


def parse_model_registry(raw: dict[str, Any] | None) -> ModelRegistry:
    """Parse and validate a persona-level ``models:`` registry.

    Shape: ``models: {entries: {<name>: {...}}, bindings: {<consumer>:
    <entry name>}}``. Entries with unknown dialects, out-of-vocabulary
    tags, fallback references to undeclared entries, or bindings that
    target undeclared entries fail with a :class:`ModelRegistryError`
    naming the offender — persona load surfaces this as an actionable
    error. Unknown top-level keys (including the pre-verdict-3 flat
    entry map) are rejected with a pointer to the current shape.
    """
    raw = raw or {}
    unknown_keys = sorted(set(raw) - {"entries", "bindings"})
    if unknown_keys:
        raise ModelRegistryError(
            f"models: unknown top-level keys {unknown_keys}. Expected "
            f"'entries:' (name -> model spec) and optional 'bindings:' "
            f"(consumer -> entry name); model entries live under "
            f"'entries:', not at the top level."
        )

    raw_entries = raw.get("entries") or {}
    raw_bindings = raw.get("bindings") or {}
    if not isinstance(raw_entries, dict):
        raise ModelRegistryError(
            f"models entries: expected a mapping, got "
            f"{type(raw_entries).__name__}."
        )
    if not isinstance(raw_bindings, dict):
        raise ModelRegistryError(
            f"models bindings: expected a mapping, got "
            f"{type(raw_bindings).__name__}."
        )

    entries: dict[str, ModelRef] = {}
    fallbacks: dict[str, list[str]] = {}

    for name, spec in raw_entries.items():
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

    bindings: dict[str, str] = {}
    for consumer, target in raw_bindings.items():
        if not isinstance(target, str) or not target:
            raise ModelRegistryError(
                f"models binding {consumer!r}: expected an entry name "
                f"string, got {target!r}."
            )
        if target not in entries:
            raise ModelRegistryError(
                f"models binding {consumer!r} targets {target!r}, but no "
                f"entry named {target!r} exists. Declared entries: "
                f"{list(entries)}."
            )
        bindings[consumer] = target

    return ModelRegistry(entries=entries, fallbacks=fallbacks, bindings=bindings)


def default_model_registry(
    defaults: dict[str, str] | None = None,
) -> ModelRegistry:
    """Synthesize the registry used when a persona declares no ``models:``.

    One entry per known harness default (:data:`DEFAULT_HARNESS_MODELS`),
    with a binding mapping each harness name to its default entry. The
    entry name and ``model_id`` both carry the full ``provider:model``
    string — the LangChain binding consumes a ``model_id`` containing
    ``:`` verbatim, so the synthesized defaults reproduce the exact
    ``init_chat_model`` call each harness made before P19; the dialect
    is inferred from the provider prefix (span labeling only).
    """
    if defaults is None:
        defaults = DEFAULT_HARNESS_MODELS
    entries: dict[str, ModelRef] = {}
    bindings: dict[str, str] = {}
    for consumer, model in defaults.items():
        if model not in entries:
            prefix, _, _ = model.partition(":")
            dialect = _PREFIX_TO_DIALECT.get(prefix, "openai-compatible")
            entries[model] = ModelRef(name=model, dialect=dialect, model_id=model)
        bindings[consumer] = model
    return ModelRegistry(
        entries=entries,
        fallbacks={name: [] for name in entries},
        bindings=bindings,
    )


class RegistryModelProvider:
    """Registry-backed provider — bindings first, then tag resolution.

    Resolution: the request's ``consumer`` is looked up in the
    registry ``bindings:`` (falling back to the ``default`` binding).
    A bound consumer resolves to the bound entry followed by its
    declared ``fallbacks``, filtered by ``required_tags`` — a chain
    member that drops a required capability such as ``private-data-ok``
    never enters the chain; an all-filtered chain raises rather than
    silently substituting an unbound entry. An unbound consumer falls
    back to tag resolution: entries carrying every ``required_tags``
    tag are candidates, ordered by preferred-tag match count
    (descending) then declaration order, each followed by its filtered
    ``fallbacks``. Duplicates keep their first position.
    """

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def list_models(self) -> list[ModelRef]:
        return list(self._registry.entries.values())

    def _resolve_binding(
        self, request: ModelRequest, bound_name: str
    ) -> list[ModelRef]:
        required = set(request.required_tags)
        chain: list[ModelRef] = []
        seen: set[str] = set()
        for name in (bound_name, *self._registry.fallbacks.get(bound_name, [])):
            if name in seen:
                continue
            seen.add(name)
            ref = self._registry.entries[name]
            if required.issubset(ref.tags):
                chain.append(ref)
        if not chain:
            raise ModelResolutionError(
                f"Consumer {request.consumer!r} is bound to {bound_name!r}, "
                f"but neither it nor its declared fallbacks carry "
                f"required_tags={sorted(required)}."
            )
        return chain

    def resolve(self, request: ModelRequest) -> list[ModelRef]:
        bindings = self._registry.bindings
        bound_name = bindings.get(request.consumer) or bindings.get(
            DEFAULT_BINDING
        )
        if bound_name is not None:
            return self._resolve_binding(request, bound_name)

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
