# observability Specification Delta

## ADDED Requirements

### Requirement: Observability Provider Contract

The system SHALL define an `ObservabilityProvider` Protocol at `src/assistant/telemetry/providers/base.py` that every concrete provider (`noop`, `langfuse`, and any future adapter) MUST implement. The Protocol SHALL expose exactly these methods:

- `name` property returning the provider's registered string identifier.
- `setup(app=None)` called once during app startup to perform lazy provider initialization.
- `trace_llm_call(*, model, persona, role, messages, input_tokens, output_tokens, duration_ms, metadata=None)` recording a harness invocation as an LLM call.
- `trace_delegation(*, parent_role, sub_role, task, persona, duration_ms, outcome, metadata=None)` recording a delegation hop.
- `trace_tool_call(*, tool_name, tool_kind, persona, role, duration_ms, error=None, metadata=None)` recording any LangChain StructuredTool or HTTP-discovered tool invocation. The `tool_kind` parameter MUST be one of `"extension"` or `"http"`.
- `trace_memory_op(*, op, target, persona, duration_ms, metadata=None)` recording any memory or Graphiti knowledge-layer operation. The `op` parameter MUST be one of `"read"`, `"write"`, `"recall"`, `"episode_add"`, or `"graph_query"`.
- `start_span(name, attributes=None)` returning a context manager for arbitrary named spans that do not fit any first-class method.
- `flush()` triggering an immediate send of buffered events.
- `shutdown()` called during process exit to drain buffers and release resources.

The Protocol SHALL be decorated with `@runtime_checkable` so `isinstance(obj, ObservabilityProvider)` checks work at runtime.

#### Scenario: Noop implements the full Protocol surface

- **WHEN** `isinstance(NoopProvider(), ObservabilityProvider)` is evaluated
- **THEN** the result MUST be `True`
- **AND** every method listed above MUST be callable with valid arguments without raising

#### Scenario: Langfuse implements the full Protocol surface

- **WHEN** `isinstance(LangfuseProvider(), ObservabilityProvider)` is evaluated
- **THEN** the result MUST be `True`
- **AND** every Protocol method MUST be present on the instance

#### Scenario: Rejects mis-typed tool_kind

- **WHEN** `trace_tool_call(tool_kind="database", ...)` is invoked on any provider
- **THEN** a `ValueError` MUST be raised identifying the invalid `tool_kind`
- **AND** no span SHALL be emitted

#### Scenario: Rejects mis-typed op value

- **WHEN** `trace_memory_op(op="READ", ...)` is invoked on any provider (any value outside the fixed set `{"read", "write", "recall", "episode_add", "graph_query"}`, including the wrong-case `"READ"`)
- **THEN** a `ValueError` MUST be raised identifying the invalid `op`
- **AND** no span SHALL be emitted

### Requirement: Graceful Degradation Across Three Levels

The telemetry factory `get_observability_provider()` at `src/assistant/telemetry/factory.py` SHALL return a functional provider under every one of these failure conditions without raising:

1. **Disabled** — `LANGFUSE_ENABLED=false` or missing required credentials.
2. **Import failure** — `langfuse` package is not installed (`ImportError` on import).
3. **Runtime failure** — provider initialization raises any exception.

Under every degradation level the factory MUST return a `NoopProvider` and log a single warning identifying the degradation cause. The application SHALL NOT crash due to observability unavailability under any circumstance.

#### Scenario: Returns noop when LANGFUSE_ENABLED is false

- **WHEN** `LANGFUSE_ENABLED=false` and `get_observability_provider()` is called
- **THEN** the returned provider's `name` MUST equal `"noop"`
- **AND** no attempt to import `langfuse` SHALL be made

#### Scenario: Returns noop when langfuse package is missing

- **WHEN** `LANGFUSE_ENABLED=true` and importing `langfuse` raises `ImportError`
- **THEN** the returned provider's `name` MUST equal `"noop"`
- **AND** a warning log record MUST be emitted naming the missing package

#### Scenario: Returns noop when provider init raises

