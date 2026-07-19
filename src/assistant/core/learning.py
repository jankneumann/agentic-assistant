"""Continual-learning pipeline — P28 continual-learning.

Memory that grows, behind a source-agnostic feedback abstraction:

    FeedbackEvent (human | machine collectors)
        → stored feedback (interactions table, metadata source=feedback)
        → reflection/consolidation (interactions → provenance-stamped
          facts + Graphiti episodes)
        → ImprovementProposal files (reviewable diffs in the persona
          dir — the persona submodule IS the approval workflow)
        → eval-gated, guardrail-gated apply

Design pillars (see openspec/changes/continual-learning/design.md):

- **No config, no learning.** A persona without a truthy ``learning:``
  section can neither record feedback, nor reflect, nor propose, nor
  apply — the feature is dormant by default (clean-room posture, P26).
- **Self-improvement is propose → eval → human-approved diff, NEVER
  self-merge** (roadmap constraint, P27/P28). Proposals are written as
  files under the persona's ``proposals/`` directory; nothing is
  applied automatically EXCEPT ``kind=preference`` proposals with
  ``risk=LOW`` when the persona opts in via
  ``learning.auto_apply_low_risk: true`` — and even that path is gated
  through ``check_action(action_type="learning_apply")`` and the P27
  eval gate.
- **Machine collectors read what already exists** — the eval gate's
  output, the guardrail spend ledger, the resilience breaker registry,
  and model-registry pricing metadata. They run on demand (CLI) or as
  scheduler jobs; no new daemons.
- **Risk is tiered by proposal kind** (``RiskLevel`` vocabulary):
  ``preference`` = LOW, ``prompt_layer`` = MEDIUM, ``routing_config``
  = HIGH. Higher tiers require the explicit operator ``--approved``
  flag — the interim human seam until the P30 durable-session approval
  interrupt lands. ``require_confirmation`` DENIES (P13 semantics).
- **Audit**: every op emits a ``learning.<op>`` span through the
  telemetry ``start_span`` escape hatch, identity-stamped (P25/P26
  precedent). Memory writes ride the existing ``trace_memory_op``
  vocabulary (``fact_write`` / ``preference_write`` /
  ``interaction_write`` / ``episode_write``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from assistant.core.capabilities.audit import emit_guardrail_audit
from assistant.core.capabilities.guardrails import (
    GuardrailProvider,
    _day_start,
    _month_start,
    budget_ledger_for,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.types import ActionRequest, RiskLevel

if TYPE_CHECKING:
    from assistant.core.persona import PersonaConfig

logger = logging.getLogger(__name__)


# ── Errors ─────────────────────────────────────────────────────────────


class LearningError(Exception):
    """Base class for continual-learning failures."""


class LearningConfigError(LearningError, ValueError):
    """A persona ``learning:`` section failed validation at load time."""


class LearningDenied(LearningError):
    """A learning operation was refused (config, guardrail, gate, risk)."""


class ProposalError(LearningError):
    """An improvement-proposal file is malformed or unusable."""


# ── Configuration (persona ``learning:`` section) ─────────────────────

#: Default ``models:`` bindings key the reflection summarizer resolves
#: under — the reserved ``memory`` consumer documented in P20 (an
#: unbound consumer falls back to the ``default`` binding).
DEFAULT_REFLECTION_CONSUMER = "memory"

#: Default proposals directory name inside the persona directory.
PROPOSALS_DIR_NAME = "proposals"

_CONFIG_KEYS = frozenset(
    {"enabled", "auto_apply_low_risk", "reflection", "proposals_dir"}
)
_REFLECTION_KEYS = frozenset({"consumer"})


@dataclass
class LearningConfig:
    """Parsed persona ``learning:`` section.

    Falsy (the default) when the persona declares no learning section
    (or sets ``enabled: false``) — every learning entry point then
    refuses, keeping the feature fully dormant (clean-room posture).
    """

    enabled: bool = False
    auto_apply_low_risk: bool = False
    reflection_consumer: str = DEFAULT_REFLECTION_CONSUMER
    proposals_dir: Path | None = None

    def __bool__(self) -> bool:
        return self.enabled


def parse_learning_config(
    raw: Any, *, persona_dir: Path | None = None
) -> LearningConfig:
    """Parse and validate a persona ``learning:`` section.

    Actionable-error posture (same as ``guardrails:`` / ``clean_room:``):
    unknown keys and mis-typed values fail with
    :class:`LearningConfigError` naming the offender, surfaced by
    persona load. ``None``/``{}`` yields the falsy default config. A
    present section defaults ``enabled`` to ``true``.
    """
    if not raw:
        return LearningConfig()
    if not isinstance(raw, dict):
        raise LearningConfigError(
            f"learning: expected a mapping, got {type(raw).__name__}."
        )
    unknown = sorted(set(raw) - _CONFIG_KEYS)
    if unknown:
        raise LearningConfigError(
            f"learning: unknown keys {unknown}. Allowed: "
            f"{sorted(_CONFIG_KEYS)}."
        )
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise LearningConfigError(
            f"learning: 'enabled' must be a boolean, got {enabled!r}."
        )
    auto_apply = raw.get("auto_apply_low_risk", False)
    if not isinstance(auto_apply, bool):
        raise LearningConfigError(
            f"learning: 'auto_apply_low_risk' must be a boolean, got "
            f"{auto_apply!r}."
        )
    consumer = DEFAULT_REFLECTION_CONSUMER
    raw_reflection = raw.get("reflection")
    if raw_reflection is not None:
        if not isinstance(raw_reflection, dict):
            raise LearningConfigError(
                f"learning: 'reflection' must be a mapping, got "
                f"{type(raw_reflection).__name__}."
            )
        unknown_r = sorted(set(raw_reflection) - _REFLECTION_KEYS)
        if unknown_r:
            raise LearningConfigError(
                f"learning: reflection has unknown keys {unknown_r}. "
                f"Allowed: {sorted(_REFLECTION_KEYS)}."
            )
        consumer = raw_reflection.get("consumer", DEFAULT_REFLECTION_CONSUMER)
        if not isinstance(consumer, str) or not consumer:
            raise LearningConfigError(
                "learning: reflection.consumer must be a non-empty "
                "models bindings key."
            )
    proposals_raw = raw.get("proposals_dir")
    proposals_dir: Path | None = None
    if proposals_raw is not None:
        if not isinstance(proposals_raw, str) or not proposals_raw:
            raise LearningConfigError(
                "learning: proposals_dir must be a non-empty path string."
            )
        proposals_dir = Path(proposals_raw)
    elif persona_dir is not None:
        proposals_dir = Path(persona_dir) / PROPOSALS_DIR_NAME

    return LearningConfig(
        enabled=enabled,
        auto_apply_low_risk=auto_apply,
        reflection_consumer=consumer,
        proposals_dir=proposals_dir,
    )


def require_learning(persona: PersonaConfig) -> LearningConfig:
    """Return the persona's truthy learning config, or refuse.

    Every learning entry point calls this first: no config (or
    ``enabled: false``) means the whole feature is dormant — even the
    read-only collectors refuse, mirroring the clean-room "no config,
    no sharing" posture (recorded design decision).
    """
    config: LearningConfig = getattr(
        persona, "learning", None
    ) or LearningConfig()
    if not config:
        raise LearningDenied(
            f"persona {persona.name!r} declares no (enabled) learning: "
            f"section — continual learning is dormant by default. Add a "
            f"learning: section to persona.yaml to opt in."
        )
    return config


# ── Memory-store slice ─────────────────────────────────────────────────


@runtime_checkable
class LearningMemoryStore(Protocol):
    """Structural slice of :class:`MemoryManager` the pipeline consumes.

    A Protocol (P26 precedent) so tests inject in-memory fakes for the
    DB-bound surface; the real ``MemoryManager`` satisfies it
    structurally.
    """

    async def list_interactions(
        self, persona: str, role: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]: ...

    async def list_facts(
        self, persona: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    async def store_fact(self, persona: str, key: str, value: Any) -> None: ...

    async def store_interaction(
        self,
        persona: str,
        role: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def store_preference(
        self,
        persona: str,
        category: str,
        key: str,
        value: Any,
        confidence: float = 0.5,
    ) -> None: ...

    async def store_episode(
        self, persona: str, content: str, source: str
    ) -> None: ...


# ── Audit spans ────────────────────────────────────────────────────────

LEARNING_FEEDBACK_SPAN = "learning.feedback"
LEARNING_REFLECT_SPAN = "learning.reflect"
LEARNING_PROPOSE_SPAN = "learning.propose"
LEARNING_APPLY_SPAN = "learning.apply"


def _emit_learning_audit(
    span_name: str,
    attributes: dict[str, Any],
    identity: AgentIdentity | None,
) -> None:
    """Emit one learning audit span, identity-stamped when known.

    Defensive posture (P25/P26 precedent): a failing telemetry provider
    logs a WARNING and never changes the pipeline outcome.
    """
    attrs: dict[str, Any] = dict(attributes)
    if identity is not None:
        attrs.update(
            {
                "persona": identity.persona,
                "role": identity.role,
                "delegation_chain": list(identity.delegation_chain),
                "chain_depth": identity.chain_depth,
                "session_id": identity.session_id,
                "issued_at": identity.issued_at.isoformat(),
            }
        )
    try:
        from assistant.telemetry import get_observability_provider

        with get_observability_provider().start_span(
            span_name, attributes=attrs
        ):
            pass
    except Exception as exc:
        logger.warning(
            "learning audit record not emitted (%s); pipeline outcome "
            "is unaffected",
            type(exc).__name__,
        )


# ── FeedbackEvent ──────────────────────────────────────────────────────

#: Closed source vocabulary for feedback events.
FEEDBACK_SOURCES = (
    "human",
    "eval",
    "guardrail",
    "resilience",
    "cost",
    "critique",
)

#: interactions.metadata marker distinguishing stored feedback rows.
FEEDBACK_METADATA_SOURCE = "feedback"


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class FeedbackEvent:
    """One source-agnostic feedback signal.

    ``subject`` names what the feedback is about (a role, a persona, a
    config path such as ``models.entries.sonnet``, a scenario file);
    ``signal`` carries the score/verdict/text; ``context`` is an
    optional reference (file path, breaker key, ledger path);
    ``data`` carries optional structured payloads (e.g. a distilled
    preference); ``identity`` is the serialized acting principal.
    """

    source: str
    subject: str
    signal: str
    context: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=_utcnow_iso)
    identity: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.source not in FEEDBACK_SOURCES:
            raise ValueError(
                f"FeedbackEvent source {self.source!r} is not one of "
                f"{list(FEEDBACK_SOURCES)}."
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "subject": self.subject,
            "signal": self.signal,
            "context": self.context,
            "data": self.data,
            "created_at": self.created_at,
            "identity": self.identity,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FeedbackEvent:
        return cls(
            source=str(payload.get("source", "")),
            subject=str(payload.get("subject", "")),
            signal=str(payload.get("signal", "")),
            context=str(payload.get("context", "") or ""),
            data=dict(payload.get("data") or {}),
            event_id=str(payload.get("event_id") or uuid.uuid4().hex),
            created_at=str(payload.get("created_at") or _utcnow_iso()),
            identity=payload.get("identity"),
        )


def identity_payload(identity: AgentIdentity) -> dict[str, Any]:
    return {
        "persona": identity.persona,
        "role": identity.role,
        "delegation_chain": list(identity.delegation_chain),
        "session_id": identity.session_id,
        "issued_at": identity.issued_at.isoformat(),
    }


async def record_feedback(
    persona: PersonaConfig,
    manager: LearningMemoryStore,
    event: FeedbackEvent,
    *,
    identity: AgentIdentity | None = None,
) -> None:
    """Persist one feedback event via the interactions table.

    Stored with ``metadata.source = "feedback"`` plus the full event
    payload, so :func:`list_feedback` can round-trip it and ordinary
    interaction consumers (snippets, eval export) see a labeled row
    rather than opaque noise. Refuses when learning is dormant.
    """
    require_learning(persona)
    if identity is None:
        identity = AgentIdentity(
            persona=persona.name, role=getattr(persona, "default_role", "")
        )
    if event.identity is None:
        event.identity = identity_payload(identity)
    summary = f"[feedback:{event.source}] {event.subject}: {event.signal}"
    await manager.store_interaction(
        persona.name,
        identity.role or getattr(persona, "default_role", ""),
        summary[:480],
        metadata={
            "source": FEEDBACK_METADATA_SOURCE,
            "feedback": event.to_payload(),
        },
    )
    _emit_learning_audit(
        LEARNING_FEEDBACK_SPAN,
        {
            "event_id": event.event_id,
            "feedback_source": event.source,
            "subject": event.subject,
            "outcome": "recorded",
        },
        identity,
    )


async def list_feedback(
    persona: PersonaConfig,
    manager: LearningMemoryStore,
    *,
    limit: int = 100,
) -> list[FeedbackEvent]:
    """Return stored feedback events, newest first."""
    require_learning(persona)
    events: list[FeedbackEvent] = []
    for row in await manager.list_interactions(persona.name, limit=limit):
        metadata = row.get("metadata") or {}
        if metadata.get("source") != FEEDBACK_METADATA_SOURCE:
            continue
        payload = metadata.get("feedback")
        if not isinstance(payload, dict):
            continue
        try:
            events.append(FeedbackEvent.from_payload(payload))
        except ValueError:
            logger.warning(
                "skipping malformed stored feedback event (interaction "
                "id=%s)",
                row.get("id"),
            )
    return events


# ── Machine collectors ─────────────────────────────────────────────────
#
# Collectors READ what already exists — no new stores, no new daemons.
# Each returns plain FeedbackEvents; callers decide whether to print,
# store (record_feedback), or feed them straight into derive_proposals.

#: Budget utilization (spent / ceiling) at which the guardrail
#: collector starts emitting feedback.
BUDGET_ALERT_UTILIZATION = 0.8

_GATE_FAIL_RE = re.compile(r"eval-gate: FAIL — (?P<what>.+?)(?:\s*$)")
_GATE_SKIP_RE = re.compile(r"eval-gate: SKIP — (?P<why>.+?)(?:\s*$)")
_GATE_PASS_RE = re.compile(r"eval-gate: PASS")


def collect_eval_feedback(gate_output: str) -> list[FeedbackEvent]:
    """Parse P27 eval-gate output into feedback events.

    Consumes the text `evaluation/run-gate.sh` prints (captured live by
    :func:`run_eval_gate`, or read from a saved log file): each
    ``eval-gate: FAIL — <scenario>`` line becomes one failing event;
    a ``SKIP`` line becomes an advisory event; a ``PASS`` line becomes
    one passing event.
    """
    events: list[FeedbackEvent] = []
    for line in gate_output.splitlines():
        fail = _GATE_FAIL_RE.search(line)
        if fail:
            events.append(
                FeedbackEvent(
                    source="eval",
                    subject=fail.group("what").strip(),
                    signal="fail",
                    context="evaluation/run-gate.sh",
                )
            )
            continue
        skip = _GATE_SKIP_RE.search(line)
        if skip:
            events.append(
                FeedbackEvent(
                    source="eval",
                    subject="eval-gate",
                    signal="skip",
                    context=skip.group("why").strip(),
                )
            )
            continue
        if _GATE_PASS_RE.search(line):
            events.append(
                FeedbackEvent(
                    source="eval",
                    subject="eval-gate",
                    signal="pass",
                    context="evaluation/run-gate.sh",
                )
            )
    return events


def collect_guardrail_feedback(
    persona: PersonaConfig, *, now: datetime | None = None
) -> list[FeedbackEvent]:
    """Budget-pressure feedback from the P13 spend ledger.

    Reads the persona's model-call budget ceilings and the process
    ledger (file-backed when ``persist: file``) and emits one event per
    window whose utilization is at or above
    :data:`BUDGET_ALERT_UTILIZATION`. No guardrails / no budget = no
    events.
    """
    config = getattr(persona, "guardrails", None)
    budget = getattr(config, "model_call_budget", None)
    if config is None or budget is None:
        return []
    ledger = budget_ledger_for(persona.name, config)
    now = now or datetime.now(UTC)
    events: list[FeedbackEvent] = []
    for label, ceiling, since in (
        ("daily", budget.daily_usd, _day_start(now)),
        ("monthly", budget.monthly_usd, _month_start(now)),
    ):
        if ceiling <= 0:
            continue
        spent = ledger.spent_since(since)
        utilization = spent / ceiling
        if utilization >= BUDGET_ALERT_UTILIZATION:
            events.append(
                FeedbackEvent(
                    source="guardrail",
                    subject=f"guardrails.budgets.model_call.{label}",
                    signal=(
                        f"spent ${spent:.4f} of ${ceiling:.2f} "
                        f"({utilization:.0%})"
                    ),
                    context="spend-ledger",
                    data={
                        "spent_usd": spent,
                        "ceiling_usd": ceiling,
                        "window": label,
                    },
                )
            )
    return events


def collect_resilience_feedback() -> list[FeedbackEvent]:
    """Circuit-breaker health feedback from the P9 breaker registry.

    Emits one event per breaker that is not ``closed`` or carries
    consecutive failures — a degraded upstream is a learning signal
    (e.g. "route around this tool source").
    """
    from assistant.core.resilience import get_circuit_breaker_registry

    events: list[FeedbackEvent] = []
    registry = get_circuit_breaker_registry()
    for key, breaker in sorted(registry.breakers().items()):
        state = breaker.state
        failures = breaker.consecutive_failures
        if state == "closed" and failures == 0:
            continue
        events.append(
            FeedbackEvent(
                source="resilience",
                subject=key,
                signal=f"breaker {state} ({failures} consecutive failures)",
                context=str(breaker.last_error or ""),
                data={"state": state, "consecutive_failures": failures},
            )
        )
    return events


def collect_cost_feedback(persona: PersonaConfig) -> list[FeedbackEvent]:
    """Cost-anomaly feedback: budgeted personas with spend blind spots.

    When a model-call budget is configured, every registry entry
    without pricing metadata (and no catalog inheritance) is invisible
    to the spend ledger unless ``default_call_cost_usd`` covers it —
    flag each such entry so the owner syncs the catalog or declares
    pricing.
    """
    config = getattr(persona, "guardrails", None)
    budget = getattr(config, "model_call_budget", None)
    if budget is None:
        return []
    if budget.default_call_cost_usd > 0:
        return []
    models = getattr(persona, "models", None)
    entries = getattr(models, "entries", {}) or {}
    events: list[FeedbackEvent] = []
    for name, ref in entries.items():
        if getattr(ref, "pricing", None):
            continue
        if getattr(ref, "endpoint", ""):
            # Local endpoints legitimately have no pricing.
            continue
        events.append(
            FeedbackEvent(
                source="cost",
                subject=f"models.entries.{name}",
                signal=(
                    "no pricing metadata while a model_call budget is "
                    "configured — spend is invisible; run `assistant "
                    "models sync-catalog` or set default_call_cost_usd"
                ),
                context="model-registry",
            )
        )
    return events


def collect_machine_feedback(
    persona: PersonaConfig,
    *,
    gate_output: str | None = None,
    now: datetime | None = None,
) -> list[FeedbackEvent]:
    """Aggregate all machine collectors (on demand — no new daemons)."""
    require_learning(persona)
    events: list[FeedbackEvent] = []
    if gate_output:
        events.extend(collect_eval_feedback(gate_output))
    events.extend(collect_guardrail_feedback(persona, now=now))
    events.extend(collect_resilience_feedback())
    events.extend(collect_cost_feedback(persona))
    return events


# ── Reflection / consolidation ─────────────────────────────────────────

#: Key prefix for consolidated reflection facts.
REFLECTION_KEY_PREFIX = "learning/reflection/"

#: Fact key tracking the newest interaction timestamp already
#: consolidated, so repeated reflections never re-consolidate.
LAST_REFLECTION_KEY = "learning/last_reflection"

#: Character budget for the heuristic (model-less) consolidation digest.
_HEURISTIC_DIGEST_CHARS = 2000


@dataclass
class ReflectionResult:
    fact_key: str
    summary: str
    interaction_count: int
    used_model: bool


async def _default_summarizer(
    persona: PersonaConfig,
    guardrails: GuardrailProvider,
    consumer: str,
    lines: list[str],
) -> str | None:
    """Model-backed consolidation under the reflection consumer binding.

    Resolves the persona ``models:`` registry under ``consumer`` (the
    reserved ``memory`` key by default; an unbound consumer falls back
    to the ``default`` binding) and calls the first resolvable
    ``openai-compatible`` endpoint through the budget-gated
    :class:`OpenAICompatibleClient`. Returns ``None`` when no entry in
    the chain is dispatchable this way — the caller then degrades to
    the deterministic heuristic digest (recorded limitation: raw
    non-OpenAI-compatible dialects have no harness-free client yet).
    """
    from assistant.core.capabilities.model_bindings import (
        ModelCallDeniedError,
        OpenAICompatibleClient,
    )
    from assistant.core.capabilities.models import (
        ModelRequest,
        RegistryModelProvider,
        default_model_registry,
    )

    registry = getattr(persona, "models", None)
    provider = RegistryModelProvider(
        registry if registry else default_model_registry()
    )
    try:
        refs = provider.resolve(ModelRequest(consumer=consumer))
    except Exception as exc:
        logger.warning(
            "reflection: model resolution failed under consumer %r "
            "(%s); using heuristic digest",
            consumer,
            type(exc).__name__,
        )
        return None
    prompt = (
        "Consolidate the following assistant interaction summaries into "
        "a short list of durable facts and preferences about the user "
        "and their ongoing work. Be concise; output plain text.\n\n"
        + "\n".join(lines)
    )
    for ref in refs:
        if ref.dialect != "openai-compatible" or not ref.endpoint:
            continue
        client = OpenAICompatibleClient(
            ref,
            credentials=getattr(persona, "credentials", None),
            guardrails=guardrails,
            persona=persona.name,
            role="learning",
        )
        try:
            response = await client.chat(
                [{"role": "user", "content": prompt}]
            )
            content = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if content:
                return str(content)
        except ModelCallDeniedError:
            raise
        except Exception as exc:
            logger.warning(
                "reflection: summarization via %r failed (%s); trying "
                "next entry",
                ref.name,
                type(exc).__name__,
            )
    return None


def _heuristic_digest(lines: list[str]) -> str:
    """Deterministic model-less consolidation: a bounded digest."""
    header = f"Consolidated {len(lines)} recent interaction(s):"
    body = "\n".join(f"- {line}" for line in lines)
    return (header + "\n" + body)[:_HEURISTIC_DIGEST_CHARS]


async def run_reflection(
    persona: PersonaConfig,
    manager: LearningMemoryStore,
    *,
    guardrails: GuardrailProvider,
    identity: AgentIdentity | None = None,
    summarizer: Any | None = None,
    limit: int = 50,
    now: datetime | None = None,
) -> ReflectionResult | None:
    """Consolidate recent interactions into a provenance-stamped fact.

    Reads the newest ``limit`` interactions, drops the ones already
    consolidated (tracked via :data:`LAST_REFLECTION_KEY`), summarizes
    them — model-backed under the reflection consumer binding when an
    ``openai-compatible`` entry resolves, deterministic digest
    otherwise — and stores the result as a
    ``learning/reflection/<timestamp>`` fact with ``source=reflection``
    provenance. Also writes the summary back as a Graphiti episode
    where configured (``store_episode`` degrades gracefully without a
    graph — this closes the deferred P21 episode write-back cheaply).
    Returns ``None`` when there is nothing new to consolidate.
    """
    config = require_learning(persona)
    if identity is None:
        identity = AgentIdentity(
            persona=persona.name, role=getattr(persona, "default_role", "")
        )

    last_until = ""
    for fact in await manager.list_facts(persona.name, limit=200):
        if fact.get("key") == LAST_REFLECTION_KEY:
            value = fact.get("value") or {}
            if isinstance(value, dict):
                last_until = str(value.get("until", "") or "")
            break

    interactions = await manager.list_interactions(persona.name, limit=limit)
    new: list[dict[str, Any]] = []
    for row in interactions:
        created = str(row.get("created_at") or "")
        if last_until and created and created <= last_until:
            continue
        new.append(row)
    if not new:
        return None

    lines = [
        f"[{row.get('role', '?')}] {row.get('summary', '')}" for row in new
    ]
    summary: str | None = None
    used_model = False
    if summarizer is not None:
        summary = await summarizer(lines)
        used_model = summary is not None
    else:
        summary = await _default_summarizer(
            persona, guardrails, config.reflection_consumer, lines
        )
        used_model = summary is not None
    if not summary:
        summary = _heuristic_digest(lines)
        used_model = False

    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    fact_key = f"{REFLECTION_KEY_PREFIX}{stamp}-{uuid.uuid4().hex[:8]}"
    consolidated_at = (now or datetime.now(UTC)).isoformat()
    await manager.store_fact(
        persona.name,
        fact_key,
        {
            "summary": summary,
            "provenance": {
                "source": "reflection",
                "interaction_ids": [row.get("id") for row in new],
                "interaction_count": len(new),
                "consolidated_at": consolidated_at,
                "used_model": used_model,
                "reflected_by": identity_payload(identity),
            },
        },
    )
    # Graphiti episode write-back where configured (store_episode
    # no-ops with a warning when no graph client exists).
    await manager.store_episode(persona.name, summary, source="reflection")

    newest = max(
        (str(row.get("created_at") or "") for row in new), default=""
    )
    if newest:
        await manager.store_fact(
            persona.name,
            LAST_REFLECTION_KEY,
            {"until": newest, "updated_at": consolidated_at},
        )

    _emit_learning_audit(
        LEARNING_REFLECT_SPAN,
        {
            "fact_key": fact_key,
            "interaction_count": len(new),
            "used_model": used_model,
            "outcome": "consolidated",
        },
        identity,
    )
    return ReflectionResult(
        fact_key=fact_key,
        summary=summary,
        interaction_count=len(new),
        used_model=used_model,
    )


def _learning_memory_manager(persona: PersonaConfig) -> Any:
    """Build the real MemoryManager for scheduler/CLI reflection runs.

    Module-level seam so tests patch ONE symbol
    (``assistant.core.learning._learning_memory_manager``) instead of
    the db/graphiti factory stack (docs/gotchas.md G4).
    """
    if not getattr(persona, "database_url", ""):
        raise LearningError(
            f"persona {persona.name!r} has no database_url configured — "
            f"reflection needs the persona's memory database."
        )
    from assistant.core.db import async_session_factory, create_async_engine
    from assistant.core.graphiti import create_graphiti_client
    from assistant.core.memory import MemoryManager

    engine = create_async_engine(persona)
    session_fac = async_session_factory(engine)
    graphiti = create_graphiti_client(persona)
    return MemoryManager(session_fac, graphiti_client=graphiti)


async def run_reflection_for_persona(persona: PersonaConfig) -> str:
    """Scheduler-facing reflection entry point (P7 ``kind: reflect`` jobs).

    Builds the persona's MemoryManager and guardrails, runs one
    reflection pass, and returns a human-readable one-liner for the
    job log.
    """
    from assistant.core.cleanroom import select_guardrails

    require_learning(persona)
    manager = _learning_memory_manager(persona)
    result = await run_reflection(
        persona,
        manager,
        guardrails=select_guardrails(persona),
        identity=AgentIdentity(
            persona=persona.name, role=getattr(persona, "default_role", "")
        ),
    )
    if result is None:
        return "reflection: nothing new to consolidate"
    return (
        f"reflection: consolidated {result.interaction_count} "
        f"interaction(s) into {result.fact_key}"
    )


# ── Improvement proposals ──────────────────────────────────────────────

PROPOSAL_KINDS = ("prompt_layer", "preference", "routing_config")

#: Deterministic kind → risk tiering. Preferences only touch the
#: persona's own memory (reversible); prompt-layer edits change agent
#: behavior (reviewable file diff); routing/config edits change
#: execution topology and spend (always human-applied).
RISK_BY_KIND: dict[str, RiskLevel] = {
    "preference": RiskLevel.LOW,
    "prompt_layer": RiskLevel.MEDIUM,
    "routing_config": RiskLevel.HIGH,
}

PROPOSAL_FORMAT = "learning-proposal"
PROPOSAL_VERSION = 1


@dataclass
class ImprovementProposal:
    """One reviewable improvement, written as a file under the persona
    dir's ``proposals/`` directory (the submodule IS the approval
    workflow)."""

    proposal_id: str
    kind: str
    target: str
    content: Any
    rationale: str
    risk: str
    provenance: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utcnow_iso)
    status: str = "proposed"
    applied_at: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in PROPOSAL_KINDS:
            raise ProposalError(
                f"proposal kind {self.kind!r} is not one of "
                f"{list(PROPOSAL_KINDS)}."
            )
        if self.risk not in RiskLevel.__members__:
            raise ProposalError(
                f"proposal risk {self.risk!r} is not one of "
                f"{list(RiskLevel.__members__)}."
            )

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel[self.risk]

    def to_payload(self) -> dict[str, Any]:
        return {
            "format": PROPOSAL_FORMAT,
            "version": PROPOSAL_VERSION,
            "proposal_id": self.proposal_id,
            "kind": self.kind,
            "target": self.target,
            "content": self.content,
            "rationale": self.rationale,
            "risk": self.risk,
            "provenance": list(self.provenance),
            "created_at": self.created_at,
            "status": self.status,
            "applied_at": self.applied_at,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> ImprovementProposal:
        if not isinstance(payload, dict):
            raise ProposalError(
                f"proposal payload must be a JSON object, got "
                f"{type(payload).__name__}."
            )
        if payload.get("format") != PROPOSAL_FORMAT:
            raise ProposalError(
                f"proposal format {payload.get('format')!r} is not "
                f"{PROPOSAL_FORMAT!r}."
            )
        if payload.get("version") != PROPOSAL_VERSION:
            raise ProposalError(
                f"proposal version {payload.get('version')!r} is not "
                f"supported (expected {PROPOSAL_VERSION})."
            )
        return cls(
            proposal_id=str(payload.get("proposal_id") or uuid.uuid4().hex),
            kind=str(payload.get("kind", "")),
            target=str(payload.get("target", "")),
            content=payload.get("content"),
            rationale=str(payload.get("rationale", "")),
            risk=str(payload.get("risk", "")),
            provenance=[str(x) for x in payload.get("provenance") or []],
            created_at=str(payload.get("created_at") or _utcnow_iso()),
            status=str(payload.get("status", "proposed")),
            applied_at=payload.get("applied_at"),
        )


def resolve_proposals_dir(persona: PersonaConfig) -> Path:
    config = require_learning(persona)
    if config.proposals_dir is None:
        raise LearningError(
            f"persona {persona.name!r} has no resolvable proposals "
            f"directory — set learning.proposals_dir (or load the "
            f"persona through the registry so the default "
            f"<persona_dir>/{PROPOSALS_DIR_NAME} applies)."
        )
    return config.proposals_dir


def proposal_path(proposals_dir: Path, proposal_id: str) -> Path:
    return proposals_dir / f"{proposal_id}.json"


def write_proposal(
    proposals_dir: Path, proposal: ImprovementProposal
) -> Path:
    path = proposal_path(proposals_dir, proposal.proposal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(proposal.to_payload(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_proposal(path: Path) -> ImprovementProposal:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProposalError(
            f"cannot read proposal at {path}: {type(exc).__name__}: {exc}"
        ) from exc
    return ImprovementProposal.from_payload(payload)


def list_proposals(proposals_dir: Path) -> list[ImprovementProposal]:
    if not proposals_dir.is_dir():
        return []
    proposals: list[ImprovementProposal] = []
    for path in sorted(proposals_dir.glob("*.json")):
        try:
            proposals.append(load_proposal(path))
        except ProposalError as exc:
            logger.warning("skipping unreadable proposal %s: %s", path, exc)
    return proposals


def derive_proposals(
    persona: PersonaConfig,
    events: list[FeedbackEvent],
    *,
    identity: AgentIdentity | None = None,
) -> list[ImprovementProposal]:
    """Turn feedback events into improvement proposals (deterministic).

    Mapping rules (one proposal per distinct ``(kind, target)``,
    provenance merged):

    - ``human`` events carrying a structured ``data["preference"]``
      payload → ``preference`` proposal (LOW) — the distillation path.
    - other ``human`` / ``critique`` events → ``prompt_layer``
      suggestion (MEDIUM) targeting the subject role's persona
      override prompt (``roles/<role>.md``) or the persona prompt
      layer (``prompt.md``).
    - ``eval`` failures → ``prompt_layer`` suggestion (MEDIUM)
      targeting ``prompt.md``, rationale naming the scenario.
    - ``guardrail`` / ``cost`` / ``resilience`` events →
      ``routing_config`` proposal (HIGH) targeting the persona
      ``models:``/``guardrails:`` config — always human-applied.
    """
    require_learning(persona)
    merged: dict[tuple[str, str], ImprovementProposal] = {}

    def _add(
        kind: str,
        target: str,
        content: Any,
        rationale: str,
        event: FeedbackEvent,
    ) -> None:
        key = (kind, target)
        existing = merged.get(key)
        if existing is not None:
            existing.provenance.append(event.event_id)
            existing.rationale = f"{existing.rationale}\n{rationale}"
            return
        merged[key] = ImprovementProposal(
            proposal_id=uuid.uuid4().hex,
            kind=kind,
            target=target,
            content=content,
            rationale=rationale,
            risk=RISK_BY_KIND[kind].name,
            provenance=[event.event_id],
        )

    for event in events:
        if event.source == "human" and isinstance(
            event.data.get("preference"), dict
        ):
            pref = event.data["preference"]
            category = str(pref.get("category", "general") or "general")
            key = str(pref.get("key", "") or "")
            if not key:
                logger.warning(
                    "skipping preference feedback %s without a key",
                    event.event_id,
                )
                continue
            _add(
                "preference",
                f"preference:{category}/{key}",
                {
                    "category": category,
                    "key": key,
                    "value": pref.get("value"),
                    "confidence": float(pref.get("confidence", 0.6)),
                },
                f"Distilled from human feedback: {event.signal}",
                event,
            )
        elif event.source in ("human", "critique"):
            role = (
                event.subject.removeprefix("role:")
                if event.subject.startswith("role:")
                else ""
            )
            target = f"roles/{role}.md" if role else "prompt.md"
            _add(
                "prompt_layer",
                target,
                (
                    f"<!-- learning suggestion ({event.source}) -->\n"
                    f"{event.signal}"
                ),
                f"{event.source} feedback on {event.subject}: "
                f"{event.signal}",
                event,
            )
        elif event.source == "eval" and event.signal == "fail":
            _add(
                "prompt_layer",
                "prompt.md",
                (
                    "<!-- learning suggestion (eval failure) -->\n"
                    f"Address the failing eval scenario: {event.subject}"
                ),
                f"Eval gate failure: {event.subject}",
                event,
            )
        elif event.source in ("guardrail", "cost", "resilience"):
            _add(
                "routing_config",
                "persona.yaml",
                (
                    "Review the persona models:/guardrails: config — "
                    f"{event.subject}: {event.signal}"
                ),
                f"{event.source} signal on {event.subject}: {event.signal}",
                event,
            )

    proposals = list(merged.values())
    if proposals:
        _emit_learning_audit(
            LEARNING_PROPOSE_SPAN,
            {
                "proposal_count": len(proposals),
                "kinds": sorted({p.kind for p in proposals}),
                "outcome": "proposed",
            },
            identity,
        )
    return proposals


# ── Eval gate (P27 integration) ────────────────────────────────────────

#: Env var overriding the gate script location.
EVAL_GATE_SCRIPT_ENV = "EVAL_GATE_SCRIPT"

_DEFAULT_GATE_SCRIPT = Path("evaluation/run-gate.sh")


@dataclass
class GateResult:
    passed: bool
    skipped: bool
    output: str


def run_eval_gate(script: Path | None = None) -> GateResult:
    """Run the P27 eval gate and classify the outcome.

    Exit 0 with a ``SKIP`` line counts as pass-with-warning (G7-style
    semantics — the gate is advisory on machines without the tools-repo
    checkout; ``EVAL_GATE_REQUIRE=1`` upstream makes that fatal).
    A missing script is a SKIP too (same availability condition).
    """
    script = script or Path(
        os.environ.get(EVAL_GATE_SCRIPT_ENV, "") or _DEFAULT_GATE_SCRIPT
    )
    if not script.is_file():
        return GateResult(
            passed=True,
            skipped=True,
            output=f"eval-gate: SKIP — gate script not found at {script}.",
        )
    try:
        completed = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateResult(
            passed=False,
            skipped=False,
            output=f"eval-gate: FAIL — could not run {script}: {exc}",
        )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        return GateResult(passed=False, skipped=False, output=output)
    skipped = "eval-gate: SKIP" in output
    return GateResult(passed=True, skipped=skipped, output=output)


# ── Apply ──────────────────────────────────────────────────────────────


def _check_apply_action(
    guardrails: GuardrailProvider,
    proposal: ImprovementProposal,
    persona_name: str,
    identity: AgentIdentity | None,
    approvals: Any | None = None,
) -> None:
    """Guardrail hook for proposal application; deny raises.

    ``require_confirmation`` (P30 durable-sessions): with an
    ``approvals`` store (persona ``sessions: {durable: true}``) the
    apply SUSPENDS — a persisted ApprovalRequest is created and
    ``PendingApprovalError`` propagates; after ``assistant approvals
    approve <id>`` the retried apply consumes the approval exactly
    once. WITHOUT a store the P13 deny fallback is preserved
    (approvals need the persona DB).
    """
    action = ActionRequest(
        action_type="learning_apply",
        resource=f"{proposal.kind}:{proposal.target}",
        persona=persona_name,
        role=identity.role if identity is not None else "",
        metadata={"risk": proposal.risk, "proposal_id": proposal.proposal_id},
        identity=identity,
    )
    decision = guardrails.check_action(action)
    emit_guardrail_audit(action, decision)
    if not decision.allowed:
        raise LearningDenied(
            f"learning_apply of proposal {proposal.proposal_id} denied by "
            f"guardrails: {decision.reason or 'no reason given'}"
        )
    if decision.require_confirmation:
        if approvals is None:
            raise LearningDenied(
                f"learning_apply of proposal {proposal.proposal_id} "
                f"requires confirmation, which DENIES without a durable "
                f"approval store (sessions: {{durable: true}} + database "
                f"url — P13 fallback semantics): "
                f"{decision.reason or 'no reason given'}"
            )
        from assistant.core.capabilities.approvals import consume_or_suspend

        consume_or_suspend(
            approvals,
            action,
            decision,
            risk=guardrails.declare_risk(action),
        )


def _persona_root_for(persona: PersonaConfig) -> Path:
    """Persona directory a prompt_layer target resolves under."""
    config = require_learning(persona)
    if config.proposals_dir is not None:
        return config.proposals_dir.parent
    raise LearningError(
        f"persona {persona.name!r}: cannot resolve the persona directory "
        f"for prompt_layer application (no proposals_dir)."
    )


def _apply_prompt_layer(
    persona: PersonaConfig, proposal: ImprovementProposal, applied_at: str
) -> str:
    root = _persona_root_for(persona).resolve()
    target = (root / proposal.target).resolve()
    if not target.is_relative_to(root):
        raise LearningDenied(
            f"proposal {proposal.proposal_id} targets {proposal.target!r}, "
            f"which escapes the persona directory — refused."
        )
    block = (
        f"\n\n<!-- applied learning proposal {proposal.proposal_id} "
        f"at {applied_at} -->\n{proposal.content}\n"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(block)
    return f"appended suggestion block to {target}"


async def apply_proposal(
    persona: PersonaConfig,
    proposal: ImprovementProposal,
    manager: LearningMemoryStore | None,
    *,
    guardrails: GuardrailProvider,
    identity: AgentIdentity | None = None,
    approved: bool = False,
    gate_runner: Any | None = None,
    now: datetime | None = None,
    approvals: Any | None = None,
) -> str:
    """Apply one proposal, fully gated. Returns a description of what
    was done and stamps the proposal ``applied``.

    Gates, in order:

    1. learning enabled (dormant persona refuses);
    2. proposal not already applied;
    3. ``learning_apply`` guardrail action (deny refuses;
       ``require_confirmation`` suspends into the P30 approval flow
       when an ``approvals`` store is supplied, else refuses — P13
       fallback);
    4. the P27 eval gate MUST pass (SKIP counts as pass with a
       warning);
    5. risk tier: LOW proposals apply as-is; MEDIUM/HIGH require the
       explicit operator ``approved`` flag (the interim human seam
       until P30).

    Application by kind: ``preference`` writes through
    ``store_preference``; ``prompt_layer`` appends the suggestion
    block to the target file inside the persona directory (the diff
    stays reviewable in the submodule); ``routing_config`` is
    review-only — it always refuses machine application (recorded
    design decision: rewriting persona.yaml mechanically is riskier
    than the human applying the suggested edit).
    """
    require_learning(persona)
    if identity is None:
        identity = AgentIdentity(
            persona=persona.name, role=getattr(persona, "default_role", "")
        )
    if proposal.status == "applied":
        raise LearningDenied(
            f"proposal {proposal.proposal_id} is already applied "
            f"(at {proposal.applied_at})."
        )

    _check_apply_action(
        guardrails, proposal, persona.name, identity, approvals=approvals
    )

    gate = (gate_runner or run_eval_gate)()
    if not gate.passed:
        raise LearningDenied(
            f"proposal {proposal.proposal_id} refused: the P27 eval gate "
            f"failed — fix the failing scenarios first.\n{gate.output[-500:]}"
        )
    if gate.skipped:
        logger.warning(
            "eval gate SKIPped (gen-eval unavailable) — applying proposal "
            "%s without scenario coverage; set EVAL_GATE_REQUIRE=1 to "
            "make this fatal upstream",
            proposal.proposal_id,
        )

    if proposal.risk_level is not RiskLevel.LOW and not approved:
        raise LearningDenied(
            f"proposal {proposal.proposal_id} is {proposal.risk} risk — "
            f"pass --approved to confirm (interim human seam until the "
            f"P30 approval interrupt flow)."
        )

    applied_at = (now or datetime.now(UTC)).isoformat()
    if proposal.kind == "preference":
        if manager is None:
            raise LearningError(
                "preference proposals need the persona's memory store."
            )
        content = proposal.content if isinstance(proposal.content, dict) else {}
        category = str(content.get("category", "general") or "general")
        key = str(content.get("key", "") or "")
        if not key:
            raise ProposalError(
                f"preference proposal {proposal.proposal_id} has no "
                f"content.key."
            )
        await manager.store_preference(
            persona.name,
            category,
            key,
            content.get("value"),
            confidence=float(content.get("confidence", 0.6)),
        )
        description = f"stored preference [{category}] {key}"
    elif proposal.kind == "prompt_layer":
        description = _apply_prompt_layer(persona, proposal, applied_at)
    else:  # routing_config
        raise LearningDenied(
            f"proposal {proposal.proposal_id} is a routing_config "
            f"proposal — review-only. Apply the suggested edit to the "
            f"persona config by hand (git is the approval workflow)."
        )

    proposal.status = "applied"
    proposal.applied_at = applied_at
    _emit_learning_audit(
        LEARNING_APPLY_SPAN,
        {
            "proposal_id": proposal.proposal_id,
            "kind": proposal.kind,
            "risk": proposal.risk,
            "gate_skipped": gate.skipped,
            "approved": approved,
            "outcome": "applied",
        },
        identity,
    )
    return description


async def maybe_auto_apply(
    persona: PersonaConfig,
    proposals: list[ImprovementProposal],
    manager: LearningMemoryStore | None,
    *,
    guardrails: GuardrailProvider,
    identity: AgentIdentity | None = None,
    gate_runner: Any | None = None,
) -> list[str]:
    """Auto-apply eligible proposals; returns the applied ids.

    Only ``kind=preference`` + ``risk=LOW`` proposals are candidates,
    only when the persona opts in via ``learning.auto_apply_low_risk:
    true`` (default false), and each application still runs the FULL
    :func:`apply_proposal` gate chain (guardrail + eval gate). A
    refused candidate is skipped with a warning, never fatal.
    """
    config = require_learning(persona)
    if not config.auto_apply_low_risk:
        return []
    applied: list[str] = []
    for proposal in proposals:
        if proposal.kind != "preference":
            continue
        if proposal.risk_level is not RiskLevel.LOW:
            continue
        try:
            await apply_proposal(
                persona,
                proposal,
                manager,
                guardrails=guardrails,
                identity=identity,
                approved=False,
                gate_runner=gate_runner,
            )
            applied.append(proposal.proposal_id)
        except LearningError as exc:
            logger.warning(
                "auto-apply of proposal %s refused: %s",
                proposal.proposal_id,
                exc,
            )
    return applied


__all__ = [
    "BUDGET_ALERT_UTILIZATION",
    "DEFAULT_REFLECTION_CONSUMER",
    "EVAL_GATE_SCRIPT_ENV",
    "FEEDBACK_METADATA_SOURCE",
    "FEEDBACK_SOURCES",
    "LAST_REFLECTION_KEY",
    "LEARNING_APPLY_SPAN",
    "LEARNING_FEEDBACK_SPAN",
    "LEARNING_PROPOSE_SPAN",
    "LEARNING_REFLECT_SPAN",
    "PROPOSALS_DIR_NAME",
    "PROPOSAL_FORMAT",
    "PROPOSAL_KINDS",
    "PROPOSAL_VERSION",
    "REFLECTION_KEY_PREFIX",
    "RISK_BY_KIND",
    "FeedbackEvent",
    "GateResult",
    "ImprovementProposal",
    "LearningConfig",
    "LearningConfigError",
    "LearningDenied",
    "LearningError",
    "LearningMemoryStore",
    "ProposalError",
    "ReflectionResult",
    "apply_proposal",
    "collect_cost_feedback",
    "collect_eval_feedback",
    "collect_guardrail_feedback",
    "collect_machine_feedback",
    "collect_resilience_feedback",
    "derive_proposals",
    "identity_payload",
    "list_feedback",
    "list_proposals",
    "load_proposal",
    "maybe_auto_apply",
    "parse_learning_config",
    "proposal_path",
    "record_feedback",
    "require_learning",
    "resolve_proposals_dir",
    "run_eval_gate",
    "run_reflection",
    "run_reflection_for_persona",
    "write_proposal",
]
