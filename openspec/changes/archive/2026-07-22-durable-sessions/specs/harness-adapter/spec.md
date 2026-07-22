# harness-adapter Specification (delta)

## MODIFIED Requirements

### Requirement: Durable Session Persistence

The system SHALL make SDK harness sessions durable through
checkpointer-backed persistence. For the DeepAgents harness this
adopts the LangGraph checkpointer interface rather than inventing a
session store: the harness SHALL accept an injected checkpointer at
construction time (`checkpointer` kwarg), keep a fresh `InMemorySaver`
as the un-injected default, and resolve a Postgres checkpointer
(`AsyncPostgresSaver` from `langgraph-checkpoint-postgres`) when the
persona declares `sessions: {durable: true}` AND a `database_url`
resolves. Durable savers SHALL be process-cached per database url and
their schema SHALL be created via the saver's own `setup()` on first
use — the checkpointer schema is package-owned and deliberately
separate from the assistant's alembic migrations. A durable
declaration without a resolvable database url MUST fail with an
actionable error rather than silently degrading to in-memory. The
harness SHALL additionally accept an explicit `thread_id` at
construction so a serving surface can re-bind an existing durable
conversation; when a durable checkpointer is configured, conversation
state keyed by `thread_id` — including runs suspended by the approval
interrupt contract — survives process restarts and is resumable by
`thread_id` alone. Other SDK harnesses SHALL expose the same
injection seam where their SDK permits; `MSAgentFrameworkHarness`
accepts the `thread_id` and `approval_store` seams, with durable
conversation persistence recorded as deferred (no `agent-framework`
checkpointer injection point).

#### Scenario: Checkpointer is injectable

- **WHEN** `DeepAgentsHarness` is constructed with an explicit
  checkpointer
- **AND** `create_agent(tools, extensions)` is called
- **THEN** the underlying agent MUST be constructed with that
  checkpointer instance
- **AND** omitting the injection MUST preserve the `InMemorySaver`
  default for non-durable personas

#### Scenario: Durable persona resolves the Postgres saver

- **WHEN** the persona declares `sessions: {durable: true}` with a
  resolvable database url
- **AND** `create_agent` is called without an injected checkpointer
- **THEN** the agent MUST be constructed with the resolved durable
  saver
- **AND** the saver MUST be built (and its `setup()` awaited) at most
  once per process and database url

#### Scenario: Durable without a database url fails actionably

- **WHEN** the persona declares `sessions: {durable: true}` but no
  database url resolves
- **THEN** checkpointer resolution MUST raise an error naming the
  missing configuration rather than silently using `InMemorySaver`

#### Scenario: Explicit thread_id re-binds a conversation

- **WHEN** a harness is constructed with `thread_id="t1"`
- **THEN** `harness.thread_id` MUST equal `"t1"` for the lifetime of
  the instance, so a durable checkpointer restores that
  conversation's prior turns

#### Scenario: Postgres-backed session survives a restart

- **WHEN** a conversation runs against a Postgres checkpointer with
  `thread_id="t1"`
- **AND** the process restarts and a new harness is constructed with
  the same checkpointer backend
- **THEN** invoking with `thread_id="t1"` MUST see the prior
  conversation history

#### Scenario: Suspended runs are resumable by thread_id

- **WHEN** a run on `thread_id="t2"` is suspended awaiting approval
  (guardrail-provider approval interrupt contract)
- **THEN** the suspended state MUST be recoverable from the durable
  checkpointer using `thread_id="t2"` alone

### Requirement: Session Registry

The system SHALL provide a session registry in the neutral module
`assistant/harnesses/sessions.py` (relocated from
`assistant.a2a.task_handler`, which keeps compatibility re-exports)
that creates, looks up, and expires sessions keyed by `thread_id`, so
serving surfaces (web transport, the P7 daemon, the P6 A2A server,
the P17 MCP server) can multiplex concurrent users and tasks instead
of binding one global harness at startup. `create` SHALL produce a
new session (persona/role-bound harness and agent) and return its
`thread_id`; `lookup` SHALL return the live session for a known
`thread_id` and signal unknown ids distinctly; `expire` SHALL release
a session's in-process resources by `thread_id` or idle TTL policy —
expiry releases the in-process session but MUST NOT delete durably
checkpointed state.

The registry SHALL additionally accept an optional durable tier: a
session-metadata store (rows: thread_id, persona, role, harness,
created_at, last_used, expires_at, status — persisted on create,
refreshed on lookup, best-effort so store failures never break
serving) and a `rebind_factory` that reconstructs a harness+agent
bound to a SPECIFIC `thread_id`. An async `resolve(thread_id)` SHALL
return the live session first, then — with the durable tier
configured — re-bind a known-`active`, un-lapsed metadata row for the
SAME role (the durable checkpointer restores the conversation), and
return the unknown signal only for truly unknown, lapsed
(`session_ttl_seconds` from persona config; 0 = never), expired, or
foreign-role ids. Without the durable tier `resolve` degrades exactly
to `lookup`.

#### Scenario: Registry multiplexes concurrent sessions

- **WHEN** two sessions are created for the same persona and role
- **THEN** they MUST have distinct `thread_id` values
- **AND** invoking one session MUST NOT observe messages from the
  other

#### Scenario: Lookup returns the live session

- **WHEN** a session is created with `thread_id="t1"`
- **AND** `lookup("t1")` is called before expiry
- **THEN** it MUST return the same session instance

#### Scenario: Unknown thread_id is signaled distinctly

- **WHEN** `lookup("never-created")` is called
- **THEN** the registry MUST signal an unknown-session condition
  (error or `None` per implementation) rather than silently creating
  a new session

#### Scenario: Expiry releases the session but not durable state

- **WHEN** a session with the durable tier configured is expired
  in-process
- **AND** `resolve` is called with the same `thread_id`
- **THEN** the registry MUST re-bind a fresh harness to that
  `thread_id` via the rebind factory
- **AND** the prior conversation history MUST still be visible to the
  re-bound session (checkpointer-restored)

#### Scenario: Lapsed durable session is rejected

- **WHEN** a durable metadata row's `expires_at` has passed (or its
  status is `expired`)
- **AND** `resolve` is called with that `thread_id`
- **THEN** the registry MUST signal unknown and MUST NOT re-bind

#### Scenario: Foreign-role session is not re-bound

- **WHEN** a durable row was recorded under role `coder`
- **AND** a registry bound to role `writer` resolves that `thread_id`
- **THEN** the registry MUST signal unknown

#### Scenario: Relocation preserves the old import path

- **WHEN** code imports `SessionRegistry` from
  `assistant.a2a.task_handler`
- **THEN** it MUST receive the same class as
  `assistant.harnesses.sessions.SessionRegistry`