- **WHEN** `LANGFUSE_ENABLED=true` and `LangfuseProvider.setup()` raises any exception during init
- **THEN** the returned provider's `name` MUST equal `"noop"`
- **AND** a warning log record MUST be emitted identifying the init failure
- **AND** the original exception MUST NOT propagate to the caller

### Requirement: Harness Invocation Tracing

The `HarnessAdapter.invoke()` call path SHALL invoke `provider.trace_llm_call(...)` on every invocation. The trace call MUST include `model` (from harness config), `persona` (persona name), `role` (current role name), `input_tokens`, `output_tokens`, and `duration_ms` measured across the awaited call.

When the underlying harness invocation raises, the trace call MUST still record the attempted operation with `metadata={"error": type(exc).__name__}` before the exception is re-raised.

#### Scenario: Emits trace_llm_call on successful invocation

- **WHEN** `DeepAgentsHarness.invoke(agent, "hello")` is awaited with persona `personal` and role `assistant`
- **THEN** `provider.trace_llm_call` MUST be called exactly once
- **AND** the call's keyword arguments MUST include `persona="personal"` and `role="assistant"`
- **AND** the `duration_ms` MUST be a non-negative float

#### Scenario: Emits trace_llm_call when invocation raises

- **WHEN** the underlying harness raises `RuntimeError("model unavailable")`
- **THEN** `provider.trace_llm_call` MUST be called once before the exception propagates
- **AND** the call's `metadata` MUST contain `{"error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller

### Requirement: Delegation Chain Tracing

The `DelegationSpawner.delegate()` call path SHALL invoke `provider.trace_delegation(...)` on every delegation. The trace call MUST include `parent_role`, `sub_role`, `task` (hashed if its length exceeds 256 characters), `persona`, `duration_ms`, and `outcome` (one of `"success"` or `"error"`).

#### Scenario: Emits trace_delegation on successful delegation

- **WHEN** `DelegationSpawner.delegate("researcher", "find X")` is awaited with parent role `assistant`
- **THEN** `provider.trace_delegation` MUST be called exactly once
- **AND** the call's keyword arguments MUST include `parent_role="assistant"`, `sub_role="researcher"`, and `outcome="success"`

#### Scenario: Hashes long task strings

- **WHEN** `delegate("researcher", task)` is called with a `task` string longer than 256 characters
- **THEN** `provider.trace_delegation` MUST be called with `task` set to the string `"sha256:<16-char hex>"` rather than the raw task

### Requirement: Tool Call Tracing Across Extensions and HTTP Tools

Every LangChain `StructuredTool` returned by an `Extension.as_langchain_tools()` call and every HTTP tool constructed by `src/assistant/http_tools/builder.py` SHALL be wrapped such that `provider.trace_tool_call(...)` is invoked on each tool invocation. The `tool_kind` argument MUST be `"extension"` for extension tools and `"http"` for HTTP-discovered tools. When the tool raises, the trace call MUST record `error=<exception type name>` before re-raising.

#### Scenario: Extension tool invocation is traced

- **WHEN** an extension tool `gmail.search` is invoked with persona `personal`
- **THEN** `provider.trace_tool_call` MUST be called once
- **AND** the call's `tool_name` MUST equal `"gmail.search"` and `tool_kind` MUST equal `"extension"`

#### Scenario: HTTP tool invocation is traced

- **WHEN** an HTTP-discovered tool `linear.listIssues` is invoked
- **THEN** `provider.trace_tool_call` MUST be called once with `tool_kind="http"`

#### Scenario: Tool error is recorded before propagating

- **WHEN** a tool invocation raises `httpx.HTTPStatusError`
- **THEN** `provider.trace_tool_call` MUST be called with `error="HTTPStatusError"`
- **AND** the exception MUST propagate to the caller

### Requirement: Memory and Graphiti Operation Tracing

Operations on `src/assistant/core/memory.py` (read, write, recall) and `src/assistant/core/graphiti.py` (episode add, graph query) SHALL invoke `provider.trace_memory_op(...)`. The `op` argument MUST use one of `"read"`, `"write"`, `"recall"`, `"episode_add"`, `"graph_query"`. The `target` argument MUST be the operation's key, namespace, or query identifier (hashed if it exceeds 256 characters).

