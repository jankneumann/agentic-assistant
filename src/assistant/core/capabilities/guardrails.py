"""GuardrailProvider protocol, AllowAllGuardrails stub, and PolicyGuardrails.

P13 security-hardening adds :class:`PolicyGuardrails` — the first
non-allow-all implementation, configured from a persona ``guardrails:``
section:

.. code-block:: yaml

    guardrails:
      budgets:
        model_call:
          daily_usd: 5.0            # 0 / omitted = unlimited
          monthly_usd: 50.0
          default_call_cost_usd: 0  # applied when no cost metadata resolves
          persist: memory           # or "file" → <persona>/.cache/guardrails/spend.json
      policies:                     # first match wins, ordered
        - action_type: model_call   # exact match, or "*"
          resource: "expensive-*"   # glob against ActionRequest.resource
          effect: deny              # allow | deny | require_confirmation
          reason: "..."
      delegation:
        denied_sub_roles: [coder]   # globs against the sub-role name
        max_task_chars: 0           # 0 = unlimited

Semantics:

- **Action policies** are evaluated first (declaration order, first
  match wins). ``deny`` → ``allowed=False``; ``require_confirmation``
  → ``allowed=True, require_confirmation=True`` (which the model-call
  budget hook treats as a denial until the approval interrupt flow
  exists — P19 owner review verdict #2); ``allow`` → fall through to
  budgets. Policies are per-action rules; budgets are ceilings — an
  explicit ``allow`` never bypasses a ceiling.
- **Model-call budgets** track estimated spend per persona across
  calls (calendar-day / calendar-month windows, UTC). Cost per call
  resolves, in order: ``metadata["estimated_cost_usd"]``,
  ``compute_cost(metadata["pricing"], estimate_input_tokens,
  estimate_output_tokens)`` (P19 cost metadata — the budget hook in
  ``model_bindings.check_model_call`` puts ``ModelRef.pricing`` on
  the request), else ``default_call_cost_usd``. Unknown cost is never
  guessed (mirrors ``compute_cost``): with the default of ``0.0``,
  entries without pricing metadata do not consume budget — set
  ``default_call_cost_usd`` to cover them. A call whose projected
  spend exceeds a ceiling is denied and NOT recorded; allowed calls
  record their estimate.
- **Delegation constraints** preserve the existing
  ``check_delegation`` contract (the spawner raises
  ``PermissionError`` on ``allowed=False``).

Ledgers are process-wide singletons keyed by persona so budget state
survives the resolver constructing fresh ``PolicyGuardrails``
instances per ``resolve()`` call (harnesses re-resolve capabilities).
``persist: file`` swaps in a JSON-file ledger under the persona's
git-ignored ``.cache/`` directory so ceilings survive process
restarts; a persona-DB-backed ledger is deferred (needs an async
bridge from this sync protocol plus a migration — see the
security-hardening design doc).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from assistant.core.capabilities.types import ActionDecision, ActionRequest, RiskLevel

logger = logging.getLogger(__name__)

_VALID_EFFECTS = ("allow", "deny", "require_confirmation")
_VALID_PERSIST = ("memory", "file", "db")


@runtime_checkable
class GuardrailProvider(Protocol):
    def check_action(self, action: ActionRequest) -> ActionDecision: ...
    def check_delegation(
        self, parent_role: str, sub_role: str, task: str
    ) -> ActionDecision: ...
    def declare_risk(self, action: ActionRequest) -> RiskLevel: ...


class AllowAllGuardrails:
    def check_action(self, action: ActionRequest) -> ActionDecision:
        return ActionDecision(allowed=True)

    def check_delegation(
        self, parent_role: str, sub_role: str, task: str
    ) -> ActionDecision:
        return ActionDecision(allowed=True)

    def declare_risk(self, action: ActionRequest) -> RiskLevel:
        return RiskLevel.LOW


# ── Guardrail configuration (persona ``guardrails:`` section) ─────────


class GuardrailConfigError(ValueError):
    """A persona ``guardrails:`` section failed validation at load time."""


@dataclass
class ActionPolicy:
    """One allow/deny/require_confirmation rule.

    P25 agent-iam adds two OPTIONAL identity-aware dimensions,
    additive to the existing ``action_type`` / ``resource`` globs:

    - ``role``: glob matched against the acting role — the request's
      ``identity.role`` when an :class:`AgentIdentity` is attached,
      else the plain ``ActionRequest.role`` field. Default ``"*"``
      (matches everything, pre-P25 behavior).
    - ``min_chain_depth``: the policy only matches requests whose
      identity has at least this many delegation hops behind it.
      ``0`` (default) means no constraint. A non-zero value can never
      match a request WITHOUT an identity — chain depth cannot be
      established, so the policy is skipped (fail-open to the next
      policy, not fail-match).
    """

    action_type: str
    resource: str = "*"
    effect: str = "allow"
    reason: str = ""
    role: str = "*"
    min_chain_depth: int = 0


@dataclass
class ModelCallBudget:
    """Per-persona USD ceilings for ``model_call`` actions.

    A ceiling of ``0`` means unlimited. Token estimates feed
    ``compute_cost`` when only per-token pricing metadata is available
    at check time (the check runs pre-call, before real token counts
    exist).
    """

    daily_usd: float = 0.0
    monthly_usd: float = 0.0
    default_call_cost_usd: float = 0.0
    estimate_input_tokens: int = 2000
    estimate_output_tokens: int = 500


#: Default delegation-chain depth ceiling (agent-iam). Small on
#: purpose: runaway recursive delegation is a spend/loop hazard, and
#: legitimate chains in this system are shallow (parent -> specialist).
DEFAULT_MAX_CHAIN_DEPTH = 5


@dataclass
class DelegationConstraints:
    denied_sub_roles: list[str] = field(default_factory=list)
    max_task_chars: int = 0
    #: P25 agent-iam: maximum delegation-chain depth (number of hops
    #: behind the CHILD identity a new delegation would create). ``0``
    #: means unlimited. Enforced by the DelegationSpawner.
    max_chain_depth: int = DEFAULT_MAX_CHAIN_DEPTH


@dataclass
class GuardrailConfig:
    """Parsed persona ``guardrails:`` section.

    Falsy (the default) when the persona declares no guardrails — the
    resolver then selects :class:`AllowAllGuardrails`, preserving
    pre-P13 behavior.
    """

    policies: list[ActionPolicy] = field(default_factory=list)
    model_call_budget: ModelCallBudget | None = None
    delegation: DelegationConstraints = field(
        default_factory=DelegationConstraints
    )
    #: Set when ``budgets.model_call.persist: file`` — resolved at
    #: persona load to ``<persona_dir>/.cache/guardrails/spend.json``.
    spend_file: Path | None = None
    #: The raw ``budgets.model_call.persist`` selection. ``"db"`` (P30
    #: durable-sessions) selects :class:`PostgresBudgetLedger` on the
    #: persona DB via :func:`budget_ledger_for` — the caller must
    #: supply the persona's ``database_url``.
    spend_persist: str = "memory"

    def __bool__(self) -> bool:
        return bool(
            self.policies
            or self.model_call_budget is not None
            or self.delegation.denied_sub_roles
            or self.delegation.max_task_chars
        )


def _require_number(raw: Any, key: str, *, minimum: float = 0.0) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise GuardrailConfigError(
            f"guardrails: {key} must be a number, got {type(raw).__name__}."
        )
    value = float(raw)
    if value < minimum:
        raise GuardrailConfigError(
            f"guardrails: {key} must be >= {minimum}, got {value}."
        )
    return value


def parse_guardrail_config(
    raw: dict[str, Any] | None, *, persona_dir: Path | None = None
) -> GuardrailConfig:
    """Parse and validate a persona ``guardrails:`` section.

    Unknown keys, unknown policy effects, and malformed budget numbers
    fail with :class:`GuardrailConfigError` naming the offender —
    persona load surfaces this as an actionable error (same posture as
    the ``models:`` registry).
    """
    raw = raw or {}
    if not isinstance(raw, dict):
        raise GuardrailConfigError(
            f"guardrails: expected a mapping, got {type(raw).__name__}."
        )
    unknown = sorted(set(raw) - {"budgets", "policies", "delegation"})
    if unknown:
        raise GuardrailConfigError(
            f"guardrails: unknown keys {unknown}. Expected 'budgets:', "
            f"'policies:', and/or 'delegation:'."
        )

    policies: list[ActionPolicy] = []
    raw_policies = raw.get("policies") or []
    if not isinstance(raw_policies, list):
        raise GuardrailConfigError(
            f"guardrails: policies must be a list, got "
            f"{type(raw_policies).__name__}."
        )
    for i, entry in enumerate(raw_policies):
        if not isinstance(entry, dict):
            raise GuardrailConfigError(
                f"guardrails: policies[{i}] must be a mapping."
            )
        action_type = entry.get("action_type", "")
        if not isinstance(action_type, str) or not action_type:
            raise GuardrailConfigError(
                f"guardrails: policies[{i}] requires a non-empty "
                f"'action_type' (an action type name, or '*')."
            )
        effect = entry.get("effect", "allow")
        if effect not in _VALID_EFFECTS:
            raise GuardrailConfigError(
                f"guardrails: policies[{i}] effect {effect!r} is not one "
                f"of {list(_VALID_EFFECTS)}."
            )
        unknown_policy_keys = sorted(
            set(entry)
            - {
                "action_type",
                "resource",
                "effect",
                "reason",
                "role",
                "min_chain_depth",
            }
        )
        if unknown_policy_keys:
            raise GuardrailConfigError(
                f"guardrails: policies[{i}] has unknown keys "
                f"{unknown_policy_keys}. Allowed: ['action_type', "
                f"'effect', 'min_chain_depth', 'reason', 'resource', "
                f"'role']."
            )
        role = entry.get("role", "*")
        if not isinstance(role, str) or not role:
            raise GuardrailConfigError(
                f"guardrails: policies[{i}] role must be a non-empty "
                f"role-name glob (or '*')."
            )
        policies.append(
            ActionPolicy(
                action_type=action_type,
                resource=str(entry.get("resource", "*") or "*"),
                effect=effect,
                reason=str(entry.get("reason", "") or ""),
                role=role,
                min_chain_depth=int(
                    _require_number(
                        entry.get("min_chain_depth", 0),
                        f"policies[{i}].min_chain_depth",
                    )
                ),
            )
        )

    budget: ModelCallBudget | None = None
    spend_file: Path | None = None
    spend_persist = "memory"
    raw_budgets = raw.get("budgets") or {}
    if not isinstance(raw_budgets, dict):
        raise GuardrailConfigError(
            f"guardrails: budgets must be a mapping, got "
            f"{type(raw_budgets).__name__}."
        )
    unknown_budgets = sorted(set(raw_budgets) - {"model_call"})
    if unknown_budgets:
        raise GuardrailConfigError(
            f"guardrails: budgets has unknown keys {unknown_budgets}; "
            f"only 'model_call' budgets exist today."
        )
    raw_mc = raw_budgets.get("model_call")
    if raw_mc is not None:
        if not isinstance(raw_mc, dict):
            raise GuardrailConfigError(
                "guardrails: budgets.model_call must be a mapping."
            )
        allowed_keys = {
            "daily_usd",
            "monthly_usd",
            "default_call_cost_usd",
            "estimate_input_tokens",
            "estimate_output_tokens",
            "persist",
        }
        unknown_mc = sorted(set(raw_mc) - allowed_keys)
        if unknown_mc:
            raise GuardrailConfigError(
                f"guardrails: budgets.model_call has unknown keys "
                f"{unknown_mc}. Allowed: {sorted(allowed_keys)}."
            )
        budget = ModelCallBudget(
            daily_usd=_require_number(
                raw_mc.get("daily_usd", 0.0), "budgets.model_call.daily_usd"
            ),
            monthly_usd=_require_number(
                raw_mc.get("monthly_usd", 0.0),
                "budgets.model_call.monthly_usd",
            ),
            default_call_cost_usd=_require_number(
                raw_mc.get("default_call_cost_usd", 0.0),
                "budgets.model_call.default_call_cost_usd",
            ),
            estimate_input_tokens=int(
                _require_number(
                    raw_mc.get("estimate_input_tokens", 2000),
                    "budgets.model_call.estimate_input_tokens",
                )
            ),
            estimate_output_tokens=int(
                _require_number(
                    raw_mc.get("estimate_output_tokens", 500),
                    "budgets.model_call.estimate_output_tokens",
                )
            ),
        )
        persist = raw_mc.get("persist", "memory")
        if persist not in _VALID_PERSIST:
            raise GuardrailConfigError(
                f"guardrails: budgets.model_call.persist {persist!r} is "
                f"not one of {list(_VALID_PERSIST)}."
            )
        spend_persist = persist
        if persist == "file":
            if persona_dir is None:
                raise GuardrailConfigError(
                    "guardrails: budgets.model_call.persist: file requires "
                    "a persona directory (loaded personas only)."
                )
            spend_file = (
                Path(persona_dir) / ".cache" / "guardrails" / "spend.json"
            )

    raw_delegation = raw.get("delegation") or {}
    if not isinstance(raw_delegation, dict):
        raise GuardrailConfigError(
            f"guardrails: delegation must be a mapping, got "
            f"{type(raw_delegation).__name__}."
        )
    unknown_delegation = sorted(
        set(raw_delegation)
        - {"denied_sub_roles", "max_task_chars", "max_chain_depth"}
    )
    if unknown_delegation:
        raise GuardrailConfigError(
            f"guardrails: delegation has unknown keys {unknown_delegation}."
        )
    denied = raw_delegation.get("denied_sub_roles") or []
    if not isinstance(denied, list) or not all(
        isinstance(x, str) for x in denied
    ):
        raise GuardrailConfigError(
            "guardrails: delegation.denied_sub_roles must be a list of "
            "role-name globs."
        )
    delegation = DelegationConstraints(
        denied_sub_roles=list(denied),
        max_task_chars=int(
            _require_number(
                raw_delegation.get("max_task_chars", 0),
                "guardrails: delegation.max_task_chars",
            )
        ),
        max_chain_depth=int(
            _require_number(
                raw_delegation.get("max_chain_depth", DEFAULT_MAX_CHAIN_DEPTH),
                "guardrails: delegation.max_chain_depth",
            )
        ),
    )

    return GuardrailConfig(
        policies=policies,
        model_call_budget=budget,
        delegation=delegation,
        spend_file=spend_file,
        spend_persist=spend_persist,
    )


# ── Budget ledgers ────────────────────────────────────────────────────


@runtime_checkable
class BudgetLedger(Protocol):
    """Append-only spend counter behind the model-call budget check."""

    def record(self, cost_usd: float, at: datetime) -> None: ...
    def spent_since(self, since: datetime) -> float: ...


class InMemoryBudgetLedger:
    """Process-lifetime spend counter (the default)."""

    def __init__(self) -> None:
        self._entries: list[tuple[datetime, float]] = []
        self._lock = threading.Lock()

    def record(self, cost_usd: float, at: datetime) -> None:
        with self._lock:
            self._entries.append((at, cost_usd))

    def spent_since(self, since: datetime) -> float:
        with self._lock:
            return sum(cost for at, cost in self._entries if at >= since)


class JsonFileBudgetLedger:
    """Spend counter persisted as JSON lines-in-a-list in the persona dir.

    Written to the persona's git-ignored ``.cache/`` tree (the
    template ``.gitignore`` already excludes it). Entries older than
    the start of the previous calendar month are pruned on write —
    nothing outside the daily/monthly windows is ever needed. Load
    errors degrade to an empty ledger with a WARNING (a corrupt spend
    file must not brick the persona; the ceiling restarts from zero,
    which is the permissive direction — documented trade-off).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._entries: list[tuple[datetime, float]] = self._load()

    def _load(self) -> list[tuple[datetime, float]]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [
                (datetime.fromisoformat(at), float(cost))
                for at, cost in raw["entries"]
            ]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "budget ledger %s unreadable (%s); starting empty",
                self._path,
                type(exc).__name__,
            )
            return []

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        cutoff = _previous_month_start(datetime.now(UTC))
        self._entries = [
            (at, cost) for at, cost in self._entries if at >= cutoff
        ]
        payload = {
            "entries": [
                [at.isoformat(), cost] for at, cost in self._entries
            ]
        }
        self._path.write_text(json.dumps(payload), encoding="utf-8")

    def record(self, cost_usd: float, at: datetime) -> None:
        with self._lock:
            self._entries.append((at, cost_usd))
            try:
                self._flush()
            except OSError as exc:
                logger.warning(
                    "budget ledger %s not persisted (%s); spend tracked "
                    "in memory for this process",
                    self._path,
                    type(exc).__name__,
                )

    def spent_since(self, since: datetime) -> float:
        with self._lock:
            return sum(cost for at, cost in self._entries if at >= since)


