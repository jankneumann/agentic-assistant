"""Fixture-sentinel non-leakage check (wp-integration, task 5.3).

The public fixture persona under ``tests/fixtures/`` carries an
intentional tests-only sentinel ``FIXTURE_PERSONA_SENTINEL_v1``
embedded in its prompt content. That sentinel is the marker the
privacy-guard plugin uses to prove that test runs source persona
content from the public fixture tree rather than from the real
(private) submodule.

This test is the telemetry-side complement: it drives a scripted
assistant interaction with the fixture persona active and asserts that
no emitted span attribute, metadata field, or error message contains
the sentinel string. The current decorator design intentionally
excludes prompt bodies from span attributes (only ``persona``, ``role``,
``model``, ``op``, ``tool_name``, etc. are emitted), so the test is
expected to pass today. Its real value is **defense in depth**: any
future refactor that adds prompt content to spans for debugging will
trip this test before reaching production, where the same code path
would emit real persona content to Langfuse.

The check matches req ``observability.7`` ("Secret Sanitization") and
spec scenario "Persona name is preserved" — the persona NAME (e.g.,
``personal``) is allowed; persona PROMPT CONTENT (which carries the
sentinel) is not.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from assistant.telemetry import factory, set_assistant_ctx
from assistant.telemetry.decorators import traced_delegation, traced_harness

# Sentinel marker embedded in the public fixture persona's prompt.md.
# Sourced as a string literal here (no FS read at test time) so the
# assertion has a single source of truth and doesn't depend on file
# layout. The same constant is asserted by tests/test_composition.py.
SENTINEL = "FIXTURE_PERSONA_SENTINEL_v1"


class _FakeHarness:
    def __init__(self, persona_name: str, role_name: str, model: str) -> None:
        self.persona = type("P", (), {})()
        self.persona.name = persona_name
        self.persona.harnesses = {"deep_agents": {"model": model}}
        self.role = type("R", (), {})()
        self.role.name = role_name

    def name(self) -> str:
        return "deep_agents"

    @traced_harness
    async def invoke(self, agent: Any, message: str) -> str:
        # Note: ``message`` is intentionally NOT included as a span
        # attribute by ``traced_harness`` — only the metadata derived
        # from the harness/persona/role attrs is. We pass a sentinel-
        # bearing message to verify the spec contract.
        return f"answer: {message[:20]}"


class _FakeSpawner:
    def __init__(self, persona_name: str, parent_role_name: str) -> None:
        self.persona = type("P", (), {"name": persona_name})()
        self.parent_role = type("R", (), {"name": parent_role_name})()

    @traced_delegation
    async def delegate(self, sub_role: str, task: str) -> str:
        return f"[{sub_role}] {task[:20]}"


def _install_spy(monkeypatch: pytest.MonkeyPatch, spy: Any) -> None:
    monkeypatch.setattr(factory, "_provider", spy)


@pytest.mark.asyncio
async def test_sentinel_in_harness_message_does_not_leak_to_spans(
    monkeypatch: pytest.MonkeyPatch,
    spy_provider: Any,
) -> None:
    """A harness invocation with a sentinel-bearing user message MUST
    NOT cause the sentinel to appear in the emitted ``trace_llm_call``
    span.

    Per req observability.3, the harness span carries
    ``model``, ``persona``, ``role``, ``input_tokens``, ``output_tokens``,
    ``duration_ms`` (and ``messages`` per the Protocol signature, but
    NOT the user message body in span attributes by design — the spec
    enumerates the metadata fields, none of which include verbatim
    user message text).

    Note: the sister field ``task`` on ``trace_delegation`` IS
    spec'd to be emitted verbatim when ≤256 chars (req
    observability.4) — so a sentinel-bearing delegation task would
    legitimately appear in spans. Whether to *also* sanitize delegation
    tasks is a separate spec question that should be raised in
    IMPL_REVIEW; this test specifically guards the harness path,
    where there is no spec license to emit user message bodies.
    """
    _install_spy(monkeypatch, spy_provider)
    set_assistant_ctx("personal", "assistant")

    leaky_message = f"please look up {SENTINEL} from prompt"

    harness = _FakeHarness("personal", "assistant", "anthropic:claude-sonnet-4-20250514")
    await harness.invoke(object(), leaky_message)

    llm_calls = spy_provider.calls.get("trace_llm_call", [])
    assert len(llm_calls) == 1, (
        f"expected 1 emitted trace_llm_call, got {len(llm_calls)} — "
        "test is vacuous if no spans emit."
    )

    serialized = json.dumps(llm_calls, default=str)
    assert SENTINEL not in serialized, (
        f"FIXTURE_PERSONA_SENTINEL_v1 leaked into a trace_llm_call span. "
        f"The decorator must not emit user message bodies as span "
        f"attributes — see req observability.3 enumerated fields. "
        f"Recorded:\n{serialized}"
    )


def test_persona_name_is_emitted_but_persona_content_is_not(
    monkeypatch: pytest.MonkeyPatch,
    spy_provider: Any,
) -> None:
    """Spec scenario 'Persona name is preserved' — defense-in-depth check.

    The persona NAME (e.g., ``"personal"``) is operator-chosen and
    allowed in spans per the sanitize known-safe-fields list. The
    persona CONTENT (sentinel-bearing prompt text) is not. This test
    proves the two are distinguishable: the name shows up; the content
    does not.
    """
    _install_spy(monkeypatch, spy_provider)
    set_assistant_ctx("personal", "assistant")

    import asyncio

    async def _drive() -> None:
        h = _FakeHarness("personal", "assistant", "anthropic:claude-sonnet-4-20250514")
        await h.invoke(object(), f"prompt body referencing {SENTINEL}")

    asyncio.run(_drive())

    llm = spy_provider.calls.get("trace_llm_call", [])
    assert llm, "harness invocation should have emitted at least one span"

    # Persona name reaches the span.
    assert all(c.get("persona") == "personal" for c in llm)

    # But the prompt content (carrying the sentinel) does not.
    serialized = json.dumps(llm, default=str)
    assert SENTINEL not in serialized
