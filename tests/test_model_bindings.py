"""Tests for the per-consumer ModelRef bindings (P19 model-provider-routing).

Covers the model-provider spec "Per-Consumer Model Bindings" and
"Model-Call Budget Hook" requirements: LangChain dialect mapping,
credential resolution through the CredentialProvider seam, the MSAF
binding's kwargs + dialect guard, the raw OpenAI-compatible client
(httpx.MockTransport — no network), and guardrail denial paths.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from assistant.core.capabilities.guardrails import AllowAllGuardrails
from assistant.core.capabilities.model_bindings import (
    ModelBindingError,
    ModelCallDeniedError,
    OpenAICompatibleClient,
    bind_langchain,
    bind_msaf_chat_client,
    check_model_call,
    langchain_model_string,
)
from assistant.core.capabilities.models import ModelRef
from assistant.core.capabilities.types import ActionDecision, ActionRequest


class _StaticCredentials:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = mapping or {}

    def get_credential(self, ref: str) -> str:
        return self._mapping.get(ref, "")


class _DenyGuardrails:
    def __init__(self, reason: str = "budget exceeded") -> None:
        self.reason = reason
        self.requests: list[ActionRequest] = []

    def check_action(self, action: ActionRequest) -> ActionDecision:
        self.requests.append(action)
        return ActionDecision(allowed=False, reason=self.reason)

    def check_delegation(self, parent: str, sub: str, task: str) -> ActionDecision:
        return ActionDecision(allowed=True)

    def declare_risk(self, action: ActionRequest) -> Any:
        return 1


class _ConfirmGuardrails(_DenyGuardrails):
    def check_action(self, action: ActionRequest) -> ActionDecision:
        self.requests.append(action)
        return ActionDecision(allowed=True, require_confirmation=True)


# ── Budget hook ──────────────────────────────────────────────────────


def test_check_model_call_sends_dialect_and_pricing_metadata() -> None:
    guardrails = _DenyGuardrails()
    ref = ModelRef(
        name="sonnet",
        dialect="anthropic",
        pricing={"prompt": "0.000003", "completion": "0.000015"},
    )
    with pytest.raises(ModelCallDeniedError, match="budget exceeded"):
        check_model_call(guardrails, ref, persona="p", role="r")
    (request,) = guardrails.requests
    assert request.action_type == "model_call"
    assert request.resource == "sonnet"
    assert request.persona == "p"
    assert request.role == "r"
    assert request.metadata["dialect"] == "anthropic"
    assert request.metadata["pricing"]["prompt"] == "0.000003"


def test_check_model_call_allow_all_preserves_behavior() -> None:
    ref = ModelRef(name="sonnet", dialect="anthropic")
    check_model_call(AllowAllGuardrails(), ref)  # must not raise


def test_check_model_call_confirmation_denies_until_interrupt_flow() -> None:
    ref = ModelRef(name="sonnet", dialect="anthropic")
    with pytest.raises(ModelCallDeniedError, match="confirmation"):
        check_model_call(_ConfirmGuardrails(), ref)


# ── LangChain binding ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dialect", "model_id", "expected"),
    [
        ("anthropic", "claude-sonnet-4-20250514", "anthropic:claude-sonnet-4-20250514"),
        ("gemini", "gemini-2.0-flash", "google_genai:gemini-2.0-flash"),
        ("bedrock", "claude-3", "bedrock_converse:claude-3"),
        ("vertex", "gemini-2.0-pro", "google_vertexai:gemini-2.0-pro"),
        ("openai-compatible", "openai/gpt-4o", "openai:openai/gpt-4o"),
        # StaticModelProvider passthrough: already-prefixed → verbatim
        ("anthropic", "anthropic:claude-sonnet-x", "anthropic:claude-sonnet-x"),
    ],
)
def test_langchain_model_string_dialect_mapping(
    dialect: str, model_id: str, expected: str
) -> None:
    ref = ModelRef(name="m", dialect=dialect, model_id=model_id)
    assert langchain_model_string(ref) == expected


def test_bind_langchain_plain_ref_calls_init_with_single_argument() -> None:
    """Static passthrough: no endpoint/credential → the exact pre-P19 call."""
    init_fn = MagicMock(return_value="model-handle")
    ref = ModelRef(
        name="anthropic:claude-sonnet-x",
        dialect="anthropic",
        model_id="anthropic:claude-sonnet-x",
    )
    result = bind_langchain(ref, init_fn=init_fn)
    assert result == "model-handle"
    init_fn.assert_called_once_with("anthropic:claude-sonnet-x")


def test_bind_langchain_passes_base_url_and_resolved_api_key() -> None:
    init_fn = MagicMock()
    ref = ModelRef(
        name="router",
        dialect="openai-compatible",
        model_id="openai/gpt-4o",
        endpoint="https://openrouter.ai/api/v1",
        credential_ref="OPENROUTER_API_KEY",
    )
    bind_langchain(
        ref,
        credentials=_StaticCredentials({"OPENROUTER_API_KEY": "sk-test"}),
        init_fn=init_fn,
    )
    init_fn.assert_called_once_with(
        "openai:openai/gpt-4o",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-test",
    )


def test_bind_langchain_omits_api_key_when_credential_unresolved() -> None:
    init_fn = MagicMock()
    ref = ModelRef(
        name="local",
        dialect="openai-compatible",
        model_id="llama-3.1-8b-instruct",
        endpoint="http://gx10.local:8000/v1",
        credential_ref="UNSET_KEY",
    )
    bind_langchain(ref, credentials=_StaticCredentials(), init_fn=init_fn)
    init_fn.assert_called_once_with(
        "openai:llama-3.1-8b-instruct", base_url="http://gx10.local:8000/v1"
    )


def test_bind_langchain_denied_never_constructs_model() -> None:
    init_fn = MagicMock()
    ref = ModelRef(name="sonnet", dialect="anthropic")
    with pytest.raises(ModelCallDeniedError, match="budget exceeded"):
        bind_langchain(ref, guardrails=_DenyGuardrails(), init_fn=init_fn)
    init_fn.assert_not_called()


# ── MSAF binding ─────────────────────────────────────────────────────


def test_bind_msaf_rejects_non_openai_compatible_dialects() -> None:
    ref = ModelRef(name="sonnet", dialect="anthropic")
    with pytest.raises(ModelBindingError, match="openai-compatible"):
        bind_msaf_chat_client(ref)


def test_bind_msaf_constructs_openai_chat_client_with_kwargs() -> None:
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    ref = ModelRef(
        name="gpt",
        dialect="openai-compatible",
        model_id="openai:gpt-4o",
        credential_ref="OPENAI_API_KEY",
    )
    with patch(
        "agent_framework.openai.OpenAIChatClient", new=_FakeClient, create=True
    ):
        client = bind_msaf_chat_client(
            ref, credentials=_StaticCredentials({"OPENAI_API_KEY": "sk-o"})
        )
    assert isinstance(client, _FakeClient)
    # provider prefix stripped for the wire client
    assert captured == {"model_id": "gpt-4o", "api_key": "sk-o"}


def test_bind_msaf_env_driven_config_passes_no_credential_kwargs() -> None:
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    ref = ModelRef(
        name="openai:gpt-4o",
        dialect="openai-compatible",
        model_id="openai:gpt-4o",
    )
    with patch(
        "agent_framework.openai.OpenAIChatClient", new=_FakeClient, create=True
    ):
        bind_msaf_chat_client(ref, credentials=_StaticCredentials())
    assert captured == {"model_id": "gpt-4o"}


def test_bind_msaf_denied_before_import_or_construction() -> None:
    ref = ModelRef(name="gpt", dialect="openai-compatible")
    with pytest.raises(ModelCallDeniedError):
        bind_msaf_chat_client(ref, guardrails=_DenyGuardrails())


# ── Raw OpenAI-compatible client ─────────────────────────────────────


def _ref_local() -> ModelRef:
    return ModelRef(
        name="local-fast",
        dialect="openai-compatible",
        model_id="llama-3.1-8b-instruct",
        endpoint="http://gx10.local:8000/v1",
        credential_ref="LOCAL_KEY",
    )


def _mock_client(recorded: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_raw_client_requires_openai_compatible_dialect() -> None:
    with pytest.raises(ModelBindingError, match="openai-compatible"):
        OpenAICompatibleClient(ModelRef(name="s", dialect="anthropic"))


def test_raw_client_requires_endpoint() -> None:
    with pytest.raises(ModelBindingError, match="endpoint"):
        OpenAICompatibleClient(
            ModelRef(name="s", dialect="openai-compatible")
        )


def test_raw_client_chat_posts_openai_wire_shape() -> None:
    recorded: list[httpx.Request] = []
    client = OpenAICompatibleClient(
        _ref_local(),
        credentials=_StaticCredentials({"LOCAL_KEY": "sk-local"}),
        http_client=_mock_client(recorded),
    )
    result = asyncio.run(
        client.chat([{"role": "user", "content": "hi"}], temperature=0.2)
    )
    assert result == {"ok": True}
    (request,) = recorded
    assert str(request.url) == "http://gx10.local:8000/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-local"
    payload = json.loads(request.content)
    assert payload["model"] == "llama-3.1-8b-instruct"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["temperature"] == 0.2


def test_raw_client_embeddings_needs_no_harness_machinery() -> None:
    recorded: list[httpx.Request] = []
    client = OpenAICompatibleClient(
        _ref_local(),
        credentials=_StaticCredentials(),
        http_client=_mock_client(recorded),
    )
    asyncio.run(client.embeddings(["a", "b"]))
    (request,) = recorded
    assert str(request.url) == "http://gx10.local:8000/v1/embeddings"
    # unresolved credential → no Authorization header
    assert "authorization" not in {k.lower() for k in request.headers}
    payload = json.loads(request.content)
    assert payload == {"model": "llama-3.1-8b-instruct", "input": ["a", "b"]}


def test_raw_client_denied_call_never_reaches_the_wire() -> None:
    recorded: list[httpx.Request] = []
    client = OpenAICompatibleClient(
        _ref_local(),
        credentials=_StaticCredentials(),
        guardrails=_DenyGuardrails(),
        http_client=_mock_client(recorded),
    )
    with pytest.raises(ModelCallDeniedError, match="budget exceeded"):
        asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
    assert recorded == []  # no HTTP request was issued
