"""Intent-classification router for automatic sub-role selection (P12).

Deterministic-first: candidate roles are scored by lexical overlap
between the task text and each role's identity (name / display name),
description, and ``preferred_tools`` (source + operation tokens). The
highest-scoring candidate wins; ties resolve to the earliest candidate
in the caller-supplied order (the parent role's ``allowed_sub_roles``
declaration order via ``delegate_auto``).

Model-assisted classification is OPTIONAL and gated behind an explicit
``router`` consumer binding in the persona ``models:`` registry (P19
consumer-binding vocabulary) — personas may bind ``router:`` to a
cheap/local entry. Without that binding the model path is never
attempted (the ``default`` binding does NOT enable it). When the model
path is enabled but fails for any reason — resolution error, guardrail
denial, transport failure, or an unparseable reply — the router falls
back to the deterministic score, always.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from assistant.core.role import RoleConfig

if TYPE_CHECKING:
    from assistant.core.capabilities.guardrails import GuardrailProvider
    from assistant.core.persona import PersonaConfig

logger = logging.getLogger(__name__)

#: Registry ``bindings:`` key that gates model-assisted classification.
ROUTER_CONSUMER: str = "router"

#: Scoring weights: a task-token hit on the role's name/display name
#: is the strongest signal, a preferred-tool token hit is next, a
#: description token hit is the weakest.
_WEIGHT_NAME: int = 3
_WEIGHT_TOOLS: int = 2
_WEIGHT_DESCRIPTION: int = 1

#: Minimal English stopword list — enough to keep glue words from
#: producing spurious cross-role matches; not a linguistic project.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "and", "are", "for", "from", "has", "have", "into", "its",
        "not", "our", "out", "over", "per", "than", "that", "the",
        "their", "them", "then", "these", "they", "this", "use",
        "using", "via", "was", "were", "what", "when", "which",
        "will", "with", "you", "your",
    }
)


class RoutingError(ValueError):
    """No candidate role could be selected for the task."""


@dataclass(frozen=True)
class RouteDecision:
    """Outcome of one routing call.

    ``method`` is ``"model"`` when the model-assisted path produced the
    selection and ``"deterministic"`` otherwise. ``scores`` always
    carries the deterministic scores (even on the model path) so the
    decision is auditable.
    """

    sub_role: str
    method: str
    scores: dict[str, int] = field(default_factory=dict)


def _tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens of length >= 3, minus stopwords."""
    return {
        t
        for t in re.findall(r"[a-z0-9]+", text.lower())
        if len(t) >= 3 and t not in _STOPWORDS
    }


def _tokens_match(a: str, b: str) -> bool:
    """Exact match, or mutual-prefix match for tokens of length >= 4.

    The prefix rule is a deliberately cheap stemmer substitute so
    morphological variants pair up ("draft"/"drafting",
    "email"/"emails", "debug"/"debugging", "write"/"writer") without a
    linguistics dependency.
    """
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        return a.startswith(b) or b.startswith(a)
    return False


def _match_count(task_tokens: set[str], role_tokens: set[str]) -> int:
    """Number of task tokens with at least one matching role token."""
    return sum(
        1
        for token in task_tokens
        if any(_tokens_match(token, other) for other in role_tokens)
    )


def score_role(task: str, role: RoleConfig) -> int:
    """Deterministic lexical score of ``role`` against ``task``.

    Weighted token-overlap (exact or mutual-prefix match): role
    name/display-name tokens x3, ``preferred_tools`` source/operation
    tokens x2, description tokens x1. Pure function — no I/O, no
    model calls.
    """
    task_tokens = _tokens(task)
    if not task_tokens:
        return 0
    name_tokens = _tokens(f"{role.name.replace('_', ' ')} {role.display_name}")
    tool_tokens: set[str] = set()
    for preferred in role.preferred_tools:
        tool_tokens |= _tokens(re.sub(r"[:_\-.]", " ", preferred))
    description_tokens = _tokens(role.description)
    return (
        _WEIGHT_NAME * _match_count(task_tokens, name_tokens)
        + _WEIGHT_TOOLS * _match_count(task_tokens, tool_tokens)
        + _WEIGHT_DESCRIPTION * _match_count(task_tokens, description_tokens)
    )


