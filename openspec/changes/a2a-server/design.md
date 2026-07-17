# a2a-server — Design

## D1. Hand-rolled spec-shaped types; adopt `a2a-sdk` later

No new dependencies (mission constraint): `a2a/types.py` hand-rolls
the A2A 0.3.0 shapes as Pydantic v2 models with camelCase wire aliases
(`to_camel` generator, `populate_by_name=True`) and tolerant inbound
parsing (`extra="ignore"`). Field names, `kind` discriminators, and
the JSON-RPC/A2A error-code space match the spec exactly, so swapping
in the official `a2a-sdk` — once it stabilizes — is a mechanical
import substitution, not a re-mapping. Serialization is always
`model_dump(by_alias=True, exclude_none=True, mode="json")`.

## D2. Agent-card path naming: serve BOTH well-known paths

A2A 0.3.0 renamed the discovery document from
`/.well-known/agent.json` to `/.well-known/agent-card.json`. We serve
the SAME card at both paths: `agent-card.json` is canonical (current
spec), `agent.json` is a legacy alias kept for pre-0.3 clients
(Copilot Studio integrations in the wild still probe it). Recorded per
the roadmap instruction; drop the alias when the ecosystem finishes
migrating.

## D3. JSON-RPC surface: `POST /a2a/v1` + REST-style alias

Primary transport is JSONRPC (as advertised in the card's
`preferredTransport`): a single `POST /a2a/v1` accepting a JSON-RPC
2.0 envelope with methods `message/send` (blocking; result = terminal
Task) and `message/stream` (SSE; each SSE `data:` line is a full
JSON-RPC success envelope whose `result` is one A2A event, per the
JSONRPC-transport streaming rule). Protocol-level failures are HTTP
200 with a `JSONRPCErrorResponse` body (JSON-RPC-over-HTTP
convention); task-level failures are NOT protocol errors — they
surface as a terminal `failed` status. Additionally,
`POST /a2a/v1/message:stream` (the literal endpoint named in the
roadmap row) is a REST-style HTTP+JSON-transport alias: body is bare
`MessageSendParams`, SSE events are bare A2A objects without the
JSON-RPC envelope.

## D4. Session registry semantics (first consumer of the P24 contract)

`SessionRegistry` implements the harness-adapter spec's Session
Registry requirement in-memory: `create()` builds a FRESH harness +
agent through the injected session factory (the same
create_harness → agent-factory pipeline the web lifespan runs) and
keys the session by the harness's own `thread_id`; `lookup()` returns
the live session or `None` — it never silently creates; `expire()`
releases by id, and an idle-TTL sweep (default 3600 s, run
opportunistically on create/lookup) reclaims abandoned sessions.
A2A task↔session multiplexing: **A2A `contextId` ≡ session
`thread_id`**. A message without `contextId` starts a new session; a
known `contextId` reuses its session (serialized by a per-session
`asyncio.Lock`); an unknown `contextId` is REJECTED with
`InvalidParams` rather than silently recreated — sessions are
in-memory, and honest failure beats fake continuity. The durable
Postgres checkpointer (which would make expired thread_ids resumable
with history, per the Durable Session Persistence requirement) remains
deferred; when it lands, unknown-but-checkpointed contextIds can be
re-bound instead of rejected. Expiry never deletes durably
checkpointed state (there is none yet to delete).

## D5. input-required bridge (ApprovalRequest contract, P13 semantics)

The guardrail-provider spec's `ApprovalRequest` contract maps to the
A2A `input-required` task state on served surfaces (protocol-standards
doc, human-seam row). Interrupt/resume is NOT implemented (needs
durable sessions — capability-protocols-v2 contract 6), so the bridge
is observational: when a run terminates with an approval-denial error
class (leaf class name in `APPROVAL_DENIED_ERROR_CLASSES`, today
`ModelCallDeniedError` — raised by the model bindings when a guardrail
returns `require_confirmation=True`, which P13 defines as DENY until
the approval flow exists), the mapper emits a non-final
`TaskStatusUpdateEvent(state=input-required)` carrying an agent
message explaining that human confirmation was required, followed by
the final `failed` update. External orchestrators therefore see the
spec-correct state transition (working → input-required → failed)
instead of an opaque failure; when interrupt/resume lands, the same
detection point suspends instead of failing and the `failed` tail
disappears. Detection is by class name because `RunFinished.error` is
class-name-only by the D8 redaction rule.

## D6. CLI: `--a2a` flag on `serve`, not a new subcommand

The A2A surface shares the persona/role/harness binding, the loopback
default, the port, and the uvicorn lifecycle with the AG-UI server —
a separate `serve-a2a` subcommand would duplicate all of that grammar
for zero isolation benefit, and mounting both on one app is exactly
what P22/P23 want (one LAN-exposable process per persona). So:
`assistant serve -p <persona> --a2a`. The flag passes
`enable_a2a=True` and `a2a_base_url=http://<host>:<port>` to
`make_app`; without the flag the legacy `make_app(persona, role,
harness)` call shape is preserved exactly (kwargs only added when the
flag is set, so injected test fakes with the old signature keep
working).

## D7. Event mapping and error contract

`transports/a2a/mapper.py` is a sibling of the AG-UI mapper over the
SAME `HarnessEvent` vocabulary (the AG-UI mapper is untouched):

| HarnessEvent            | A2A event                                        |
|-------------------------|--------------------------------------------------|
| RunStarted              | TaskStatusUpdateEvent(working)                   |
| TextDelta(message_id=X) | TaskArtifactUpdateEvent(artifactId=X, TextPart); `append` None on first chunk, True after |
| ToolCallStart/Args/End  | dropped — A2A has no tool-call vocabulary; internal execution detail is not leaked to external orchestrators |
| RunFinished(error=None) | TaskStatusUpdateEvent(completed, final=true)     |
| RunFinished(error=cls)  | [input-required (D5) +] TaskStatusUpdateEvent(failed, final=true) |

Two-phase D8 contract: Phase 1 (terminal `RunFinished(error=…)`) maps
to the final `failed` update with class-name-only text; Phase 2
(re-raise) is absorbed by the mapper. A raw raise WITHOUT the Phase-1
terminal event propagates to the task handler, which synthesizes the
final `failed` update (class-name-only) so every A2A stream ends with
`final=true` — mirroring the AG-UI route's robustness path.
`lastChunk` is never set on artifact updates: the harness stream gives
no lookahead, and emitting an empty-parts "closing" update is worse
than omitting the optional field (recorded limitation).

## D8. Deferred scope

- `tasks/get` / `tasks/cancel` JSON-RPC methods (the handler keeps an
  in-memory task store, so `tasks/get` is a small follow-up).
- Multi-turn task continuation: a message carrying a known `taskId`
  returns `UnsupportedOperation` (-32004) until interrupt/resume
  exists; unknown `taskId` returns `TaskNotFound` (-32001).
- Push notifications (`capabilities.pushNotifications=false`).
- FilePart/DataPart inputs: parsed but rejected with
  `ContentTypeNotSupported` (-32005) — v1 is a text-only surface.
- Agent-card `securitySchemes` / authn — P25 `agent-iam`; the surface
  stays loopback-only by default (web-server posture) until then.
- Durable sessions + resumable contextIds — harness-adapter Durable
  Session Persistence (Postgres checkpointer).
- Official `a2a-sdk` adoption (D1).
- Agent Protocol (runs/threads REST) noted as a candidate sibling
  surface (protocol-standards doc) — not adopted.
