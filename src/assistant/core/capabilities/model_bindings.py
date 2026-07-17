"""Per-consumer ModelRef bindings — model-provider-routing (P19).

The binding is the only consumer-specific code; the seam is the
``ModelProvider`` protocol itself (ADR-0005). Three bindings:

- :func:`bind_langchain` — ``init_chat_model`` for LangChain-native
  harnesses (DeepAgents);
- :func:`bind_msaf_chat_client` — ``agent-framework`` chat clients for
  the MSAF harness (``openai-compatible`` refs only; the SDK ships no
  connector for the other dialects);
- :class:`OpenAICompatibleClient` — raw client for direct calls that
  need no harness, including embeddings, covering every
  ``openai-compatible`` endpoint (OpenRouter and all local backends).

Bindings resolve ``credential_ref`` through the ``CredentialProvider``
seam at binding time and gate dispatch through the persona's
``GuardrailProvider`` via
``check_action(ActionRequest(action_type="model_call", ...))``.
No second provider-abstraction library is introduced (ADR-0005).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from assistant.core.capabilities.audit import emit_guardrail_audit
from assistant.core.capabilities.credentials import (
    CredentialProvider,
    EnvCredentialProvider,
)
from assistant.core.capabilities.guardrails import GuardrailProvider
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.models import ModelRef
from assistant.core.capabilities.types import ActionRequest

#: Wire dialect → LangChain ``init_chat_model`` provider prefix.
_DIALECT_TO_LANGCHAIN_PREFIX: dict[str, str] = {
    "anthropic": "anthropic",
    "openai-compatible": "openai",
    "gemini": "google_genai",
    "bedrock": "bedrock_converse",
    "vertex": "google_vertexai",
}


class ModelBindingError(RuntimeError):
    """A ModelRef cannot be adapted by the requested binding."""


class ModelCallDeniedError(PermissionError):
    """The persona's GuardrailProvider denied a ``model_call`` action."""


def check_model_call(
    guardrails: GuardrailProvider | None,
    ref: ModelRef,
    *,
    persona: str = "",
    role: str = "",
    metadata: dict[str, Any] | None = None,
    identity: AgentIdentity | None = None,
) -> None:
    """Budget hook: gate a model dispatch through the guardrail seam.

    Raises :class:`ModelCallDeniedError` when the decision is
    ``allowed=False`` — the wire call (or client construction) never
    happens, and the caller receives the guardrail reason. A
    ``require_confirmation=True`` decision also raises: the approval
    interrupt flow (guardrail-provider spec) rides on durable sessions
    which are not wired yet, so the deny-safe behavior is to refuse
    rather than silently proceed. ``AllowAllGuardrails`` returns
    ``allowed=True`` for everything, preserving current behavior.

    P25 agent-iam: the request carries an :class:`AgentIdentity` —
    the caller's, or one synthesized from ``persona``/``role`` when
    not injected — so identity-aware policies can match and every
    decision emits an audit record through the telemetry provider.
    """
    if guardrails is None:
        return
    request_metadata: dict[str, Any] = {
        "dialect": ref.dialect,
        "model_id": ref.model_id,
    }
    if ref.pricing:
        request_metadata["pricing"] = ref.pricing
    if metadata:
        request_metadata.update(metadata)
    if identity is None and (persona or role):
        identity = AgentIdentity(persona=persona, role=role)
    request = ActionRequest(
        action_type="model_call",
        resource=ref.name,
        persona=persona,
        role=role,
        metadata=request_metadata,
        identity=identity,
    )
    decision = guardrails.check_action(request)
    emit_guardrail_audit(request, decision)
    if not decision.allowed:
        raise ModelCallDeniedError(
            f"Model call to {ref.name!r} denied by guardrails: "
            f"{decision.reason or '<no reason given>'}"
        )
    if decision.require_confirmation:
        raise ModelCallDeniedError(
            f"Model call to {ref.name!r} requires confirmation, but the "
            "approval interrupt flow is not wired yet (deferred to the "
            "durable-session work from capability-protocols-v2); denying."
        )


def langchain_model_string(ref: ModelRef) -> str:
    """Derive the ``init_chat_model`` model string for a ModelRef.

    A ``model_id`` that already carries a ``provider:`` prefix (the
    synthesized default-registry entries store full ``provider:model``
    strings) is used verbatim — this preserves the exact pre-P19
    ``init_chat_model`` call for the defaults. Registry ``id`` values
    are bare wire identifiers (OpenRouter uses ``/``, never ``:``), so
    they get the dialect-mapped prefix prepended.
    """
    if ":" in ref.model_id:
        return ref.model_id
    prefix = _DIALECT_TO_LANGCHAIN_PREFIX[ref.dialect]
    return f"{prefix}:{ref.model_id}"


def bind_langchain(
    ref: ModelRef,
    *,
    credentials: CredentialProvider | None = None,
    guardrails: GuardrailProvider | None = None,
    persona: str = "",
    role: str = "",
    init_fn: Callable[..., Any] | None = None,
) -> Any:
    """Adapt a ModelRef via LangChain's ``init_chat_model``.

    ``base_url`` and ``api_key`` kwargs are passed only when the ref
    declares an endpoint / a resolving credential ref, so the
    synthesized default-registry refs produce the exact
    single-argument ``init_chat_model(model)`` call the harness made
    before P19. ``init_fn`` lets the harness inject its own
    module-level ``init_chat_model`` import (keeps the established
    patch point for tests); the default imports from ``langchain``.
    """
    check_model_call(guardrails, ref, persona=persona, role=role)

    if init_fn is None:
        from langchain.chat_models import init_chat_model

        init_fn = init_chat_model

    kwargs: dict[str, Any] = {}
    if ref.endpoint:
        kwargs["base_url"] = ref.endpoint
    credentials = credentials or EnvCredentialProvider()
    if ref.credential_ref:
        api_key = credentials.get_credential(ref.credential_ref)
        if api_key:
            kwargs["api_key"] = api_key
    return init_fn(langchain_model_string(ref), **kwargs)