#: Process-wide ledger registry: budget state must survive the
#: capability resolver constructing a fresh PolicyGuardrails per
#: resolve() call. Keyed by persona name + persistence target.
_LEDGERS: dict[str, BudgetLedger] = {}
_LEDGERS_LOCK = threading.Lock()


def budget_ledger_for(
    persona: str, config: GuardrailConfig, *, database_url: str = ""
) -> BudgetLedger:
    """Resolve the persona's process-wide spend ledger.

    ``persist: memory`` (default) → :class:`InMemoryBudgetLedger`;
    ``persist: file`` → :class:`JsonFileBudgetLedger` under the
    persona ``.cache/`` tree; ``persist: db`` (P30 durable-sessions)
    → ``PostgresBudgetLedger`` on the persona DB — the caller passes
    the resolved ``database_url`` (the config section cannot carry it;
    the url resolves through the credential seam at persona load). A
    ``db`` selection without a url raises an actionable error rather
    than silently degrading to a process-local ledger.
    """
    if config.spend_persist == "db":
        if not database_url:
            raise GuardrailConfigError(
                f"guardrails: budgets.model_call.persist: db for persona "
                f"{persona!r} requires a resolvable database url "
                f"(database: {{url_env: ...}}); none resolved."
            )
        key = f"{persona}:db:{database_url}"
        with _LEDGERS_LOCK:
            ledger = _LEDGERS.get(key)
            if ledger is None:
                # Lazy import: keep guardrails import-light; the durable
                # module owns the SQLAlchemy schema (G4 posture — import
                # at the source module for patching).
                from assistant.core.db import create_sync_engine
                from assistant.core.durable import PostgresBudgetLedger

                ledger = PostgresBudgetLedger(
                    create_sync_engine(database_url), persona=persona
                )
                _LEDGERS[key] = ledger
            return ledger
    key = f"{persona}:{config.spend_file or '<memory>'}"
    with _LEDGERS_LOCK:
        ledger = _LEDGERS.get(key)
        if ledger is None:
            ledger = (
                JsonFileBudgetLedger(config.spend_file)
                if config.spend_file is not None
                else InMemoryBudgetLedger()
            )
            _LEDGERS[key] = ledger
        return ledger


