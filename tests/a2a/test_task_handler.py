"""A2ATaskHandler tests — task lifecycle, session multiplexing, errors."""

from __future__ import annotations

import pytest

from assistant.a2a.task_handler import (
    A2ATaskHandler,
    SessionRegistry,
    apply_artifact_text,
)
from assistant.a2a.types import (
    CONTENT_TYPE_NOT_SUPPORTED,
    INVALID_PARAMS,
    TASK_NOT_FOUND,
    UNSUPPORTED_OPERATION,
    A2AProtocolError,
    MessageSendParams,
    Task,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)
from tests.a2a.helpers import (
    make_session_factory,
    text_events,
    user_message_payload,
)


def _params(**kw) -> MessageSendParams:
    return MessageSendParams.model_validate(user_message_payload(**kw))


def _handler(events=None) -> tuple[A2ATaskHandler, list]:
    factory, created = make_session_factory(events)
    return A2ATaskHandler(SessionRegistry(factory)), created


# ---------------------------------------------------------------------------
# message/send happy path
# ---------------------------------------------------------------------------


async def test_message_send_returns_completed_task_with_artifact_text():
    handler, created = _handler(text_events("Hello", " world"))
    task = await handler.handle_message_send(_params(text="hi there"))
    assert isinstance(task, Task)
    assert task.status.state is TaskState.COMPLETED
    assert task.context_id == created[0].thread_id
    assert apply_artifact_text(task) == "Hello world"
    # The harness received the extracted text.
    assert created[0].invocations == ["hi there"]


async def test_message_send_task_lifecycle_recorded_in_store():
    handler, _ = _handler()
    task = await handler.handle_message_send(_params())
    stored = handler.get_task(task.id)
    assert stored is not None
    assert stored.status.state is TaskState.COMPLETED


async def test_message_send_history_contains_incoming_message():
    handler, _ = _handler()
    task = await handler.handle_message_send(_params(text="remember me"))
    assert task.history is not None and len(task.history) == 1
    assert task.history[0].task_id == task.id
    assert task.history[0].context_id == task.context_id


# ---------------------------------------------------------------------------
# message/stream event sequence
# ---------------------------------------------------------------------------


async def test_message_stream_sequence_submitted_working_completed():
    handler, _ = _handler(text_events("chunk"))
    events = [
        e async for e in handler.handle_message_stream(_params())
    ]
    # Task snapshot first (submitted), then working, artifact, completed.
    assert isinstance(events[0], Task)
    assert events[0].status.state is TaskState.SUBMITTED
    assert isinstance(events[1], TaskStatusUpdateEvent)
    assert events[1].status.state is TaskState.WORKING
    terminal = events[-1]
    assert isinstance(terminal, TaskStatusUpdateEvent)
    assert terminal.status.state is TaskState.COMPLETED
    assert terminal.final is True


async def test_message_stream_misbehaving_harness_synthesizes_failed():
    """Raw raise without Phase-1 terminal → synthesized final failed
    update with class-name-only redaction."""
    from tests.a2a.helpers import make_run_started

    factory, _ = make_session_factory([make_run_started()])
    # Attach the raise to every harness the factory builds.
    async def _raising_factory():
        harness, agent = await factory()
        harness._raise_after = RuntimeError("secret-path /etc/shadow")
        return harness, agent

    handler = A2ATaskHandler(SessionRegistry(_raising_factory))
    events = [e async for e in handler.handle_message_stream(_params())]
    terminal = events[-1]
    assert isinstance(terminal, TaskStatusUpdateEvent)
    assert terminal.final is True
    assert terminal.status.state is TaskState.FAILED
    assert terminal.status.message is not None
    part = terminal.status.message.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "RuntimeError"
    assert "secret-path" not in part.text


# ---------------------------------------------------------------------------
# Session multiplexing
# ---------------------------------------------------------------------------


async def test_two_sends_without_context_create_distinct_sessions():
    handler, created = _handler()
    t1 = await handler.handle_message_send(_params())
    t2 = await handler.handle_message_send(_params())
    assert t1.context_id != t2.context_id
    assert len(created) == 2
    assert created[0].invocations == ["hello"]
    assert created[1].invocations == ["hello"]


async def test_send_with_known_context_reuses_session():
    handler, created = _handler()
    t1 = await handler.handle_message_send(_params(text="first"))
    t2 = await handler.handle_message_send(
        _params(text="second", context_id=t1.context_id)
    )
    assert t2.context_id == t1.context_id
    assert len(created) == 1
    assert created[0].invocations == ["first", "second"]
    assert t1.id != t2.id  # distinct tasks multiplexed on one session


async def test_unknown_context_id_rejected():
    handler, _ = _handler()
    with pytest.raises(A2AProtocolError) as exc_info:
        await handler.handle_message_send(
            _params(context_id="never-created")
        )
    assert exc_info.value.code == INVALID_PARAMS


# ---------------------------------------------------------------------------
# taskId continuation / validation errors
# ---------------------------------------------------------------------------


async def test_known_task_id_continuation_unsupported():
    handler, _ = _handler()
    done = await handler.handle_message_send(_params())
    with pytest.raises(A2AProtocolError) as exc_info:
        await handler.handle_message_send(
            _params(context_id=done.context_id, task_id=done.id)
        )
    assert exc_info.value.code == UNSUPPORTED_OPERATION


async def test_unknown_task_id_is_task_not_found():
    handler, _ = _handler()
    with pytest.raises(A2AProtocolError) as exc_info:
        await handler.handle_message_send(_params(task_id="no-such-task"))
    assert exc_info.value.code == TASK_NOT_FOUND


async def test_non_text_parts_rejected():
    handler, _ = _handler()
    payload = user_message_payload()
    payload["message"]["parts"] = [{"kind": "data", "data": {"k": "v"}}]
    with pytest.raises(A2AProtocolError) as exc_info:
        await handler.handle_message_send(
            MessageSendParams.model_validate(payload)
        )
    assert exc_info.value.code == CONTENT_TYPE_NOT_SUPPORTED


async def test_empty_parts_rejected():
    handler, _ = _handler()
    payload = user_message_payload()
    payload["message"]["parts"] = []
    with pytest.raises(A2AProtocolError) as exc_info:
        await handler.handle_message_send(
            MessageSendParams.model_validate(payload)
        )
    assert exc_info.value.code == INVALID_PARAMS