def _bare_model_id(ref: ModelRef) -> str:
    """Strip a LangChain-style ``provider:`` prefix off ``model_id``.

    Synthesized default-registry refs carry a full ``openai:gpt-4o``
    string; wire clients want the bare ``gpt-4o``.
    """
    _, sep, rest = ref.model_id.partition(":")
    return rest if sep else ref.model_id


def bind_msaf_chat_client(
    ref: ModelRef,
    *,
    credentials: CredentialProvider | None = None,
    guardrails: GuardrailProvider | None = None,
    persona: str = "",
    role: str = "",
) -> Any:
    """Adapt a ModelRef to an ``agent-framework`` ``OpenAIChatClient``.

    Only ``openai-compatible`` refs are supported — the pinned
    ``agent-framework-openai`` package ships no connector for the other
    dialects (the ``azure_openai`` branch degrades to its documented
    install error inside the harness, unchanged by P19). ``model_id``,
    ``api_key``, and ``base_url`` kwargs are passed only when
    non-empty so env-var-driven configuration keeps working.
    """
    check_model_call(guardrails, ref, persona=persona, role=role)

    if ref.dialect != "openai-compatible":
        raise ModelBindingError(
            f"MSAF binding supports only 'openai-compatible' refs; got "
            f"dialect {ref.dialect!r} for {ref.name!r}. Route this model "
            "through the DeepAgents harness or add a connector package."
        )
    try:
        from agent_framework.openai import (  # type: ignore[import-not-found, unused-ignore]
            OpenAIChatClient,
        )
    except ImportError as exc:
        raise ModelBindingError(
            "Failed to import agent_framework.openai.OpenAIChatClient. "
            "Install with `pip install agent-framework-core "
            "agent-framework-openai` — see CLAUDE.md 'What's Not Yet "
            "Wired' for the packaging note."
        ) from exc

    kwargs: dict[str, Any] = {}
    model_id = _bare_model_id(ref)
    if model_id:
        kwargs["model_id"] = model_id
    credentials = credentials or EnvCredentialProvider()
    if ref.credential_ref:
        api_key = credentials.get_credential(ref.credential_ref)
        if api_key:
            kwargs["api_key"] = api_key
    if ref.endpoint:
        kwargs["base_url"] = ref.endpoint
    return OpenAIChatClient(**kwargs)


class OpenAICompatibleClient:
    """Raw OpenAI-compatible binding for direct calls (no harness).

    Minimal by design — the P20 (local inference node) and P21-adjacent
    consumers (embeddings, summarization) call ``chat`` / ``embeddings``
    directly against any OpenAI-compatible endpoint (OpenRouter, vLLM,
    Ollama, NIM). Uses the already-present ``httpx`` dependency; the
    guardrail budget hook fires before every wire call. Tests inject
    ``http_client`` (e.g. ``httpx.MockTransport``-backed) so nothing
    touches the network.
    """

    def __init__(
        self,
        ref: ModelRef,
        *,
        credentials: CredentialProvider | None = None,
        guardrails: GuardrailProvider | None = None,
        persona: str = "",
        role: str = "",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if ref.dialect != "openai-compatible":
            raise ModelBindingError(
                f"OpenAICompatibleClient requires an 'openai-compatible' "
                f"ref; got dialect {ref.dialect!r} for {ref.name!r}."
            )
        if not ref.endpoint:
            raise ModelBindingError(
                f"OpenAICompatibleClient requires a non-empty endpoint on "
                f"{ref.name!r} (base URL of the OpenAI-compatible server)."
            )
        self._ref = ref
        self._credentials = credentials or EnvCredentialProvider()
        self._guardrails = guardrails
        self._persona = persona
        self._role = role
        self._http_client = http_client
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = (
            self._credentials.get_credential(self._ref.credential_ref)
            if self._ref.credential_ref
            else ""
        )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._ref.endpoint.rstrip("/") + path
        if self._http_client is not None:
            response = await self._http_client.post(
                url, json=payload, headers=self._headers()
            )
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url, json=payload, headers=self._headers()
                )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def chat(
        self, messages: list[dict[str, Any]], **params: Any
    ) -> dict[str, Any]:
        """POST ``/chat/completions`` and return the parsed response."""
        check_model_call(
            self._guardrails,
            self._ref,
            persona=self._persona,
            role=self._role,
            metadata={"consumer": "chat"},
        )
        payload = {
            "model": _bare_model_id(self._ref),
            "messages": messages,
            **params,
        }
        return await self._post("/chat/completions", payload)

    async def embeddings(
        self, input_texts: list[str] | str, **params: Any
    ) -> dict[str, Any]:
        """POST ``/embeddings`` and return the parsed response."""
        check_model_call(
            self._guardrails,
            self._ref,
            persona=self._persona,
            role=self._role,
            metadata={"consumer": "embedding"},
        )
        payload = {
            "model": _bare_model_id(self._ref),
            "input": input_texts,
            **params,
        }
        return await self._post("/embeddings", payload)
