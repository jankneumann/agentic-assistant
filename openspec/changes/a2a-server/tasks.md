# a2a-server — Tasks

## 1. Protocol types + mapper

- [x] 1.1 `a2a/types.py` — spec-shaped Pydantic models (parts,
  Message, Task/TaskStatus/TaskState, Artifact, status/artifact
  update events, MessageSendParams, AgentCard, JSON-RPC envelope +
  A2A error codes; camelCase aliases, tolerant inbound parsing)
- [x] 1.2 `transports/a2a/mapper.py` — HarnessEvent → A2A events
  (working/artifact/completed/failed mapping, tool-call events
  dropped, two-phase D8 absorption, input-required approval bridge)

## 2. Agent card + task lifecycle

- [x] 2.1 `a2a/agent_card.py` — persona + enabled roles → AgentCard
  (one skill per role, streaming capability, `{base}/a2a/v1` url)
- [x] 2.2 `a2a/task_handler.py` — in-memory `SessionRegistry`
  (create/lookup/expire by thread_id, idle TTL, per-session lock;
  first consumer of the harness-adapter Session Registry requirement)
- [x] 2.3 `a2a/task_handler.py` — `A2ATaskHandler`: contextId↔session
  resolution, task store, message/stream generator (initial Task
  snapshot + mapped events + synthesized failed terminal on raw
  raise), blocking message/send

## 3. Server surface + wiring

- [x] 3.1 `a2a/server.py` — `build_a2a_state` + `register_a2a_routes`:
  agent card at `/.well-known/agent-card.json` + legacy
  `/.well-known/agent.json`, JSON-RPC `POST /a2a/v1`
  (message/send + message/stream SSE), REST alias
  `POST /a2a/v1/message:stream`
- [x] 3.2 `web/app.py` — `make_app(enable_a2a=, a2a_base_url=)`:
  lifespan builds A2A state with a fresh-harness session factory
  (same pipeline as the AG-UI harness); routes registered only when
  enabled
- [x] 3.3 `cli.py` — `assistant serve --a2a` (legacy call shape kept
  when the flag is absent; startup echo of the agent-card URL)

## 4. Tests

- [x] 4.1 `tests/transports/a2a/test_mapper.py` — lifecycle mapping,
  artifact append semantics, tool-call drop, two-phase error,
  input-required bridge, raw-raise propagation
- [x] 4.2 `tests/a2a/test_session_registry.py` — create/lookup/expire,
  distinct thread_ids, idle TTL, duplicate-id rejection
- [x] 4.3 `tests/a2a/test_task_handler.py` — send happy path, stream
  sequence, synthesized failure, multi-task multiplexing,
  contextId reuse, taskId/parts validation errors
- [x] 4.4 `tests/a2a/test_agent_card.py` — roles→skills, streaming
  capability, camelCase wire shape
- [x] 4.5 `tests/a2a/test_server.py` — both well-known card paths,
  JSON-RPC envelope errors (-32700/-32600/-32601/-32602),
  message/send + message/stream over HTTP, REST alias
- [x] 4.6 `tests/web/test_a2a_mount.py` + `tests/cli/test_serve_a2a.py`
  — mount alongside AG-UI, fresh-session isolation, flag wiring,
  legacy call-shape preservation

## 5. Docs

- [x] 5.1 CLAUDE.md — A2A section (endpoints, flag, deferred scope)
- [x] 5.2 OpenSpec deltas — ADDED `a2a-server`, MODIFIED
  `cli-interface`; `openspec validate a2a-server --strict` green
