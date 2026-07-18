"""MS Agent Framework harness adapter.

Replaces the P1 ``NotImplementedError``-raising stub with a full
``SdkHarnessAdapter`` implementation backed by the official
``agent-framework`` Python package
(``github.com/microsoft/agent-framework``).

Design references (``openspec/changes/ms-graph-extension``):

- D5  — MSAF SDK is ``agent-framework``; harness uses
        ``OpenAIChatClient`` or ``AzureOpenAIChatClient`` per persona
- D10 — capability resolver wiring (ToolPolicy + ContextProvider +
        GuardrailProvider + MemoryPolicy minimal injection)
- P17 tool-spec migration — ``create_agent(tools)`` receives the
        complete, already-aggregated ToolSpec list from
        ``ToolPolicy.authorized_tools()`` and renders it through the
        MSAF adapter (``render_msaf_tools`` → ``FunctionTool``); the
        harness NEVER derives tools from the ``extensions`` argument
        (replaces the D11 ``as_ms_agent_tools()`` consumption)
- D27 — minimal MemoryPolicy injection: prepend
        ``MemoryPolicy.get_recent_snippets`` results under a
        ``## Recent context`` heading inside the composed system prompt
"""

from __future__ import annotations

import inspect
import json
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from assistant.core.capabilities.model_bindings import (
    ModelCallDeniedError,
    bind_msaf_chat_client,
)
from assistant.core.capabilities.models import (
    DEFAULT_HARNESS_MODELS,
    ModelRef,
    ModelRequest,
    ModelResolutionError,
)
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import SdkHarnessAdapter
from assistant.harnesses.sdk.events import (
    HarnessEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)
from assistant.telemetry.decorators import traced_harness

if TYPE_CHECKING:
    from collections.abc import Callable

    from assistant.core.capabilities.context import ContextProvider
    from assistant.core.capabilities.credentials import CredentialProvider
    from assistant.core.capabilities.guardrails import GuardrailProvider
    from assistant.core.capabilities.memory import MemoryPolicy
    from assistant.core.capabilities.models import ModelProvider
    from assistant.core.capabilities.tools import ToolPolicy
    from assistant.delegation.context import DelegationContext

#: Memory snippet limit — D27 sets this at 10. Tests can override via
#: the ``memory_snippet_limit`` constructor kwarg.
DEFAULT_MEMORY_SNIPPET_LIMIT: int = 10

#: Section heading prepended to the composed prompt when memory
#: snippets are present (D27 / spec scenario "Memory snippets prepended
#: to instructions").
_MEMORY_SECTION_HEADING: str = "## Recent context"


