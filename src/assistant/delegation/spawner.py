"""Sub-agent delegation with role-switching + concurrency enforcement.

P25 agent-iam adds delegation-chain attribution: the spawner carries an
:class:`AgentIdentity` for the parent (injected by the caller, or
synthesized from persona + parent role), derives the child principal
for every hop via ``identity.delegate_to(sub_role)``, enforces the
persona's ``guardrails.delegation.max_chain_depth`` ceiling (default
5; ``0`` = unlimited), logs the chain on every decision, and emits a
guardrail audit record through the telemetry provider.

P12 delegation-context adds rich delegation on top:

- every hop constructs a :class:`DelegationContext` (child identity,
  memory snippets fetched under the SUB-role, optional parent-supplied
  conversation summary, constraints) and threads it into
  ``spawn_sub_agent`` — harnesses render it as a ``## Delegation
  context`` prompt block;
- cycle detection: a sub-role already present in the identity's
  delegation chain (or self-delegation) is denied unless the parent
  role opts in with ``delegation.allow_recursive: true``;
- ``delegate_parallel`` fans out several delegations under a
  semaphore with per-task error isolation;
- an in-flight registry (``list_active`` / ``cancel`` / ``analytics``)
  tracks every delegation for monitoring and cancellation;
- ``delegate_auto`` selects the sub-role via
  :class:`~assistant.delegation.router.DelegationRouter`.

Analytics are DB-migration-free by design: outcomes ride the existing
``trace_delegation`` telemetry span (P4) plus a best-effort one-line
``record_interaction`` summary under the parent role (a no-op for
file-backed memory), and the in-process registry serves live queries.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from assistant.core.capabilities.audit import emit_guardrail_audit
from assistant.core.capabilities.guardrails import (
    DEFAULT_MAX_CHAIN_DEPTH,
    AllowAllGuardrails,
    GuardrailProvider,
)
from assistant.core.capabilities.identity import AgentIdentity
from assistant.core.capabilities.memory import MemoryPolicy
from assistant.core.capabilities.types import ActionDecision, ActionRequest
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.context import DelegationContext
from assistant.delegation.router import DelegationRouter, RouteDecision
from assistant.harnesses.base import SdkHarnessAdapter
from assistant.telemetry.decorators import traced_delegation

logger = logging.getLogger(__name__)

#: Snippets fetched under the sub-role for the DelegationContext block.
#: Deliberately below the harness's own D27 limit (10) — the context
#: block is a hand-off cue, not the sub-agent's full recent context.
DEFAULT_CONTEXT_SNIPPET_LIMIT: int = 5

#: Upper bound on retained finished DelegationRecords (running records
#: are never evicted). Keeps the in-process analytics registry bounded
#: for long-lived daemon spawners.
_MAX_FINISHED_RECORDS: int = 256

#: Fallback concurrent-delegation ceiling when the parent role's
#: ``delegation:`` section declares no ``max_concurrent``.
_DEFAULT_MAX_CONCURRENT: int = 3


@dataclass
class DelegationRecord:
    """One tracked delegation in the spawner's monitoring registry."""

    delegation_id: str
    sub_role: str
    task: str
    started_at: datetime
    status: str = "running"  # running | succeeded | failed | cancelled
    finished_at: datetime | None = None
    error: str = ""

    @property
    def duration_ms(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds() * 1000.0


@dataclass(frozen=True)
class DelegationOutcome:
    """Per-task result marker returned by ``delegate_parallel``."""

    sub_role: str
    task: str
    status: str  # success | error | cancelled
    result: str = ""
    error: str = ""


class DelegationSpawner:
    def __init__(
        self,
        persona: PersonaConfig,
        parent_role: RoleConfig,
        harness: SdkHarnessAdapter,
        tools: list[Any],
        extensions: list[Any],
        role_registry: RoleRegistry | None = None,
        guardrails: GuardrailProvider | None = None,
        identity: AgentIdentity | None = None,
        memory_policy: MemoryPolicy | None = None,
        router: DelegationRouter | None = None,
    ) -> None:
        self.persona = persona
        self.parent_role = parent_role
        self.harness = harness
        self.tools = tools
        self.extensions = extensions
        self.role_registry = role_registry or RoleRegistry()
        self.guardrails: GuardrailProvider = guardrails or AllowAllGuardrails()
        # P25 agent-iam: the parent principal for chain attribution. A
        # nested spawner receives the (already-extended) identity of
        # its parent hop; a top-level spawner synthesizes the root.
        if identity is None:
            try:
                session_id = str(harness.thread_id or "")
            except (NotImplementedError, AttributeError):
                # Base-class property for harnesses predating the
                # thread_id contract (or test doubles without one) —
                # identity works without a session id.
                session_id = ""
            identity = AgentIdentity(
                persona=persona.name,
                role=parent_role.name,
                session_id=session_id,
            )
        self.identity: AgentIdentity = identity
        # P12: injected MemoryPolicy for context snippets + analytics
        # capture; ``None`` resolves lazily via CapabilityResolver.
        self._memory_policy = memory_policy
        self._memory_policy_resolved = memory_policy is not None
        self._router = router
        self._active: int = 0
        # P12 monitoring registry: every delegate() call is recorded;
        # running entries carry their asyncio task for cancel().
        self._records: dict[str, DelegationRecord] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    # ── audit + guardrail plumbing (P25) ──────────────────────────

    def _audit(self, sub_role_name: str, decision: ActionDecision) -> None:
        """Log the chain + emit the audit record for one decision."""
        child = self.identity.delegate_to(sub_role_name)
        logger.info(
            "delegation %s: chain %s (depth %d) -> %s",
            "allowed" if decision.allowed else "DENIED",
            self.identity.chain_display(),
            child.chain_depth,
            sub_role_name,
        )
        emit_guardrail_audit(
            ActionRequest(
                action_type="delegation",
                resource=sub_role_name,
                persona=self.persona.name,
                role=self.parent_role.name,
                metadata={
                    "child_chain": [*child.delegation_chain, child.role],
                    "child_chain_depth": child.chain_depth,
                },
                identity=self.identity,
            ),
            decision,
        )

    # ── DelegationContext construction (P12) ──────────────────────

    def _resolve_memory_policy(self) -> MemoryPolicy | None:
        """Injected policy, else lazy CapabilityResolver resolution.

        Resolution failures degrade to ``None`` (no snippets, no
        analytics capture) — context enrichment must never make a
        previously working delegation fail.
        """
        if not self._memory_policy_resolved:
            self._memory_policy_resolved = True
            try:
                from assistant.core.capabilities.resolver import (
                    CapabilityResolver,
                )

                resolver = CapabilityResolver()
                self._memory_policy = resolver.resolve(
                    self.persona, "sdk", self.parent_role
                ).memory
            except Exception:
                logger.warning(
                    "MemoryPolicy resolution failed; delegation context "
                    "proceeds without memory snippets",
                    exc_info=True,
                )
                self._memory_policy = None
        return self._memory_policy

    async def _build_context(
        self,
        sub_role: RoleConfig,
        child: AgentIdentity,
        *,
        conversation_summary: str = "",
        deadline_seconds: float | None = None,
        allowed_tools: Sequence[str] | None = None,
        max_depth: int,
    ) -> DelegationContext:
        """Assemble the DelegationContext for one hop.

        Memory snippets are fetched under the SUB-role (the sub-agent's
        retrieval scope, not the parent's) and error-swallowed — a down
        memory backend yields an identity-only context block.
        """
        snippets: tuple[str, ...] = ()
        policy = self._resolve_memory_policy()
        if policy is not None:
            try:
                snippets = tuple(
                    await policy.get_recent_snippets(
                        self.persona,
                        sub_role,
                        limit=DEFAULT_CONTEXT_SNIPPET_LIMIT,
                    )
                )
            except Exception:
                logger.warning(
                    "Snippet retrieval for delegation context failed; "
                    "continuing without snippets",
                    exc_info=True,
                )
        constraints: dict[str, Any] = {}
        if max_depth:
            constraints["max_depth_remaining"] = max(
                max_depth - child.chain_depth, 0
            )
        if deadline_seconds is not None:
            constraints["deadline_seconds"] = deadline_seconds
        if allowed_tools is not None:
            constraints["allowed_tools"] = list(allowed_tools)
        return DelegationContext(
            parent_role=self.parent_role.name,
            identity=child,
            memory_snippets=snippets,
            conversation_summary=conversation_summary,
            constraints=constraints,
        )

    async def _call_spawn(
        self, sub_role: RoleConfig, task: str, context: DelegationContext
    ) -> str:
        """Invoke ``harness.spawn_sub_agent``, threading the context.

        Backward compatibility: adapters predating the P12 ``context``
        keyword (out-of-tree or test doubles) are detected via
        signature inspection and called with the pre-P12 argument list
        — the context block is dropped for that hop with a WARNING.
        """
        spawn = self.harness.spawn_sub_agent
        try:
            params = inspect.signature(spawn).parameters
            accepts_context = "context" in params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD
                for p in params.values()
            )
        except (TypeError, ValueError):  # builtins / exotic callables
            accepts_context = False
        if accepts_context:
            return await spawn(
                sub_role, task, self.tools, self.extensions, context=context
            )
        logger.warning(
            "Harness %r spawn_sub_agent does not accept the P12 "
            "'context' keyword; delegation context dropped for this hop",
            type(self.harness).__name__,
        )
        return await spawn(sub_role, task, self.tools, self.extensions)

    async def _record_outcome_summary(
        self, sub_role_name: str, task: str, result: str
    ) -> None:
        """Best-effort delegation-analytics capture (P12).

        Stores a one-line ``[delegation]``-prefixed summary under the
        PARENT role via ``record_interaction`` — distinguishable from
        the sub-agent's own post-turn capture (which records the raw
        task under the sub-role). File-backed memory no-ops; failures
        are swallowed (analytics must never break a delegation).
        """
        policy = self._resolve_memory_policy()
        if policy is None:
            return
        try:
            await policy.record_interaction(
                self.persona,
                self.parent_role,
                user_message=(
                    f"[delegation] {self.parent_role.name} -> "
                    f"{sub_role_name}: {task}"
                ),
                response=result,
            )
        except Exception:
            logger.warning(
                "Delegation outcome capture failed; continuing",
                exc_info=True,
            )

    # ── core delegation (P25 checks + P12 context) ────────────────

    @traced_delegation
    async def delegate(
        self,
        sub_role_name: str,
        task: str,
        *,
        conversation_summary: str = "",
        deadline_seconds: float | None = None,
        allowed_tools: Sequence[str] | None = None,
    ) -> str:
        allowed = self.parent_role.delegation.get("allowed_sub_roles", []) or []
        if sub_role_name not in allowed:
            raise ValueError(
                f"Role '{self.parent_role.name}' cannot delegate to "
                f"'{sub_role_name}'. Allowed: {allowed}"
            )

        available = self.role_registry.available_for_persona(self.persona)
        if sub_role_name not in available:
            raise ValueError(
                f"Role '{sub_role_name}' is not available for persona "
                f"'{self.persona.name}' (check disabled_roles)."
            )

        child = self.identity.delegate_to(sub_role_name)

        # P12 delegation-context: cycle detection. A sub-role already
        # in the chain (or self-delegation) is denied unless the
        # parent role opts in via ``delegation.allow_recursive: true``.
        # Checked BEFORE depth + guardrails: a cycle is structurally
        # wrong regardless of ceilings or policy.
        allow_recursive = bool(
            self.parent_role.delegation.get("allow_recursive", False)
        )
        is_cycle = (
            sub_role_name == self.identity.role
            or sub_role_name in self.identity.delegation_chain
        )
        if is_cycle and not allow_recursive:
            decision = ActionDecision(
                allowed=False,
                reason=(
                    f"delegation cycle: role '{sub_role_name}' already "
                    f"appears in the delegation chain "
                    f"({child.chain_display()}). Set "
                    f"'delegation.allow_recursive: true' on role "
                    f"'{self.parent_role.name}' to permit recursive "
                    f"delegation."
                ),
            )
            self._audit(sub_role_name, decision)
            raise PermissionError(decision.reason)

        # P25 agent-iam: enforce the delegation-chain depth ceiling
        # BEFORE the guardrail check — an over-deep chain is denied
        # regardless of what the policy provider would say.
        guardrail_config = getattr(self.persona, "guardrails", None)
        max_depth = (
            guardrail_config.delegation.max_chain_depth
            if guardrail_config is not None
            else DEFAULT_MAX_CHAIN_DEPTH
        )
        if max_depth and child.chain_depth > max_depth:
            decision = ActionDecision(
                allowed=False,
                reason=(
                    f"delegation chain depth {child.chain_depth} exceeds "
                    f"max_chain_depth {max_depth} "
                    f"(chain: {child.chain_display()})"
                ),
            )
            self._audit(sub_role_name, decision)
            raise PermissionError(decision.reason)

        decision = self.guardrails.check_delegation(
            self.parent_role.name, sub_role_name, task
        )
        self._audit(sub_role_name, decision)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        max_concurrent = self.parent_role.delegation.get(
            "max_concurrent", _DEFAULT_MAX_CONCURRENT
        )
        if self._active >= max_concurrent:
            raise RuntimeError(
                f"Max concurrent delegations ({max_concurrent}) reached for "
                f"role '{self.parent_role.name}'."
            )

        sub_role = self.role_registry.load(sub_role_name, self.persona)
        context = await self._build_context(
            sub_role,
            child,
            conversation_summary=conversation_summary,
            deadline_seconds=deadline_seconds,
            allowed_tools=allowed_tools,
            max_depth=max_depth,
        )

        record = DelegationRecord(
            delegation_id=str(uuid4()),
            sub_role=sub_role_name,
            task=task,
            started_at=datetime.now(UTC),
        )
        self._records[record.delegation_id] = record
        current = asyncio.current_task()
        if current is not None:
            self._tasks[record.delegation_id] = current

        self._active += 1
        try:
            if deadline_seconds is not None:
                async with asyncio.timeout(deadline_seconds):
                    result = await self._call_spawn(sub_role, task, context)
            else:
                result = await self._call_spawn(sub_role, task, context)
        except asyncio.CancelledError:
            record.status = "cancelled"
            raise
        except BaseException as exc:
            record.status = "failed"
            record.error = type(exc).__name__
            raise
        else:
            record.status = "succeeded"
            await self._record_outcome_summary(sub_role_name, task, result)
            return result
        finally:
            record.finished_at = datetime.now(UTC)
            self._tasks.pop(record.delegation_id, None)
            self._active -= 1
            self._trim_records()

    # ── parallel delegation (P12) ─────────────────────────────────

    async def delegate_parallel(
        self,
        tasks: Sequence[tuple[str, str]],
        *,
        max_concurrent: int | None = None,
        conversation_summary: str = "",
    ) -> list[DelegationOutcome]:
        """Fan out ``(sub_role, task)`` pairs with per-task isolation.

        Concurrency is bounded by a semaphore sized to the parent
        role's ``delegation.max_concurrent`` (optionally narrowed by
        the ``max_concurrent`` argument) so queued tasks WAIT instead
        of tripping ``delegate()``'s hard concurrency ceiling. One
        failing task never aborts its siblings: every pair yields a
        :class:`DelegationOutcome` marker (``success`` / ``error`` /
        ``cancelled``) in input order.
        """
        if not tasks:
            return []
        role_limit = int(
            self.parent_role.delegation.get(
                "max_concurrent", _DEFAULT_MAX_CONCURRENT
            )
        )
        limit = role_limit
        if max_concurrent is not None:
            limit = min(limit, max_concurrent)
        limit = max(limit, 1)
        semaphore = asyncio.Semaphore(limit)

        async def _run(sub_role_name: str, task: str) -> str:
            async with semaphore:
                return await self.delegate(
                    sub_role_name,
                    task,
                    conversation_summary=conversation_summary,
                )

        results = await asyncio.gather(
            *(_run(r, t) for r, t in tasks), return_exceptions=True
        )
        outcomes: list[DelegationOutcome] = []
        for (sub_role_name, task), result in zip(tasks, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                outcomes.append(
                    DelegationOutcome(
                        sub_role=sub_role_name,
                        task=task,
                        status="cancelled",
                        error="CancelledError",
                    )
                )
            elif isinstance(result, BaseException):
                outcomes.append(
                    DelegationOutcome(
                        sub_role=sub_role_name,
                        task=task,
                        status="error",
                        error=f"{type(result).__name__}: {result}",
                    )
                )
            else:
                outcomes.append(
                    DelegationOutcome(
                        sub_role=sub_role_name,
                        task=task,
                        status="success",
                        result=result,
                    )
                )
        return outcomes

    # ── automatic sub-role selection (P12 router) ─────────────────

    async def delegate_auto(
        self,
        task: str,
        *,
        conversation_summary: str = "",
        deadline_seconds: float | None = None,
        allowed_tools: Sequence[str] | None = None,
    ) -> str:
        """Route ``task`` to a sub-role automatically, then delegate.

        Candidates are the parent role's ``allowed_sub_roles``
        intersected with the persona's available roles, in declaration
        order. Raises ``ValueError`` when no candidate exists and
        :class:`~assistant.delegation.router.RoutingError` when the
        router cannot classify the task.
        """
        decision = await self.route_task(task)
        return await self.delegate(
            decision.sub_role,
            task,
            conversation_summary=conversation_summary,
            deadline_seconds=deadline_seconds,
            allowed_tools=allowed_tools,
        )

    async def route_task(self, task: str) -> RouteDecision:
        """Run the router over this spawner's candidate sub-roles."""
        allowed = self.parent_role.delegation.get("allowed_sub_roles", []) or []
        available = set(
            self.role_registry.available_for_persona(self.persona)
        )
        candidate_names = [r for r in allowed if r in available]
        if not candidate_names:
            raise ValueError(
                f"Role '{self.parent_role.name}' has no available "
                f"sub-roles to route between (allowed: {allowed})."
            )
        candidates = [
            self.role_registry.load(name, self.persona)
            for name in candidate_names
        ]
        router = self._router or DelegationRouter(
            self.persona, guardrails=self.guardrails
        )
        return await router.route(task, candidates)

    # ── monitoring / cancellation / analytics (P12) ───────────────

    def list_active(self) -> list[DelegationRecord]:
        """Snapshot of delegations currently in flight."""
        return [r for r in self._records.values() if r.status == "running"]

    def get_record(self, delegation_id: str) -> DelegationRecord | None:
        return self._records.get(delegation_id)

    def cancel(self, delegation_id: str) -> bool:
        """Request cancellation of an in-flight delegation.

        Returns ``True`` when a cancellation was requested, ``False``
        for unknown ids or already-finished delegations. Cancellation
        propagates ``asyncio.CancelledError`` to whoever awaits the
        ``delegate()`` call (``delegate_parallel`` maps it to a
        ``cancelled`` outcome marker).
        """
        task = self._tasks.get(delegation_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def analytics(self) -> dict[str, Any]:
        """In-process delegation analytics over the registry.

        DB-migration-free (P12 design deviation from the old roadmap
        text): durable analytics ride the existing ``trace_delegation``
        span + the ``record_interaction`` summary; this method serves
        live counters for the current spawner.
        """
        records = list(self._records.values())
        by_status = Counter(r.status for r in records)
        by_sub_role = Counter(r.sub_role for r in records)
        durations = [
            r.duration_ms for r in records if r.duration_ms is not None
        ]
        return {
            "total": len(records),
            "active": by_status.get("running", 0),
            "by_status": dict(by_status),
            "by_sub_role": dict(by_sub_role),
            "avg_duration_ms": (
                sum(durations) / len(durations) if durations else None
            ),
        }

    def _trim_records(self) -> None:
        """Evict the oldest FINISHED records beyond the retention cap."""
        finished = [
            r for r in self._records.values() if r.status != "running"
        ]
        overflow = len(finished) - _MAX_FINISHED_RECORDS
        if overflow <= 0:
            return
        finished.sort(key=lambda r: r.started_at)
        for record in finished[:overflow]:
            self._records.pop(record.delegation_id, None)