class DelegationRouter:
    """Select the sub-role for a task from a candidate list.

    ``model_invoker`` is an injectable async transport
    (``prompt -> reply text``) used by the model-assisted path; tests
    inject a fake, production builds one over the persona's ``router``
    model binding. Injecting an invoker does NOT enable the model path
    — only the explicit ``router`` binding does.
    """

    def __init__(
        self,
        persona: PersonaConfig,
        *,
        guardrails: GuardrailProvider | None = None,
        model_invoker: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self.persona = persona
        self._guardrails = guardrails
        self._model_invoker = model_invoker

    # ── gating ────────────────────────────────────────────────────

    def model_routing_enabled(self) -> bool:
        """True only when the persona binds the ``router`` consumer.

        The ``default`` binding deliberately does not spill into the
        router — model-assisted classification is opt-in per persona.
        """
        registry = getattr(self.persona, "models", None)
        bindings: dict[str, str] = getattr(registry, "bindings", {}) or {}
        return ROUTER_CONSUMER in bindings

    # ── routing ───────────────────────────────────────────────────

    async def route(
        self, task: str, candidates: list[RoleConfig]
    ) -> RouteDecision:
        """Pick one candidate for ``task``.

        Raises :class:`RoutingError` when ``candidates`` is empty or
        when the deterministic path is reached and every candidate
        scores zero (no signal — refusing to guess beats delegating a
        research task to a writer at random).
        """
        if not candidates:
            raise RoutingError(
                "No candidate sub-roles to route between — check the "
                "parent role's delegation.allowed_sub_roles and the "
                "persona's disabled_roles."
            )
        scores = {role.name: score_role(task, role) for role in candidates}

        if self.model_routing_enabled():
            chosen = await self._classify_with_model(task, candidates)
            if chosen is not None:
                logger.info(
                    "delegation router: model-assisted selection %r "
                    "(deterministic scores: %s)",
                    chosen,
                    scores,
                )
                return RouteDecision(
                    sub_role=chosen, method="model", scores=scores
                )
            logger.warning(
                "delegation router: model-assisted classification "
                "failed or returned no valid role; falling back to "
                "deterministic scoring"
            )

        best = max(scores.values())
        if best <= 0:
            raise RoutingError(
                f"Could not classify task for delegation — no candidate "
                f"role matched (scores: {scores}). Name the role "
                f"explicitly via delegate(<role>, <task>)."
            )
        # Ties resolve to the earliest candidate in caller order.
        winner = next(r.name for r in candidates if scores[r.name] == best)
        logger.info(
            "delegation router: deterministic selection %r (scores: %s)",
            winner,
            scores,
        )
        return RouteDecision(sub_role=winner, method="deterministic", scores=scores)

    # ── model-assisted path ───────────────────────────────────────

    def _build_prompt(self, task: str, candidates: list[RoleConfig]) -> str:
        lines = [
            "Select the single best sub-agent role for the task below.",
            "",
            "Roles:",
        ]
        lines += [
            f"- {role.name}: {role.description or role.display_name}"
            for role in candidates
        ]
        lines += [
            "",
            f"Task: {task}",
            "",
            "Reply with exactly one role name from the list, nothing else.",
        ]
        return "\n".join(lines)

    async def _classify_with_model(
        self, task: str, candidates: list[RoleConfig]
    ) -> str | None:
        """Model-assisted classification; ``None`` on ANY failure.

        Every failure mode — model resolution, guardrail/budget denial,
        transport error, or a reply naming no candidate — degrades to
        the deterministic path (design: the router must never make
        delegation less available than it was before P12).
        """
        try:
            invoker = self._model_invoker or self._default_invoker
            reply = await invoker(self._build_prompt(task, candidates))
        except Exception:
            logger.warning(
                "delegation router: model invocation failed",
                exc_info=True,
            )
            return None
        return _parse_role_reply(reply, candidates)

    async def _default_invoker(self, prompt: str) -> str:
        """Resolve + bind the ``router``-bound model and invoke it once.

        Walks the bound fallback chain like the harnesses do; binding
        goes through ``bind_langchain`` so credential resolution stays
        on the CredentialProvider seam and every call is budget-gated
        via ``check_model_call`` (P19).
        """
        from assistant.core.capabilities.model_bindings import bind_langchain
        from assistant.core.capabilities.models import (
            ModelRequest,
            RegistryModelProvider,
        )

        provider = RegistryModelProvider(self.persona.models)
        refs = provider.resolve(ModelRequest(consumer=ROUTER_CONSUMER))
        last_exc: Exception | None = None
        for ref in refs:
            try:
                model = bind_langchain(
                    ref,
                    credentials=getattr(self.persona, "credentials", None),
                    guardrails=self._guardrails,
                    persona=self.persona.name,
                    role=ROUTER_CONSUMER,
                )
                response = await model.ainvoke(prompt)
                return _response_text(response)
            except Exception as exc:
                last_exc = exc
                continue
        raise RuntimeError(
            "Every ModelRef in the router-bound chain failed."
        ) from last_exc


def _response_text(response: Any) -> str:
    """Extract text from a LangChain message-like or plain response."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _parse_role_reply(reply: str, candidates: list[RoleConfig]) -> str | None:
    """Map a model reply onto a candidate role name.

    Exact (case-insensitive, stripped) match first; then a substring
    scan in candidate order. Anything else is invalid → ``None``.
    """
    text = reply.strip().lower()
    if not text:
        return None
    for role in candidates:
        if text == role.name.lower():
            return role.name
    for role in candidates:
        if role.name.lower() in text:
            return role.name
    return None


__all__ = [
    "ROUTER_CONSUMER",
    "DelegationRouter",
    "RouteDecision",
    "RoutingError",
    "score_role",
]
