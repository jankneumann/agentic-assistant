"""Harness routing rule schema + matchers (P11 harness-routing).

The persona ``harnesses.routing:`` list declares ordered first-match
rules for automatic harness selection (``--harness auto``)::

    harnesses:
      routing:
        - tools: ["ms_graph:*", "outlook:*"]   # preferred_tools globs
          harness: ms_agent_framework
        - role: "coder"                        # role-name glob
          harness: deep_agents

Only the **schema** and pure matching helpers live here. The
precedence walk itself (``select_harness``) lives in
``harnesses/factory.py`` next to ``HARNESS_REGISTRY`` — the registry
also owns registry-level validation of rule targets (unknown / host /
disabled harness), because this module is imported by
``core/persona.py`` and the import direction ``factory → persona``
forbids the reverse (same discipline as the scheduler schema).

Shape validation happens at persona load with the actionable-error
posture of the ``models:`` / ``guardrails:`` / ``schedules:`` sections:
a bad rule fails persona load naming the rule index and offender.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

#: Sentinel harness name that requests automatic selection.
AUTO_HARNESS = "auto"

#: Tool-source prefixes that mark a role as M365-flavored (the four
#: MS extensions from P5 ``ms-graph-extension``). A role whose
#: ``preferred_tools`` reference any of these sources routes to the
#: MS Agent Framework harness when it is enabled.
MS_TOOL_SOURCES = frozenset({"ms_graph", "outlook", "teams", "sharepoint"})

_RULE_KEYS = frozenset({"role", "tools", "harness"})


class HarnessRoutingError(ValueError):
    """A persona ``harnesses.routing:`` section failed validation."""


@dataclass(frozen=True)
class HarnessRoutingRule:
    """One ordered entry of the persona ``harnesses.routing:`` list.

    ``role`` is an fnmatch glob on the role name (empty = any role);
    ``tools`` are fnmatch globs matched against the role's
    ``preferred_tools`` entries (empty = any tools). At least one of
    the two matchers is always present (enforced at parse). ``harness``
    names the target — validated against the registry by
    ``select_harness``, not here.
    """

    harness: str
    role: str = ""
    tools: tuple[str, ...] = ()


def parse_harness_routing(raw: Any) -> tuple[HarnessRoutingRule, ...]:
    """Parse and shape-validate a ``harnesses.routing:`` list.

    Returns an empty tuple when the section is absent. Raises
    :class:`HarnessRoutingError` naming the rule index for unknown
    keys, wrong types, empty matchers, or a missing ``harness:``.
    """
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise HarnessRoutingError(
            f"expected a list of routing rules, got {type(raw).__name__}."
        )

    rules: list[HarnessRoutingRule] = []
    for index, spec in enumerate(raw):
        if not isinstance(spec, dict):
            raise HarnessRoutingError(
                f"rule[{index}]: expected a mapping, got "
                f"{type(spec).__name__}."
            )
        unknown = sorted(set(spec) - _RULE_KEYS)
        if unknown:
            raise HarnessRoutingError(
                f"rule[{index}]: unknown keys {unknown}. "
                f"Allowed: {sorted(_RULE_KEYS)}."
            )

        harness = spec.get("harness")
        if not isinstance(harness, str) or not harness:
            raise HarnessRoutingError(
                f"rule[{index}]: 'harness' must be a non-empty harness "
                f"name."
            )

        role = spec.get("role", "")
        if role is None:
            role = ""
        if not isinstance(role, str):
            raise HarnessRoutingError(
                f"rule[{index}]: 'role' must be a role-name glob "
                f"string, got {type(role).__name__}."
            )

        tools_raw = spec.get("tools", [])
        if tools_raw is None:
            tools_raw = []
        if not isinstance(tools_raw, list) or not all(
            isinstance(t, str) and t for t in tools_raw
        ):
            raise HarnessRoutingError(
                f"rule[{index}]: 'tools' must be a list of non-empty "
                f"preferred_tools globs (e.g. 'ms_graph:*')."
            )

        if not role and not tools_raw:
            raise HarnessRoutingError(
                f"rule[{index}]: declare at least one matcher — "
                f"'role' (role-name glob) and/or 'tools' "
                f"(preferred_tools globs)."
            )
        rules.append(
            HarnessRoutingRule(
                harness=harness, role=role, tools=tuple(tools_raw)
            )
        )
    return tuple(rules)


def _tool_pattern_matches(pattern: str, preferred_tool: str) -> bool:
    """Match one rule glob against one ``source:operation`` entry.

    Patterns containing ``:`` match the full entry (``ms_graph:*``,
    ``outlook:send_mail``); bare patterns match the source prefix
    only, so ``ms_graph`` is shorthand for ``ms_graph:*``.
    """
    if ":" in pattern:
        return fnmatchcase(preferred_tool, pattern)
    source = preferred_tool.split(":", 1)[0]
    return fnmatchcase(source, pattern)


def rule_matches(
    rule: HarnessRoutingRule,
    role_name: str,
    preferred_tools: list[str] | tuple[str, ...],
) -> bool:
    """True when every declared matcher of ``rule`` matches the role.

    ``role`` matches by case-sensitive fnmatch on the role name;
    ``tools`` matches when ANY rule glob matches ANY preferred_tools
    entry. Declared matchers are ANDed (parse guarantees at least
    one is declared).
    """
    if rule.role and not fnmatchcase(role_name, rule.role):
        return False
    if rule.tools and not any(
        _tool_pattern_matches(pattern, pt)
        for pattern in rule.tools
        for pt in preferred_tools
    ):
        return False
    return True


def role_prefers_ms_tools(
    preferred_tools: list[str] | tuple[str, ...],
) -> bool:
    """True when any preferred_tools entry references an MS source."""
    return any(
        pt.split(":", 1)[0] in MS_TOOL_SOURCES for pt in preferred_tools
    )


__all__ = [
    "AUTO_HARNESS",
    "MS_TOOL_SOURCES",
    "HarnessRoutingError",
    "HarnessRoutingRule",
    "parse_harness_routing",
    "role_prefers_ms_tools",
    "rule_matches",
]