#### Scenario: Memory read emits trace_memory_op

- **WHEN** `MemoryStore.recall(key="last_summary")` is invoked
- **THEN** `provider.trace_memory_op` MUST be called once with `op="recall"` and `target="last_summary"`

#### Scenario: Graphiti episode add emits trace_memory_op

- **WHEN** `GraphitiClient.add_episode(...)` is awaited
- **THEN** `provider.trace_memory_op` MUST be called with `op="episode_add"`

### Requirement: Secret Sanitization

The module `src/assistant/telemetry/sanitize.py` SHALL apply an ordered regex list to every string value in span attributes, metadata dicts, and error messages emitted to any provider. The regex list MUST be applied most-specific-first and MUST include at least these patterns in this order:

1. `pk-lf-[A-Za-z0-9]+` and `sk-lf-[A-Za-z0-9]+` → `LF-KEY-REDACTED`
2. `AKIA[0-9A-Z]{16}` and `ASIA[0-9A-Z]{16}` → `AWS-KEY-REDACTED`
3. `(ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]{36,255}` → `GH-TOKEN-REDACTED`
4. `xox[abprs]-[0-9]+-[0-9]+-[A-Za-z0-9_-]{24,}` → `SLACK-TOKEN-REDACTED`
5. `ya29\.[A-Za-z0-9_-]+` → `GOOGLE-OAUTH-REDACTED`
6. `(postgres|postgresql|mysql|mongodb|redis)://[^\s:]+:[^\s@]+@[^\s]+` → `DB-URL-REDACTED`
7. `sk-[A-Za-z0-9]+` → `SK-REDACTED`
8. `sbp_[A-Za-z0-9]+` → `SBP-REDACTED`
9. `eyJ[A-Za-z0-9_\-\.]+` → `JWT-REDACTED`
10. `Authorization:\s*Basic\s+[A-Za-z0-9+/=]+` → `Authorization: Basic REDACTED`
11. `Authorization:\s*Digest\s+[^\r\n]+` → `Authorization: Digest REDACTED`
12. `Cookie:\s*[^\r\n]+` → `Cookie: REDACTED`
13. `Bearer +[A-Za-z0-9_\-\.=]+` → `Bearer REDACTED`
14. Private submodule URL patterns matching `git@[^\s:]+:[^\s]+\.git` and `https://[^\s@]+@[^\s]+\.git` → `SUBMODULE-URL-REDACTED`
15. Catch-all `(?i)(password|token|secret|key|api[_-]?key)=[^\s&]+` → `\1=REDACTED`

The sanitizer MUST NOT modify fields with known-safe semantics: `persona`, `role`, `parent_role`, `sub_role`, `tool_name`, `model`, `name` (span name), `outcome`, `op`, `tool_kind`. Every other string passes through the redaction chain.

#### Scenario: Langfuse-specific key is redacted before the generic secret-key pattern

- **WHEN** a span attribute value contains both `sk-lf-abc123` and `sk-generic456` as substrings
- **THEN** the sanitized value MUST contain `LF-KEY-REDACTED` for the `sk-lf-` match
- **AND** MUST contain `SK-REDACTED` for the generic `sk-` match
- **AND** the same ordering rule MUST apply for `pk-lf-*` before any generic public-key-shaped pattern

#### Scenario: Common vendor-token formats are redacted

- **WHEN** a span attribute value contains any of: an AWS access key matching `AKIA` followed by 16 uppercase alphanumerics; a GitHub PAT matching `ghp_` (or `gho_` / `ghu_` / `ghs_` / `ghr_`) followed by 36 or more base62 characters; a Slack token matching `xoxb-` (or `xoxp-` / `xoxa-`) followed by the standard numeric-numeric-base62 triplet; a Google OAuth access token matching `ya29.` followed by base64url characters
- **THEN** each value MUST be replaced by its dedicated redaction marker (`AWS-KEY-REDACTED`, `GH-TOKEN-REDACTED`, `SLACK-TOKEN-REDACTED`, `GOOGLE-OAUTH-REDACTED`)
- **AND** no fragment of the original value MUST remain in the sanitized output

