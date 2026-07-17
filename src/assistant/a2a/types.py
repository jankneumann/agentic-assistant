"""A2A protocol types — spec-shaped Pydantic models (hand-rolled, no SDK dep).

Models mirror the A2A specification (Linux Foundation, protocol version
0.3.0) closely enough that migrating to the official ``a2a-sdk`` package —
once it stabilizes — is a mechanical import swap: field names are the
spec's camelCase on the wire (via ``to_camel`` aliases) and snake_case in
Python, and the discriminated unions use the spec's ``kind`` literals.

Scope (v1): TextPart / FilePart / DataPart, Message, Task + TaskStatus +
TaskState, Artifact, TaskStatusUpdateEvent / TaskArtifactUpdateEvent,
MessageSendParams (+ configuration), AgentCard (+ capabilities, skills,
provider), and the JSON-RPC 2.0 envelope with the A2A error-code space.

Serialization convention: always ``model_dump(by_alias=True,
exclude_none=True)`` so wire payloads are camelCase and omit nulls.
Inbound parsing is tolerant (``extra="ignore"``) so newer-spec clients
don't break us.
"""

from __future__ import annotations

import enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

A2A_PROTOCOL_VERSION = "0.3.0"


class A2ABaseModel(BaseModel):
    """Base config: camelCase wire aliases, tolerant inbound parsing."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------


class TextPart(A2ABaseModel):
    kind: Literal["text"] = "text"
    text: str
    metadata: dict[str, Any] | None = None


class FilePart(A2ABaseModel):
    """File content part. v1 accepts the shape but the server rejects it
    with ``ContentTypeNotSupported`` (text-only surface for now)."""

    kind: Literal["file"] = "file"
    # FileWithBytes | FileWithUri in the spec; kept as an open mapping so
    # inbound messages parse without us modeling both variants yet.
    file: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] | None = None


class DataPart(A2ABaseModel):
    kind: Literal["data"] = "data"
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] | None = None


Part = Annotated[TextPart | FilePart | DataPart, Field(discriminator="kind")]


# ---------------------------------------------------------------------------
# Message / Task / Artifact
# ---------------------------------------------------------------------------


class Message(A2ABaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]
    message_id: str = Field(..., min_length=1)
    task_id: str | None = None
    context_id: str | None = None
    kind: Literal["message"] = "message"
    metadata: dict[str, Any] | None = None


class TaskState(enum.StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"
    AUTH_REQUIRED = "auth-required"
    UNKNOWN = "unknown"


class TaskStatus(A2ABaseModel):
    state: TaskState
    message: Message | None = None
    timestamp: str | None = Field(
        default=None, description="ISO 8601 UTC timestamp."
    )


class Artifact(A2ABaseModel):
    artifact_id: str = Field(..., min_length=1)
    name: str | None = None
    description: str | None = None
    parts: list[Part] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class Task(A2ABaseModel):
    id: str = Field(..., min_length=1)
    context_id: str = Field(..., min_length=1)
    status: TaskStatus
    artifacts: list[Artifact] | None = None
    history: list[Message] | None = None
    kind: Literal["task"] = "task"
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------


class TaskStatusUpdateEvent(A2ABaseModel):
    task_id: str = Field(..., min_length=1)
    context_id: str = Field(..., min_length=1)
    status: TaskStatus
    final: bool = False
    kind: Literal["status-update"] = "status-update"
    metadata: dict[str, Any] | None = None


class TaskArtifactUpdateEvent(A2ABaseModel):
    task_id: str = Field(..., min_length=1)
    context_id: str = Field(..., min_length=1)
    artifact: Artifact
    append: bool | None = None
    last_chunk: bool | None = None
    kind: Literal["artifact-update"] = "artifact-update"
    metadata: dict[str, Any] | None = None


# Everything a message/stream SSE stream may carry as a JSON-RPC result.
A2AStreamEvent = Task | Message | TaskStatusUpdateEvent | TaskArtifactUpdateEvent


# ---------------------------------------------------------------------------
# message/send params
# ---------------------------------------------------------------------------


class MessageSendConfiguration(A2ABaseModel):
    accepted_output_modes: list[str] | None = None
    blocking: bool | None = None
    history_length: int | None = None


class MessageSendParams(A2ABaseModel):
    message: Message
    configuration: MessageSendConfiguration | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Agent card
# ---------------------------------------------------------------------------


class AgentCapabilities(A2ABaseModel):
    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False


class AgentSkill(A2ABaseModel):
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    examples: list[str] | None = None
    input_modes: list[str] | None = None
    output_modes: list[str] | None = None


class AgentProvider(A2ABaseModel):
    organization: str
    url: str | None = None


class AgentCard(A2ABaseModel):
    protocol_version: str = A2A_PROTOCOL_VERSION
    name: str
    description: str = ""
    url: str
    preferred_transport: str = "JSONRPC"
    version: str
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    default_input_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    default_output_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    skills: list[AgentSkill] = Field(default_factory=list)
    provider: AgentProvider | None = None


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 envelope + A2A error space
# ---------------------------------------------------------------------------

# Standard JSON-RPC 2.0 codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# A2A-specific codes.
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
PUSH_NOTIFICATION_NOT_SUPPORTED = -32003
UNSUPPORTED_OPERATION = -32004
CONTENT_TYPE_NOT_SUPPORTED = -32005
INVALID_AGENT_RESPONSE = -32006


class JSONRPCRequest(A2ABaseModel):
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str = Field(..., min_length=1)
    params: dict[str, Any] | None = None


class JSONRPCError(A2ABaseModel):
    code: int
    message: str
    data: Any = None


class JSONRPCSuccessResponse(A2ABaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: Any = None


class JSONRPCErrorResponse(A2ABaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    error: JSONRPCError


class A2AProtocolError(Exception):
    """Raised by the task handler for protocol-level failures.

    Carries the JSON-RPC error code so the server layer can render a
    ``JSONRPCErrorResponse`` (or the bare-error shape on the REST-style
    alias) without string matching.
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_error(self) -> JSONRPCError:
        return JSONRPCError(code=self.code, message=self.message, data=self.data)


__all__ = [
    "A2A_PROTOCOL_VERSION",
    "CONTENT_TYPE_NOT_SUPPORTED",
    "INTERNAL_ERROR",
    "INVALID_AGENT_RESPONSE",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "PUSH_NOTIFICATION_NOT_SUPPORTED",
    "TASK_NOT_CANCELABLE",
    "TASK_NOT_FOUND",
    "UNSUPPORTED_OPERATION",
    "A2ABaseModel",
    "A2AProtocolError",
    "A2AStreamEvent",
    "AgentCapabilities",
    "AgentCard",
    "AgentProvider",
    "AgentSkill",
    "Artifact",
    "DataPart",
    "FilePart",
    "JSONRPCError",
    "JSONRPCErrorResponse",
    "JSONRPCRequest",
    "JSONRPCSuccessResponse",
    "Message",
    "MessageSendConfiguration",
    "MessageSendParams",
    "Part",
    "Task",
    "TaskArtifactUpdateEvent",
    "TaskState",
    "TaskStatus",
    "TaskStatusUpdateEvent",
    "TextPart",
]
