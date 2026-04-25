# Observability

This document explains how to enable and operate the optional Langfuse-backed
observability layer for `agentic-assistant`. The layer is fully opt-in: the
default install ships with a noop provider and zero behavioral change, so you
only pay the cost of telemetry (extra dependency, network calls) when you ask
for it.

## Quickstart

The repo bundles a self-hosted Langfuse v3 stack so a developer can go from a
fresh clone to a live trace dashboard in one terminal session, with no
account creation, no manual UI setup, and no real credentials. The
`LANGFUSE_INIT_*` env vars in the compose file auto-provision a default
organization, project, API key pair, and admin user on first start
(see Langfuse "Headless Initialization").

```bash
# 1. Bring up the local stack (postgres, clickhouse, redis, minio,
#    langfuse-web on 3100, langfuse-worker). The -p flag isolates this
#    project name from the app's own compose graphs.
docker compose -f docker-compose.langfuse.yml -p langfuse up -d

# 2. Install the optional telemetry extra (adds the Langfuse Python SDK).
uv sync --extra telemetry

# 3. Point the assistant at the local Langfuse instance with the seeded
#    dev keys.
export LANGFUSE_ENABLED=true
export LANGFUSE_PUBLIC_KEY=DUMMY-pk-lf-dev-local
export LANGFUSE_SECRET_KEY=DUMMY-sk-lf-dev-local
export LANGFUSE_HOST=http://localhost:3100

# 4. Run the assistant — every harness invocation, sub-agent delegation,
#    memory operation, Graphiti call, and tool call now emits a span.
uv run assistant -p personal
```

Open the dashboard at <http://localhost:3100> and log in with
`dev@localhost` / `DUMMY-change-me-before-prod`. The seeded project's traces
appear under "agentic-assistant (DUMMY)".

To turn telemetry off again, unset `LANGFUSE_ENABLED` (or set it to `false`).
The factory falls back to the noop provider and the assistant runs without
emitting anything.

## Minimum requirements

- Python 3.12 (matches the rest of the repo).
- Langfuse server v3.x — pinned via the bundled compose file (the
  `langfuse/langfuse:3` and `langfuse/langfuse-worker:3` images).
- `langfuse>=3.0,<4.0` Python SDK — installed when you add the optional
  `[telemetry]` extra (`uv sync --extra telemetry`).
- Docker + Docker Compose v2 — needed only for the bundled local stack.
  Pointing at a hosted Langfuse instance instead of the local one is
  fully supported; just set `LANGFUSE_HOST` accordingly.

## Delivery guarantees

Telemetry uses one of two flush modes, controlled by `LANGFUSE_FLUSH_MODE`.

**`shutdown` (default).** Spans are batched in the Langfuse SDK's in-process
queue and flushed once when the Python interpreter exits via `atexit`. This
is the right tradeoff for normal operation: trace emission stays off the hot
path so the assistant's per-request latency budget is unaffected.

The cost: any process termination that bypasses `atexit` discards the
buffered batch. That includes:

- `SIGKILL` (`kill -9`, container OOM kill, `docker rm -f`).
- An uncatchable C-extension crash (segfault, abort).
- Linux OOM killer reaping the process under memory pressure.
- A power loss or kernel panic on the host.

Normal exits — `SIGTERM`, `SIGINT` (Ctrl-C), an uncaught Python exception
that unwinds the stack, `sys.exit()`, falling off the end of `main()` — all
run `atexit` and flush cleanly.

**`per_op`.** Set `LANGFUSE_FLUSH_MODE=per_op` to force a flush after every
top-level `trace_*` call (`trace_llm_call`, `trace_delegation`,
`trace_tool_call`, `trace_memory_op`). This guarantees that a span is on
the wire before the next operation begins, so a SIGKILL one millisecond
later still loses at most the in-flight HTTP request.

The cost: per-operation latency. Each trace adds a synchronous HTTP round
trip to the Langfuse server (typically tens of milliseconds local, hundreds
of milliseconds to a hosted instance). For the assistant's interactive REPL
this is usually invisible; for high-throughput batch processing it can
double the wall time of tool-heavy workloads.

**Recommendation.** Leave `LANGFUSE_FLUSH_MODE` unset (defaults to
`shutdown`) for normal use. Switch to `per_op` when debugging a crash you
suspect is losing the trace that would explain it, or when running an
evaluation harness where every span matters.

## Privacy and sanitization notes

The telemetry module sanitizes span attributes before they leave the
process. The sanitizer is an ordered regex chain in
`src/assistant/telemetry/sanitize.py` that matches most-specific patterns
first (Langfuse-style API keys, OpenAI-style keys, GitHub tokens, AWS
access keys, generic high-entropy strings, and private-submodule URLs that
could leak persona repo names) and replaces them with `[REDACTED]`.

Persona and role names are deliberately passed through unredacted: the
codebase guarantees they are short operator-chosen identifiers
(`personal`, `work`, `researcher`, `chief_of_staff`, etc.) and the spans
become much less useful without them. A future code path that derives
persona names from untrusted input would need an additional validation
step at persona-registry load time — see the design doc and session log
for the open question.