*(Implementation note: the test suite for task 1.7 MUST construct fixture values matching these patterns inline from character classes to avoid committing realistic-looking strings into the repo, which would trip secret-scanning on push.)*

#### Scenario: Database URL with embedded credentials is redacted

- **WHEN** a span attribute value contains `postgres://user:password@db.example.com:5432/app` or `mysql://u:p@host/db`
- **THEN** the sanitized value MUST contain `DB-URL-REDACTED` in place of the URL
- **AND** the credentials portion (`user:password@`) MUST NOT remain visible even partially

#### Scenario: Private submodule URL is redacted

- **WHEN** a metadata field contains `git@github.com:jankneumann/private-config.git`
- **THEN** the sanitized value MUST contain `SUBMODULE-URL-REDACTED`
- **AND** MUST NOT contain the original URL

#### Scenario: Persona name is preserved

- **WHEN** a span is emitted with `persona="personal"`
- **THEN** the emitted `persona` attribute MUST equal `"personal"`
- **AND** MUST NOT be redacted

### Requirement: Flush Lifecycle

The telemetry module SHALL register `atexit.register(provider.shutdown)` exactly once during `get_observability_provider()` to ensure buffered events are drained when the process exits normally. When the env var `LANGFUSE_FLUSH_MODE=per_op` is set, every first-class `trace_*` method MUST additionally call `self.flush()` before returning. The default flush mode SHALL be `shutdown`.

#### Scenario: Shutdown mode batches events

- **WHEN** `LANGFUSE_FLUSH_MODE` is unset and 10 consecutive `trace_llm_call` calls occur
- **THEN** `provider.flush` MUST NOT be called as a side effect of any `trace_*` method
- **AND** `provider.shutdown` MUST be invoked when the process exits

#### Scenario: Per-op mode flushes each call

- **WHEN** `LANGFUSE_FLUSH_MODE=per_op` is set and `trace_llm_call` is invoked
- **THEN** `provider.flush` MUST be called before the `trace_llm_call` method returns

### Requirement: Noop Provider is the Default

The telemetry factory SHALL return a `NoopProvider` instance when no `LANGFUSE_ENABLED=true` configuration is present, whether or not Langfuse credentials are set. The `NoopProvider` SHALL implement every Protocol method as a zero-allocation no-op (constant-time return, no metadata dict creation, no logging at info level or above).

#### Scenario: Default configuration yields noop

- **WHEN** `get_observability_provider()` is called with no env var set
- **THEN** the returned instance's `name` MUST equal `"noop"`

#### Scenario: Noop methods have O(1) allocation behavior

