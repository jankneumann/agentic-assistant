# a2a-server — A2A Protocol Server (P6)

## Why

External orchestrators (Copilot Studio, Omnigent-class meta-harnesses)
need a standards-based way to delegate tasks to this assistant
(roadmap row P6; perplexity §6/§8.5; guiding principle 7 —
standards-first seams: A2A is the adopted agent↔agent protocol per
`docs/architecture-analysis/2026-07-16-protocol-standards.md`). Today
the only serving surface is the AG-UI bridge (`/chat`), which is a
user-UI session channel, not an agent↔agent contract: no agent card
for discovery, no task lifecycle, no protocol-level multiplexing —
`web/app.py` binds ONE harness at startup, so concurrent external
tasks would interleave one conversation thread. P6 is also a
prerequisite surface for P22 meta-harness composition.

## What Changes

- **New `src/assistant/a2a/` package**:
  - `types.py` — hand-rolled, spec-shaped Pydantic models for A2A
    protocol version 0.3.0 (parts, Message, Task/TaskStatus/TaskState,
    Artifact, status/artifact update events, MessageSendParams,
    AgentCard, JSON-RPC 2.0 envelope + A2A error codes). NO new
    dependencies; the official `a2a-sdk` may replace these later
    (design.md D1).
  - `agent_card.py` — AgentCard built from persona + enabled roles
    (one A2A skill per role), advertising `capabilities.streaming`.
  - `task_handler.py` — in-memory `SessionRegistry`
    (create/lookup/expire by `thread_id` — the FIRST consumer of the
    harness-adapter spec's Session Registry requirement) plus
    `A2ATaskHandler` running the task lifecycle (submitted → working →
    completed/failed) over `SdkHarnessAdapter.astream_invoke`.
  - `server.py` — FastAPI route registration: agent card at
    `/.well-known/agent-card.json` AND legacy `/.well-known/agent.json`,
    JSON-RPC 2.0 `POST /a2a/v1` (`message/send`, `message/stream` over
    SSE), and a REST-style `POST /a2a/v1/message:stream` alias.
- **New `src/assistant/transports/a2a/mapper.py`** — a SECOND mapping
  over the SAME `HarnessEvent` vocabulary (AG-UI mapper untouched):
  HarnessEvent → A2A TaskStatusUpdateEvent / TaskArtifactUpdateEvent,
  honoring the two-phase D8 error contract with class-name-only
  redaction, and bridging approval denials
  (`ModelCallDeniedError`, P13 semantics) to the A2A `input-required`
  task state before the run fails (interrupt/resume NOT implemented —
  design.md D5).
- **CLI**: `assistant serve` gains an `--a2a` flag that mounts the A2A
  surface alongside AG-UI on the same loopback-default server
  (design.md D6 records why a flag, not a new subcommand).
- **Web app factory**: `make_app(..., enable_a2a=, a2a_base_url=)`
  builds the A2A state in the lifespan; A2A sessions are FRESH
  harness+agent pairs per A2A context via the same pipeline the AG-UI
  lifespan runs — the single AG-UI harness semantics are unchanged.

## Impact

- Affected specs: **ADDED** `a2a-server` capability; **MODIFIED**
  `cli-interface` (CLI serve Subcommand requirement — `--a2a` flag).
  The harness-adapter spec's Session Registry requirement is consumed
  (first implementation), not modified; `web-server` requirements are
  unchanged (new routes are additive and off by default).
- Affected code: new `src/assistant/a2a/`,
  `src/assistant/transports/a2a/`; `src/assistant/web/app.py`
  (optional A2A mount), `src/assistant/cli.py` (`--a2a` flag).
- Behavior preserved: `assistant serve` without `--a2a` is
  byte-for-byte the previous surface (no A2A routes registered; legacy
  `make_app(persona, role, harness)` call shape kept).
- Deferred (design.md D8): `tasks/get`/`tasks/cancel` JSON-RPC
  methods, push notifications, multi-turn task continuation
  (`input-required` resume), durable sessions (Postgres checkpointer),
  agent-card auth schemes (P25), official `a2a-sdk` adoption.