The two-layer privacy guard
(`tests/conftest.py` + `tests/_privacy_guard_plugin.py`) patches all
filesystem I/O in the public test suite. Telemetry MUST NOT write spans
to local files — it only emits over HTTP via the Langfuse SDK. There is
no JSONL fallback, no `/tmp/spans.log`, and no on-disk side effect from
any provider path. The `tests/telemetry/test_privacy_compliance.py` test
asserts this by exercising the module under the privacy-guard fixtures.

The sanitizer applies to span attributes; persona-private content
(memory entries, Graphiti graph nodes, role overrides loaded from a
private submodule) is handled by the persona boundary rather than by
the sanitizer. Tests assert the fixture sentinel `FIXTURE_PERSONA_SENTINEL_v1`
never appears in any emitted span.

## Dev-only credential warning

Every credential committed to `docker-compose.langfuse.yml` is prefixed
with `DUMMY-`. This convention is load-bearing:

- Secret scanners (`gitleaks`, `trufflehog`, GitHub push protection) skip
  values prefixed with `DUMMY-` so the compose file can be checked in
  without false positives.
- A copy-paste of any of these values into a production deployment is
  instantly visually wrong, which is the desired failure mode.
- The langfuse-web container's startup is intended to refuse to launch
  with `DUMMY-*` credentials when the host is anything other than
  `localhost` / `127.0.0.1` (see the design doc D9 startup-check sidecar
  note — the integration test in `wp-integration` covers this).

**Do not use any `DUMMY-*` value as the credential for a real Langfuse
instance.** Production Langfuse keys come from the Langfuse UI's
project-settings page and look like `pk-lf-…` / `sk-lf-…` (no `DUMMY-`
prefix).

The repo's `.gitleaksignore` (or equivalent allowlist) lists the committed
placeholders so secret-scanning CI does not need a per-PR override.

## CI/CD considerations

The default GitHub Actions test job runs without the `[telemetry]` extra:

- `uv sync` (no `--extra telemetry`) — the Langfuse SDK is not installed.
- `LANGFUSE_ENABLED` is not set in the workflow env.
- The factory walks the level-1 graceful-degradation path
  (`enabled=false` → `NoopProvider`) on every test that touches telemetry.
- The test suite itself never makes a real Langfuse network call.

This keeps the default CI lane fast (no extra wheel data, no httpx
transitive churn) and means the assistant's behavior under "telemetry off"
is exercised by every test run.

A separate, opt-in `langfuse-smoke` job runs `uv sync --extra telemetry`
and exercises a live round-trip against an ephemeral Langfuse instance.
It is opt-in (not in the default required-checks list) for two reasons:

1. It needs the Langfuse SDK + a running Langfuse — both add minutes to
   the wall time of every PR even when the change has nothing to do with
   telemetry.
2. The factory's three-level graceful degradation makes telemetry
   strictly additive: a default-CI failure is always a real bug, but a
   smoke-job failure may be a transient Langfuse-server hiccup. Gating
   merges on the smoke job would conflate the two.

Run the smoke job manually (workflow_dispatch) before tagging a release
or after touching `src/assistant/telemetry/providers/langfuse.py`.

## Claude Code Stop hook wiring

This repo does **not** install a Claude Code Stop hook automatically.
The canonical, repo-agnostic Stop hook lives in
`agent-coordinator/scripts/langfuse_hook.py`
(in `~/Coding/agentic-coding-tools/agent-coordinator/`); it reads the
Claude Code transcript, cursor-tracks the lines it has already consumed,
sanitizes them through the same regex chain used by the in-process
telemetry, and emits a Langfuse trace per session.

To enable session-level traces from Claude Code, follow the wiring
instructions in the `agent-coordinator` README. In short:

1. Set the same `LANGFUSE_*` env vars (public/secret/host) in the shell
   that launches Claude Code, or in `~/.claude/settings.json`'s `env`
   block.
2. Add a Stop hook entry in `~/.claude/settings.json` that points at
   `~/Coding/agentic-coding-tools/agent-coordinator/scripts/langfuse_hook.py`.
3. Confirm the next Claude Code session shows up under the same Langfuse
   project as the assistant CLI's spans.

We deliberately keep the exact JSON snippet out of this doc: the hook
config varies by user (paths, env-var sourcing, multiple-project setups)
and the upstream `agent-coordinator` README is the source of truth.
Re-implementing the hook here would duplicate code and drift; the hook
is genuinely repo-agnostic and the agentic-coding-tools repo is the
intentional canonical home (see design D10).

## Further reading

- Design rationale: `openspec/changes/observability/design.md` (decisions
  D6, D9, D10, D12, D13).
- Spec: `openspec/changes/observability/specs/observability/spec.md`.
- Architecture diagrams and the harness/delegation/memory/tool hook
  inventory: `openspec/changes/observability/proposal.md`.