class MSAgentFrameworkHarness(SdkHarnessAdapter):
    """SDK harness for the official ``agent-framework`` package.

    The harness is constructed by ``create_harness(persona, role,
    "ms_agent_framework")`` per the registry contract. Production code
    relies on the two-arg constructor only; tests inject the optional
    ``tool_policy`` / ``memory_policy`` / ``guardrail_provider`` /
    ``chat_client_factory`` kwargs to bypass the SDK and avoid real
    OAuth + LLM round-trips.
    """

    #: Span-default chat-client model id, sourced from the shared
    #: harness-default table that also seeds the synthesized registry
    #: (P19 verdict #3 — registry-only).
    _DEFAULT_MODEL: str = DEFAULT_HARNESS_MODELS["ms_agent_framework"]

    def __init__(
        self,
        persona: PersonaConfig,
        role: RoleConfig,
        *,
        tool_policy: ToolPolicy | None = None,
        memory_policy: MemoryPolicy | None = None,
        guardrail_provider: GuardrailProvider | None = None,
        context_provider: ContextProvider | None = None,
        chat_client_factory: Callable[[], Any] | None = None,
        memory_snippet_limit: int = DEFAULT_MEMORY_SNIPPET_LIMIT,
        model_provider: ModelProvider | None = None,
        credential_provider: CredentialProvider | None = None,
        delegation_context: DelegationContext | None = None,
    ) -> None:
        super().__init__(persona, role)
        # P12 delegation-context: set only on sub-harnesses built by
        # spawn_sub_agent; rendered ahead of the composed instructions.
        self._delegation_context = delegation_context
        self._tool_policy = tool_policy
        self._memory_policy = memory_policy
        self._guardrail_provider = guardrail_provider
        self._context_provider = context_provider
        self._chat_client_factory = chat_client_factory
        self._memory_snippet_limit = memory_snippet_limit
        self._model_provider = model_provider
        self._credential_provider = credential_provider
        self._active_model: str = self._DEFAULT_MODEL
        # Resolved ModelRef backing ``_active_model`` — read by
        # ``@traced_harness`` for cost attribution (P19).
        self._active_model_ref: ModelRef | None = None
        # Stable conversation-thread identifier for transport binding (D4).
        # UUID4 synthesized once at construction; persists for the lifetime of
        # this adapter instance across invoke / astream_invoke calls.
        self._thread_id: str = str(uuid.uuid4())

    def name(self) -> str:
        return "ms_agent_framework"

    @property
    def thread_id(self) -> str:
        """Stable conversation-thread identifier for this adapter instance.

        Per the harness-adapter spec "SdkHarnessAdapter exposes a thread_id
        for transport binding": the value MUST be non-empty and MUST persist
        for the lifetime of the adapter instance across multiple invoke /
        astream_invoke calls. MSAF synthesizes a UUID at construction time
        (no native concept of a thread_id in agent-framework v1.x).
        """
        return self._thread_id

    # ── Capability resolution ─────────────────────────────────────

    def _resolve_tool_policy(self) -> ToolPolicy:
        if self._tool_policy is not None:
            return self._tool_policy
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver()
        return resolver.resolve(self.persona, "sdk", self.role).tools

    def _resolve_memory_policy(self) -> MemoryPolicy:
        if self._memory_policy is not None:
            return self._memory_policy
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver()
        return resolver.resolve(self.persona, "sdk", self.role).memory

    def _resolve_guardrail_provider(self) -> GuardrailProvider:
        if self._guardrail_provider is not None:
            return self._guardrail_provider
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver()
        return resolver.resolve(self.persona, "sdk", self.role).guardrails

    def _resolve_context_provider(self) -> ContextProvider:
        """Return the persona+role's ContextProvider, or the default.

        Per ms-agent-framework-harness spec / "Capability Consumption":
        the harness MUST consume ``ContextProvider`` from the
        ``CapabilityResolver`` rather than calling
        ``compose_system_prompt`` directly. The default provider falls
        back to the existing ``compose_system_prompt`` shape so personas
        without a custom context provider behave identically to before.
        """
        if self._context_provider is not None:
            return self._context_provider
        from assistant.core.capabilities.context import DefaultContextProvider
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver()
        resolved = resolver.resolve(self.persona, "sdk", self.role)
        if resolved.context is not None:
            return resolved.context
        return DefaultContextProvider()

    def _resolve_model_provider(self) -> ModelProvider:
        """Return the injected ModelProvider or resolve slot #6.

        Mirrors ``DeepAgentsHarness._resolve_model_provider``:
        registry-only (P19 verdict #3) — the resolver hands back a
        :class:`RegistryModelProvider` (persona-declared or
        synthesized-default) and this harness selects its model via
        the ``ModelRequest.consumer`` binding lookup.
        """
        if self._model_provider is not None:
            return self._model_provider
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver()
        provider = resolver.resolve(self.persona, "sdk", self.role).models
        assert provider is not None  # resolver always fills slot #6
        return provider

    def _resolve_credential_provider(self) -> CredentialProvider:
        if self._credential_provider is not None:
            return self._credential_provider
        # P13 security-hardening: prefer the persona-scoped provider
        # built at persona load (persona .env first, process env
        # fallback) so model credential_refs resolve per-persona.
        persona_credentials = getattr(self.persona, "credentials", None)
        if persona_credentials is not None:
            return persona_credentials
        from assistant.core.capabilities.credentials import EnvCredentialProvider

        return EnvCredentialProvider()

    # ── Chat client construction ──────────────────────────────────

    def _build_chat_client(self) -> Any:
        """Build an ``agent_framework`` chat client per persona config.

        Per spec scenario "Chat client selection respects persona
        configuration": the persona's
        ``harnesses.ms_agent_framework.chat_client`` field selects
        between ``OpenAIChatClient`` (default) and
        ``AzureOpenAIChatClient``. Tests inject
        ``chat_client_factory`` to bypass this entirely.
        """
        if self._chat_client_factory is not None:
            return self._chat_client_factory()

        cfg = self.persona.harnesses.get("ms_agent_framework", {}) or {}
        chat_client_kind = cfg.get("chat_client", "openai")

        if chat_client_kind == "azure_openai":
            # Unchanged by model-provider-routing: no Azure OpenAI
            # connector package ships for agent-framework 1.10.x, so
            # this branch degrades to its documented install error
            # (CLAUDE.md "What's Not Yet Wired"). ``_active_model``
            # keeps its span default — the legacy per-harness ``model``
            # key is gone (P19 verdict #3, registry-only).
            try:
                from agent_framework.azure_openai import (  # type: ignore[import-not-found, unused-ignore]
                    AzureOpenAIChatClient,
                )
            except ImportError as exc:
                raise _agent_framework_install_error(
                    "agent_framework.azure_openai.AzureOpenAIChatClient"
                ) from exc

            return AzureOpenAIChatClient()

        # Default (openai) branch flows through the ModelProvider seam
        # (model-provider-routing, registry-only per P19 verdict #3):
        # the consumer binding selects a registry entry — persona
        # ``models:`` when declared, synthesized defaults otherwise. A
        # guardrail denial is a policy stop and propagates; a binding
        # failure tries the next ref in the resolved fallback chain.
        provider = self._resolve_model_provider()
        refs = provider.resolve(ModelRequest(consumer=self.name()))
        credentials = self._resolve_credential_provider()
        guardrails = self._resolve_guardrail_provider()

        last_exc: Exception | None = None
        for ref in refs:
            try:
                client = bind_msaf_chat_client(
                    ref,
                    credentials=credentials,
                    guardrails=guardrails,
                    persona=self.persona.name,
                    role=self.role.name,
                )
            except ModelCallDeniedError:
                raise
            except Exception as exc:
                last_exc = exc
                continue
            self._active_model = ref.model_id or ref.name
            self._active_model_ref = ref
            return client
        raise ModelResolutionError(
            f"Every ModelRef in the resolved chain failed to bind: "
            f"{[r.name for r in refs]}."
        ) from last_exc

    # ── Instruction composition (D27) ─────────────────────────────

    async def _compose_instructions(self) -> str:
        """Compose system prompt + optional memory snippet block.

        Per D27: the memory snippets are *prepended* under
        ``## Recent context`` so the agent reads them before the
        composed system-prompt body. An empty snippet list MUST leave
        the prompt unchanged (no heading injected). Snippet retrieval
        is awaited directly on the ``create_agent`` event loop
        (capability-protocols-v2 owner review verdict C8, 2026-07-16 —
        no sync bridge on the hot path).

        The base system prompt is sourced from the persona+role's
        ``ContextProvider`` (resolved via ``CapabilityResolver`` per
        spec "Capability Consumption" requirement). The default
        provider delegates to ``compose_system_prompt``; persona configs
        can override by registering a custom ContextProvider.
        """
        base = self._resolve_context_provider().compose_system_prompt(
            self.persona, self.role
        )

        memory_policy = self._resolve_memory_policy()
        snippets = await memory_policy.get_recent_snippets(
            self.persona, self.role, limit=self._memory_snippet_limit
        )
        instructions = base
        if snippets:
            snippet_block = "\n\n".join(snippets)
            instructions = (
                f"{_MEMORY_SECTION_HEADING}\n\n{snippet_block}\n\n{base}"
            )
        # P12 delegation-context: the delegation block leads the whole
        # prompt (identity + constraints before recent context). Absent
        # context leaves the instructions byte-identical to pre-P12.
        if self._delegation_context is not None:
            instructions = (
                f"{self._delegation_context.render()}\n\n{instructions}"
            )
        return instructions

    # ── SdkHarnessAdapter contract ────────────────────────────────

    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any:
        """Build an ``agent_framework.Agent`` for the persona/role pair.

        Steps:
        1. Render ``tools`` — the complete, already-aggregated ToolSpec
           list produced by ``ToolPolicy.authorized_tools()`` (the tool
           policy is the SOLE tool aggregator; spec harness-adapter
           "SdkHarnessAdapter.create_agent consumes the aggregated tool
           list as-is") — to the MSAF native shape via the per-harness
           adapter. The harness MUST NOT derive tools from
           ``extensions`` (that parameter is retained for non-tool
           concerns only).
        2. Compose instructions via ``_compose_instructions``
           (system prompt + optional memory snippets per D27).
        3. Build chat client per persona config.
        4. Construct ``Agent(client, instructions, tools)``.
        """
        from assistant.harnesses.tool_adapters import render_msaf_tools

        rendered_tools = render_msaf_tools(tools)

        instructions = await self._compose_instructions()
        chat_client = self._build_chat_client()

        try:
            from agent_framework import (  # type: ignore[import-not-found, attr-defined, unused-ignore]
                Agent,
            )
        except ImportError as exc:
            raise _agent_framework_install_error(
                "agent_framework.Agent"
            ) from exc

        return Agent(
            client=chat_client,
            instructions=instructions,
            tools=rendered_tools,
        )

    @traced_harness
    async def invoke(self, agent: Any, message: str) -> str:
        """Await ``agent.run`` and return the response string.

        Spec scenarios "invoke returns the agent's response string"
        and "invoke propagates underlying exceptions unchanged" — the
        ``@traced_harness`` decorator emits exactly one
        ``trace_llm_call`` whether the call succeeds or raises.
        """
        result = await agent.run(message)
        response = _stringify_run_result(result)
        # Post-turn capture (memory-retrieval-activation): best-effort,
        # error-swallowed — see SdkHarnessAdapter._capture_interaction.
        await self._capture_interaction(message, response)
        return response

    @traced_harness
    async def astream_invoke(
        self, agent: Any, message: str
    ) -> AsyncIterator[HarnessEvent]:
        """Stream a harness invocation as a sequence of HarnessEvent instances.

        Calls ``agent.run(messages, stream=True)`` which returns a
        ``ResponseStream[AgentResponseUpdate, AgentResponse[Any]]``. Each
        ``AgentResponseUpdate`` is translated to ``HarnessEvent`` variants
        per the D11 mapping table:

        - Text content (update.text is non-empty) → ``TextDelta``
        - Content item with type ``"function_call"`` → ``ToolCallStart`` +
          optionally ``ToolCallArgs`` (if arguments are present)
        - Content item with type ``"function_result"`` → ``ToolCallEnd``

        Lifecycle (D8 two-phase error contract):
        - Phase 1: yield terminal ``RunFinished(error=ClassName)`` on exception
        - Phase 2: re-raise the original exception unchanged

        The ``@traced_harness`` decorator handles observability: emits exactly
        one ``trace_llm_call`` per invocation with ``metadata={"streaming": True}``.

        Lazy imports of ``agent_framework`` are preserved (v1.0.1 namespace-
        package quirk — see CLAUDE.md "What's Not Yet Wired"). Tests mock the
        agent object directly and never trigger the real SDK import path.
        """
        run_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        # FIFO queue of synthesized call_ids for missing-id function_call
        # items, so subsequent missing-id function_result items can match
        # the *oldest* unpaired start (sequential AND parallel orphan
        # tool calls).  When the SDK supplies call_id on both sides the
        # queue stays empty — the SDK value is authoritative.
        # IMPL_REVIEW round-1 gemini #2 (single slot) → round-2 cross-vendor
        # (claude-r2-2 + codex-r2-1) upgraded to a deque for parallel orphans.
        pending_orphan_call_ids: deque[str] = deque()
        # Accumulated assistant text for post-turn memory capture on the
        # success path (memory-retrieval-activation).
        captured_text: list[str] = []
        started_at = datetime.now(UTC).isoformat()
        yield RunStarted(run_id=run_id, started_at=started_at)

        # agent.run(messages, stream=True) returns a ResponseStream (AsyncIterable).
        # The call itself is synchronous (not awaitable) when stream=True.
        try:
            response_stream = agent.run(message, stream=True)
        except GeneratorExit:
            # Client disconnected before stream construction. Propagate.
            raise
        except Exception as exc:
            finished_at = datetime.now(UTC).isoformat()
            yield RunFinished(
                run_id=run_id,
                finished_at=finished_at,
                error=type(exc).__name__,
            )
            raise

        # Best-effort finalization of the upstream MSAF ResponseStream on
        # GeneratorExit so a mid-stream client disconnect closes the SDK
        # iterator rather than leaving it pending until garbage collection.
        # We can't use ``contextlib.aclosing`` directly because
        # ``ResponseStream`` is not required by the agent-framework SDK
        # contract to expose ``aclose``; the test fakes (MagicMock-based)
        # also don't expose an awaitable aclose. Falling back to a defensive
        # try/finally that only awaits aclose when it's a real coroutine.
        # IMPL_REVIEW round-2 gemini-r2-3.
        try:
            async for update in response_stream:
                # --- Text content ---
                # Defensive: try .text property first (AgentResponseUpdate),
                # then fall back to .content / .delta for SDK shape drift
                # (D11 note).
                text = getattr(update, "text", None)
                if not isinstance(text, str):
                    text = getattr(update, "content", None) or ""
                    if not isinstance(text, str):
                        text = str(getattr(update, "delta", "") or "")
                if text:
                    captured_text.append(text)
                    yield TextDelta(message_id=message_id, text=text)

                # --- Tool-call content ---
                # Each update may carry a list of Content items with typed
                # slots. Defensive: fall back to empty list if .contents
                # is absent.
                contents = getattr(update, "contents", None) or []
                for content_item in contents:
                    item_type = getattr(content_item, "type", None)
                    call_id = getattr(content_item, "call_id", None)

                    if item_type == "function_call":
                        # ToolCallStart — name is the tool name
                        tool_name = (
                            getattr(content_item, "name", None) or "unknown"
                        )
                        effective_call_id = call_id or str(uuid.uuid4())
                        if not call_id:
                            # SDK omitted call_id — queue the synthesized
                            # UUID so a later missing-id function_result
                            # can pair with the *oldest* unmatched start
                            # (handles parallel orphans).
                            pending_orphan_call_ids.append(effective_call_id)
                        yield ToolCallStart(
                            call_id=effective_call_id, tool_name=tool_name
                        )
                        # ToolCallArgs — emit arguments if present
                        arguments = getattr(content_item, "arguments", None)
                        if arguments is not None:
                            if not isinstance(arguments, str):
                                try:
                                    arguments = json.dumps(arguments)
                                except (TypeError, ValueError):
                                    arguments = str(arguments)
                            yield ToolCallArgs(
                                call_id=effective_call_id,
                                args_chunk=arguments,
                            )

                    elif item_type == "function_result":
                        # SDK-provided call_id is authoritative. Otherwise
                        # match the oldest queued missing-id start (FIFO).
                        # Last resort: fresh UUID — bracket lost, the
                        # scenario violates the SDK contract.
                        if call_id:
                            effective_call_id = call_id
                        elif pending_orphan_call_ids:
                            effective_call_id = pending_orphan_call_ids.popleft()
                        else:
                            effective_call_id = str(uuid.uuid4())
                        result = getattr(content_item, "result", None)
                        yield ToolCallEnd(
                            call_id=effective_call_id, result=result
                        )

        except GeneratorExit:
            # Client disconnected mid-stream. Propagate unchanged so async
            # generator finalization (PEP 525) is honored. DO NOT yield
            # while handling GeneratorExit — Python raises RuntimeError.
            # IMPL_REVIEW round-1 claude #1. (Upstream stream cleanup runs
            # in the ``finally`` block below.)
            raise
        except Exception as exc:
            finished_at = datetime.now(UTC).isoformat()
            yield RunFinished(
                run_id=run_id,
                finished_at=finished_at,
                error=type(exc).__name__,
            )
            raise
        finally:
            # Best-effort close of the upstream SDK iterator on every
            # exit path (success, disconnect, exception). Skipped when
            # ``aclose`` is absent (e.g. ``MagicMock``-based test fakes)
            # or returns a non-coroutine. IMPL_REVIEW round-2 gemini-r2-3.
            aclose_fn = getattr(response_stream, "aclose", None)
            if callable(aclose_fn):
                aclose_result = aclose_fn()
                if inspect.iscoroutine(aclose_result):
                    await aclose_result

        # Post-turn capture BEFORE the terminal RunFinished yield: once
        # the consumer sees RunFinished it may close the generator, and
        # code after the final yield would be skipped by GeneratorExit.
        # Success path only — errors and disconnects are not captured.
        await self._capture_interaction(message, "".join(captured_text))

        finished_at = datetime.now(UTC).isoformat()
        yield RunFinished(run_id=run_id, finished_at=finished_at, error=None)

    async def spawn_sub_agent(
        self,
        role: RoleConfig,
        task: str,
        tools: list[Any],
        extensions: list[Any],
        context: DelegationContext | None = None,
    ) -> str:
        """Build a nested harness for ``role`` and invoke it on ``task``.

        Per spec "Capability Consumption" — the
        ``GuardrailProvider`` MUST be consulted via
        ``check_action(ActionRequest(kind="delegate", ...))`` BEFORE
        any ``Agent`` construction. A denied decision raises
        ``PermissionError``.

        P12 delegation-context: an optional ``context`` (constructed by
        the ``DelegationSpawner``) is threaded to the sub-harness, whose
        instruction composition renders it as a ``## Delegation
        context`` block. ``None`` preserves pre-P12 behavior exactly.
        """
        from assistant.core.capabilities.audit import emit_guardrail_audit
        from assistant.core.capabilities.identity import AgentIdentity
        from assistant.core.capabilities.types import ActionRequest

        guardrails = self._resolve_guardrail_provider()
        # P25 agent-iam: attach the acting principal so the decision is
        # attributable (identity-aware policies + audit record).
        request = ActionRequest(
            action_type="delegate",
            resource=role.name,
            persona=self.persona.name,
            role=self.role.name,
            metadata={"task": task},
            identity=AgentIdentity(
                persona=self.persona.name,
                role=self.role.name,
                session_id=self.thread_id,
            ),
        )
        decision = guardrails.check_action(request)
        emit_guardrail_audit(request, decision)
        if not decision.allowed:
            raise PermissionError(
                f"Delegation to role {role.name!r} denied by guardrails: "
                f"{decision.reason or '<no reason given>'}"
            )

        sub = MSAgentFrameworkHarness(
            self.persona,
            role,
            tool_policy=self._tool_policy,
            memory_policy=self._memory_policy,
            guardrail_provider=self._guardrail_provider,
            context_provider=self._context_provider,
            chat_client_factory=self._chat_client_factory,
            memory_snippet_limit=self._memory_snippet_limit,
            model_provider=self._model_provider,
            credential_provider=self._credential_provider,
            delegation_context=context,
        )
        agent = await sub.create_agent(tools, extensions)
        return await sub.invoke(agent, task)