- **WHEN** `NoopProvider.trace_llm_call(...)` is called 10,000 times with a fixed-size kwargs dict
- **THEN** the heap allocation measured via `tracemalloc` at the end MUST NOT scale with call count (linear growth is a regression; a constant per-call overhead from Python's own keyword-dict construction is acceptable)
- **AND** this scenario is categorized as an **advisory** performance check: a 3-run median MUST stay within a 4 KB tolerance over the 10k iteration window on typical CI runners, but a single outlier run MUST NOT fail the CI job

### Requirement: Configuration Loading Through Persona Pattern

The telemetry configuration SHALL be resolved through the existing `_env()` helper pattern used in `src/assistant/core/persona.py`, not by direct `os.environ` access in provider code. The module `src/assistant/telemetry/config.py` SHALL define a frozen dataclass `TelemetryConfig` with fields corresponding to `LANGFUSE_ENABLED`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `LANGFUSE_ENVIRONMENT`, `LANGFUSE_FLUSH_MODE`, and `LANGFUSE_SAMPLE_RATE`, with typed defaults. Credentials MUST NEVER be embedded in code or committed config.

#### Scenario: Missing credentials default to disabled

- **WHEN** `TelemetryConfig.from_env()` is called with no `LANGFUSE_*` env vars set
- **THEN** the returned config's `enabled` field MUST equal `False`

#### Scenario: Empty-string credentials are treated as missing

- **WHEN** `TelemetryConfig.from_env()` is called with `LANGFUSE_ENABLED=true` but `LANGFUSE_PUBLIC_KEY=""` (empty string, whitespace, or unset) or `LANGFUSE_SECRET_KEY=""` (empty)
- **THEN** the returned config's `enabled` field MUST equal `False`
- **AND** a warning log record MUST be emitted identifying the empty-but-present credential as the reason for the disabled state (distinguishing this from a fully-unset case)

### Requirement: Persona and Role Context Propagation

The system SHALL expose `contextvars.ContextVar`-based functions for propagating the current persona and role identifiers to every `trace_*` call site without threading them through method signatures. The module `src/assistant/telemetry/context.py` SHALL provide:

- `set_assistant_ctx(persona: str | None, role: str | None) -> None` — replaces the current context
- `get_assistant_ctx() -> tuple[str | None, str | None]` — returns the current `(persona, role)` tuple
- `assistant_ctx(persona: str | None, role: str | None) -> contextmanager` — a context manager that pushes a new scope and pops it on exit

Because `contextvars.ContextVar` is task-local per PEP 567, the context MUST survive across `await` boundaries within the same asyncio task. When `DelegationSpawner.delegate()` spawns a sub-agent, the delegation decorator SHALL use the `assistant_ctx(...)` context manager to push the sub-role for the duration of the sub-agent's execution so that spans emitted by the sub-agent report the sub-role, not the parent role.

#### Scenario: Context persists across await

- **WHEN** `set_assistant_ctx("personal", "assistant")` is called and the running async function awaits a coroutine that calls `get_assistant_ctx()` before and after an `await asyncio.sleep(0)` boundary
- **THEN** both calls MUST return `("personal", "assistant")`

#### Scenario: Delegation updates context for the sub-agent's spans

- **WHEN** the current context is `("personal", "assistant")` and `DelegationSpawner.delegate("researcher", "find X")` is awaited
- **THEN** any span emitted by the sub-agent during the delegation's lifetime MUST report `role="researcher"`
- **AND** after the delegation returns, `get_assistant_ctx()` MUST return `("personal", "assistant")` again (scope popped)

### Requirement: No Inbound Interfaces

The telemetry module SHALL NOT expose any HTTP endpoint, webhook, gRPC server, message-queue consumer, or other inbound network interface. All communication with external observability backends SHALL be outbound-only via the backend vendor's SDK (currently the Langfuse HTTP SDK). This constraint SHALL be enforced in code review and documented in `src/assistant/telemetry/__init__.py` as a module-level docstring comment.

Rationale: inbound interfaces expand the attack surface of the agent process. Observability is a write-only consumer of internal state; introducing a reader (e.g., a webhook that external systems can POST to) would violate that invariant and has not been analyzed in any threat model for this change.

#### Scenario: Module docstring declares outbound-only posture

- **WHEN** `src/assistant/telemetry/__init__.py` is loaded
- **THEN** its module docstring MUST contain the phrase "outbound-only"
- **AND** no import inside `src/assistant/telemetry/` SHALL pull in `fastapi`, `flask`, `aiohttp.web`, `grpc.aio.server`, or any other inbound server framework

### Requirement: Documented Crash-Time Delivery Semantics

The telemetry module SHALL document, in both `src/assistant/telemetry/flush_hook.py` module docstring and `docs/observability.md`, that the default `shutdown` flush mode loses buffered events if the process is terminated by a signal that bypasses `atexit` (SIGKILL, uncatchable crash, OOM kill). Users requiring guaranteed delivery SHALL set `LANGFUSE_FLUSH_MODE=per_op` and accept the per-operation latency cost.

#### Scenario: Shutdown-mode delivery loss is documented

- **WHEN** `docs/observability.md` is read
- **THEN** it MUST contain a section titled "Delivery guarantees" that describes the shutdown-mode tradeoff and the `LANGFUSE_FLUSH_MODE=per_op` opt-in
