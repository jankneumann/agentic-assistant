"""DelegationContext — rich delegation context (P12 delegation-context).

A :class:`DelegationContext` is the structured payload a parent agent
hands to a sub-agent alongside the task string: who delegated (parent
role), the full attributable principal for the hop (the P25
:class:`AgentIdentity` — the delegation chain lives THERE and is never
duplicated here), memory snippets retrieved under the SUB-role,
an optional parent-supplied conversation summary, and execution
constraints (remaining chain depth, optional deadline, optional tool
narrowing).

Harnesses serialize the context into the sub-agent's system prompt as
a ``## Delegation context`` block — mirroring the D27
``## Recent context`` prepend pattern — via :meth:`DelegationContext.render`.
Empty sections are omitted; a context with no snippets, no summary,
and no constraints still renders the identity header so a sub-agent
always knows it is acting under delegation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from assistant.core.capabilities.identity import AgentIdentity

#: Section heading for the rendered block — sibling of the D27
#: ``## Recent context`` heading used by the memory prepend.
DELEGATION_SECTION_HEADING: str = "## Delegation context"


def _format_constraint_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


@dataclass(frozen=True)
class DelegationContext:
    """Structured context flowing from a parent agent into a sub-agent.

    Attributes:
        parent_role: Name of the delegating (parent) role.
        identity: The CHILD principal for this hop (already derived via
            ``parent_identity.delegate_to(sub_role)``). The delegation
            chain is read from ``identity.delegation_chain`` — this
            dataclass deliberately does not carry its own copy.
        memory_snippets: Recent memory snippets fetched under the
            sub-role (parent-side retrieval; may be empty).
        conversation_summary: Optional parent-supplied one-paragraph
            summary of the conversation that led to this delegation.
        constraints: Execution constraints communicated to the
            sub-agent. Known keys: ``max_depth_remaining`` (int),
            ``deadline_seconds`` (float), ``allowed_tools``
            (list[str] narrowing). Open map — unknown keys render as
            plain ``key: value`` bullets.
    """

    parent_role: str
    identity: AgentIdentity
    memory_snippets: tuple[str, ...] = ()
    conversation_summary: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        """Render the ``## Delegation context`` prompt block.

        Mirrors the D27 ``## Recent context`` pattern: a markdown block
        prepended ahead of the composed system prompt. Sections with no
        content (summary / memory / constraints) are omitted entirely.
        """
        lines: list[str] = [
            DELEGATION_SECTION_HEADING,
            "",
            (
                f"You are acting as role '{self.identity.role}', delegated "
                f"by role '{self.parent_role}' "
                f"(persona '{self.identity.persona}')."
            ),
            (
                f"Delegation chain: {self.identity.chain_display()} "
                f"(depth {self.identity.chain_depth})."
            ),
        ]
        if self.conversation_summary:
            lines += ["", "### Conversation summary", "", self.conversation_summary]
        if self.memory_snippets:
            lines += ["", "### Relevant memory", ""]
            lines.append("\n\n".join(self.memory_snippets))
        if self.constraints:
            lines += ["", "### Constraints", ""]
            lines += [
                f"- {key}: {_format_constraint_value(value)}"
                for key, value in self.constraints.items()
            ]
        return "\n".join(lines)


__all__ = ["DELEGATION_SECTION_HEADING", "DelegationContext"]