def _agent_framework_install_error(symbol: str) -> RuntimeError:
    """Build an actionable error for a failed lazy ``agent_framework`` import.

    Three failure modes the user might hit at this point:

    1. The ``agent-framework`` package is not installed at all.
    2. Installed but a known v1.0.1 namespace-collision shipped an
       empty ``agent_framework/__init__.py``, so submodules import but
       top-level names (``Agent``) do not — see CLAUDE.md "What's Not
       Yet Wired" for the documented quirk.
    3. A different SDK version that no longer exposes the symbol the
       harness expects.

    All three surface as ``ImportError``; the message points the
    operator at concrete next steps so the failure is debuggable
    without grepping the harness source.
    """
    return RuntimeError(
        f"MSAgentFrameworkHarness: failed to import {symbol!r}. "
        "Install with `pip install 'agent-framework>=1.0.0,<2.0.0'`. "
        "If already installed, check for the v1.0.1 namespace-package "
        "quirk (empty agent_framework/__init__.py despite RECORD "
        "claiming bytes) — see CLAUDE.md 'What's Not Yet Wired' for "
        "the workaround. The harness module loads fine in this state; "
        "only invoke-time fails."
    )


def _stringify_run_result(result: Any) -> str:
    """Coerce an ``agent.run`` result into the response string.

    The ``agent-framework`` SDK has shipped slightly different result
    shapes between minor versions (object with ``.text`` /
    ``.content`` / ``.message.content``; sometimes a bare string). We
    accept any of these shapes and fall back to ``str(result)`` so the
    contract "returns a string" stays stable across SDK churn. Tests
    pin the expected shape to the SDK version actually in use.
    """
    if isinstance(result, str):
        return result
    for attr in ("text", "content", "response"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
    message = getattr(result, "message", None)
    if message is not None:
        for attr in ("content", "text"):
            value = getattr(message, attr, None)
            if isinstance(value, str):
                return value
    return str(result)
