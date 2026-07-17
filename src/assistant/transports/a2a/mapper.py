"""A2A mapper: HarnessEvent async-iterator → A2A protocol event async-iterator.

Transport-agnostic; knows nothing about HTTP, SSE, FastAPI, or JSON-RPC.

Contract: ``map_harness_to_a2a(stream, *, task_id, context_id)`` is an
async generator function returning an ``AsyncIterator`` of
``TaskStatusUpdateEvent | TaskArtifactUpdateEvent``.

Import direction (mirrors the AG-UI mapper's D6):
  - ``assistant.harnesses.sdk.events``  (downward — harness layer)
  - ``assistant.a2a.types``             (spec-shaped protocol types)

Nothing in this module may import from ``assistant.web`` or
``assistant.a2a.server``.

Event mapping (one HarnessEvent vocabulary, second protocol mapping):

  RunStarted                → TaskStatusUpdateEvent(state=working)
  TextDelta(message_id=X)   → TaskArtifactUpdateEvent(artifactId=X,
                              parts=[TextPart]); ``append`` is None on the
                              first chunk of an artifact and True after
  ToolCallStart/Args/End    → dropped (A2A has no tool-call vocabulary;
                              tool activity is an internal execution
                              detail — do not leak it to external
                              orchestrators)
  RunFinished(error=None)   → TaskStatusUpdateEvent(state=completed,
                              final=True)
  RunFinished(error=cls)    → TaskStatusUpdateEvent(state=failed,
                              final=True); class-name-only redaction is
                              preserved end-to-end (D8 rule)

Approval bridge (P13 semantics, guardrail-provider ApprovalRequest
contract): when the terminal error class is an approval-denial class
(default: ``ModelCallDeniedError`` — raised when a guardrail returns
``require_confirmation=True`` and no interrupt/resume flow exists), the
mapper first emits a non-final ``TaskStatusUpdateEvent(state=
input-required)`` carrying an agent message, THEN the final ``failed``
update. External orchestrators see the A2A-standard "this needed human
input" state; the run still denies because suspend/resume is deferred to
the durable-session work (capability-protocols-v2).

Two-phase D8 error contract
----------------------------
Phase 1: harness yields terminal ``RunFinished(error='<ClassName>')`` —
  mapper emits the (optional input-required +) final failed update.
Phase 2: harness re-raises the original exception — mapper absorbs it.
Raw raise (misbehaving harness, no Phase-1 terminal event): the
exception propagates unchanged; the server layer synthesizes the final
failed update (mirroring the AG-UI route's robustness handling).
"""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator
from typing import Final

from assistant.a2a.types import (
    Artifact,
    Message,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from assistant.harnesses.sdk.events import (
    HarnessEvent,
    RunFinished,
    RunStarted,
    TextDelta,
)

# Exception class names (leaf, unqualified) whose terminal RunFinished
# signals "a guardrail wanted human confirmation". P13 semantics:
# require_confirmation on model_call DENIES until the approval
# interrupt/resume flow exists, and ModelCallDeniedError is the class
# both SDK harness bindings raise for that denial
# (core/capabilities/model_bindings.py).
APPROVAL_DENIED_ERROR_CLASSES: Final[frozenset[str]] = frozenset(
    {"ModelCallDeniedError"}
)

_INPUT_REQUIRED_NOTE = (
    "A guardrail requires human confirmation for this action ({cls}). "
    "Approval interrupt/resume is not implemented yet; the task will "
    "now fail (deny-by-default per security-hardening P13)."
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


async def map_harness_to_a2a(
    stream: AsyncIterator[HarnessEvent],
    *,
    task_id: str,
    context_id: str,
    approval_denied_classes: frozenset[str] = APPROVAL_DENIED_ERROR_CLASSES,
) -> AsyncIterator[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
    """Map a ``HarnessEvent`` async iterator to A2A task events.

    Args:
        stream: Async iterator of ``HarnessEvent`` instances from a
            harness's ``astream_invoke()`` call.
        task_id: A2A task identifier (keyword-only, non-empty).
        context_id: A2A context identifier — the session ``thread_id``
            the task is multiplexed onto (keyword-only, non-empty).
        approval_denied_classes: leaf exception-class names treated as
            approval denials (input-required bridge).

    Yields:
        ``TaskStatusUpdateEvent`` / ``TaskArtifactUpdateEvent`` in
        protocol order. The final event of a run is always a
        status-update with ``final=True`` (completed or failed) when the
        harness honors the two-phase contract.

    Raises:
        ValueError: if ``task_id`` or ``context_id`` is empty.
        Any exception raised by a misbehaving harness that skips the
        terminal ``RunFinished`` (raw raise without the Phase-1 signal).
    """
    if not task_id:
        raise ValueError("task_id must be a non-empty string")
    if not context_id:
        raise ValueError("context_id must be a non-empty string")

    # Artifact ids we have already opened — decides append semantics.
    seen_artifacts: set[str] = set()
    terminal_emitted = False

    try:
        async for event in stream:
            if isinstance(event, RunStarted):
                yield TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(state=TaskState.WORKING, timestamp=_now()),
                )

            elif isinstance(event, TextDelta):
                first_chunk = event.message_id not in seen_artifacts
                seen_artifacts.add(event.message_id)
                yield TaskArtifactUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    artifact=Artifact(
                        artifact_id=event.message_id,
                        parts=[TextPart(text=event.text)],
                    ),
                    append=None if first_chunk else True,
                )

            elif isinstance(event, RunFinished):
                terminal_emitted = True
                if event.error is None:
                    yield TaskStatusUpdateEvent(
                        task_id=task_id,
                        context_id=context_id,
                        status=TaskStatus(
                            state=TaskState.COMPLETED, timestamp=_now()
                        ),
                        final=True,
                    )
                else:
                    leaf = event.error.rsplit(".", 1)[-1]
                    if leaf in approval_denied_classes:
                        # ApprovalRequest bridge: surface the A2A
                        # input-required state before the deny-fail.
                        yield TaskStatusUpdateEvent(
                            task_id=task_id,
                            context_id=context_id,
                            status=TaskStatus(
                                state=TaskState.INPUT_REQUIRED,
                                message=Message(
                                    role="agent",
                                    parts=[
                                        TextPart(
                                            text=_INPUT_REQUIRED_NOTE.format(
                                                cls=leaf
                                            )
                                        )
                                    ],
                                    message_id=f"{task_id}-input-required",
                                    task_id=task_id,
                                    context_id=context_id,
                                ),
                                timestamp=_now(),
                            ),
                        )
                    # Class-name-only redaction (D8) carried through.
                    yield TaskStatusUpdateEvent(
                        task_id=task_id,
                        context_id=context_id,
                        status=TaskStatus(
                            state=TaskState.FAILED,
                            message=Message(
                                role="agent",
                                parts=[TextPart(text=event.error)],
                                message_id=f"{task_id}-failure",
                                task_id=task_id,
                                context_id=context_id,
                            ),
                            timestamp=_now(),
                        ),
                        final=True,
                    )
            # ToolCallStart / ToolCallArgs / ToolCallEnd: intentionally
            # dropped — internal execution detail, no A2A vocabulary.

    except Exception:
        if terminal_emitted:
            # Phase 2 of the D8 contract: absorb the re-raise.
            return
        # Misbehaving harness — propagate so the bug is observable.
        raise