def _clear_budget_ledgers() -> None:
    """Test hook: drop all process-wide ledger state."""
    with _LEDGERS_LOCK:
        _LEDGERS.clear()


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


def _previous_month_start(now: datetime) -> datetime:
    """Ledger pruning cutoff: keep the previous + current month."""
    this_month = _month_start(now)
    if this_month.month == 1:
        return this_month.replace(year=this_month.year - 1, month=12)
    return this_month.replace(month=this_month.month - 1)


# ── PolicyGuardrails ─────────────────────────────────────────────────


class PolicyGuardrails:
    """First non-allow-all GuardrailProvider (P13 security-hardening).

    See the module docstring for configuration shape and semantics.
    ``now`` is injectable for deterministic tests; production uses
    UTC wall-clock.
    """

    def __init__(
        self,
        config: GuardrailConfig,
        *,
        persona: str = "",
        ledger: BudgetLedger | None = None,
        now: Callable[[], datetime] | None = None,
        database_url: str = "",
    ) -> None:
        self._config = config
        self._persona = persona
        # ``database_url`` matters only for ``persist: db`` (P30) — the
        # resolver and CLI guardrail-selection paths pass the persona's
        # resolved url so the DB ledger can be constructed.
        self._ledger = ledger or budget_ledger_for(
            persona, config, database_url=database_url
        )
        self._now = now or (lambda: datetime.now(UTC))

    # -- protocol surface ------------------------------------------------

    def check_action(self, action: ActionRequest) -> ActionDecision:
        policy = self._match_policy(action)
        if policy is not None:
            if policy.effect == "deny":
                return ActionDecision(
                    allowed=False,
                    reason=policy.reason
                    or (
                        f"denied by guardrail policy "
                        f"(action_type={policy.action_type!r}, "
                        f"resource={policy.resource!r})"
                    ),
                )
            if policy.effect == "require_confirmation":
                return ActionDecision(
                    allowed=True,
                    reason=policy.reason
                    or (
                        f"confirmation required by guardrail policy "
                        f"(action_type={policy.action_type!r}, "
                        f"resource={policy.resource!r})"
                    ),
                    require_confirmation=True,
                )
            # effect == "allow": explicit allow rules do not bypass
            # budget ceilings — fall through.
        budget = self._config.model_call_budget
        if action.action_type == "model_call" and budget is not None:
            return self._check_budget(action, budget)
        return ActionDecision(allowed=True)

    def check_delegation(
        self, parent_role: str, sub_role: str, task: str
    ) -> ActionDecision:
        for pattern in self._config.delegation.denied_sub_roles:
            if fnmatchcase(sub_role, pattern):
                return ActionDecision(
                    allowed=False,
                    reason=(
                        f"delegation from {parent_role!r} to {sub_role!r} "
                        f"denied by guardrail (matches {pattern!r})"
                    ),
                )
        max_chars = self._config.delegation.max_task_chars
        if max_chars and len(task) > max_chars:
            return ActionDecision(
                allowed=False,
                reason=(
                    f"delegation task is {len(task)} chars; guardrail "
                    f"limit is {max_chars}"
                ),
            )
        return ActionDecision(allowed=True)

    def declare_risk(self, action: ActionRequest) -> RiskLevel:
        policy = self._match_policy(action)
        if policy is not None and policy.effect in (
            "deny",
            "require_confirmation",
        ):
            return RiskLevel.HIGH
        if (
            action.action_type == "model_call"
            and self._config.model_call_budget is not None
        ):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # -- internals ---------------------------------------------------------

    def _match_policy(self, action: ActionRequest) -> ActionPolicy | None:
        identity = action.identity
        for policy in self._config.policies:
            if policy.action_type not in ("*", action.action_type):
                continue
            if not fnmatchcase(action.resource, policy.resource):
                continue
            # P25 agent-iam: identity-aware dimensions, additive to the
            # action_type/resource globs above.
            if policy.role != "*":
                acting_role = (
                    identity.role if identity is not None else action.role
                )
                if not fnmatchcase(acting_role, policy.role):
                    continue
            if policy.min_chain_depth > 0:
                # Chain depth is only knowable with an identity; a
                # depth-scoped policy never matches identity-less
                # requests (skip to the next policy, don't deny).
                if (
                    identity is None
                    or identity.chain_depth < policy.min_chain_depth
                ):
                    continue
            return policy
        return None

    def _estimate_cost(
        self, action: ActionRequest, budget: ModelCallBudget
    ) -> float:
        metadata = action.metadata or {}
        estimated = metadata.get("estimated_cost_usd")
        if isinstance(estimated, (int, float)) and not isinstance(
            estimated, bool
        ):
            return float(estimated)
        pricing = metadata.get("pricing")
        if isinstance(pricing, dict):
            from assistant.core.capabilities.models import compute_cost

            cost = compute_cost(
                pricing,
                budget.estimate_input_tokens,
                budget.estimate_output_tokens,
            )
            if cost is not None:
                return cost
        return budget.default_call_cost_usd

    def _check_budget(
        self, action: ActionRequest, budget: ModelCallBudget
    ) -> ActionDecision:
        cost = self._estimate_cost(action, budget)
        now = self._now()
        for label, ceiling, since in (
            ("daily", budget.daily_usd, _day_start(now)),
            ("monthly", budget.monthly_usd, _month_start(now)),
        ):
            if ceiling <= 0:
                continue
            spent = self._ledger.spent_since(since)
            if spent + cost > ceiling:
                return ActionDecision(
                    allowed=False,
                    reason=(
                        f"model_call budget exceeded for persona "
                        f"{self._persona or action.persona!r}: {label} "
                        f"ceiling ${ceiling:.2f}, spent ${spent:.4f}, "
                        f"this call estimated ${cost:.4f}"
                    ),
                )
        if cost > 0:
            self._ledger.record(cost, now)
        return ActionDecision(allowed=True)
