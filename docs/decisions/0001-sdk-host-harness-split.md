# ADR-0001: Two-tier harness architecture — SDK vs Host adapters

## Status

ACCEPTED — decided in OpenSpec change `capability-protocols`
(`openspec/changes/archive/2026-04-20-capability-protocols/`),
archived 2026-04-20.

## Date

2026-04-20

## Context

The original `HarnessAdapter` from `bootstrap-vertical-slice` (P1)
assumed every harness owns the agent loop: `create_agent` → `invoke` →
`spawn_sub_agent`. That model fits SDK-based harnesses (Deep Agents,
MS Agent Framework, and future ADK / Claude Agent SDK / OpenAI Agents
SDK integrations), but it is structurally wrong for host harnesses
such as Claude Code and Codex, where the *host* owns the loop and this
repo's persona/role configuration is the payload. Before this change,
host-harness integration files (CLAUDE.md sections, skill definitions)
were maintained by hand, with no programmatic export path and no place
in the adapter hierarchy for a harness that never calls a model itself.

## Decision

Split `src/assistant/harnesses/` into two tiers, both defined in
`src/assistant/harnesses/base.py`:

- **`SdkHarnessAdapter`** (`harnesses/sdk/`) — owns the agent loop.
  Abstract surface: `create_agent(tools, extensions)`,
  `invoke(agent, message)`, `spawn_sub_agent(...)`, plus (added later
  by `harness-ag-ui-bridge`) `astream_invoke()` and a `thread_id`
  property for transport binding. Concrete implementations:
  `harnesses/sdk/deep_agents.py` and `harnesses/sdk/ms_agent_fw.py`.
- **`HostHarnessAdapter`** (`harnesses/host/`) — the host owns the
  loop; our code exports configuration artifacts instead of executing.
  Abstract surface: `export_context()`,
  `export_guardrail_declarations()`, `export_tool_manifest()`.
  Concrete implementation: `harnesses/host/claude_code.py`, driven by
  the `assistant export` CLI subcommand in `src/assistant/cli.py`.

`harness_type()` returns `"sdk"` or `"host"` so `harnesses/factory.py`
and the `CapabilityResolver` (ADR-0002) can route on tier. This was a
**breaking** restructure: `harnesses/deep_agents.py` moved to
`harnesses/sdk/deep_agents.py` and factory imports were updated.

## Consequences

- Subscription-seat harnesses (Claude Code, Codex, Gemini CLI) are
  first-class citizens rather than manually maintained config files;
  P16 `cli-harness-integrations` extends the `HostHarnessAdapter`
  export surface rather than inventing a new mechanism.
- Capability provisioning differs by tier (see ADR-0002): SDK
  harnesses receive injected capability implementations; host
  harnesses declare memory/sandbox/guardrails as host-provided and
  only self-provide context composition.
- Every new SDK harness must implement the full loop-owning contract,
  including streaming (`astream_invoke`, enforced at runtime via
  `NotImplementedError` on the base class).
- Downstream phases build on the split: P11 `harness-routing` selects
  across tiers (`--harness auto`); the AG-UI transport (ADR-0003)
  binds only to the SDK tier via `thread_id`.
- One import-path migration cost was paid once (tests and factory
  updated in the same change); the roadmap
  (`openspec/roadmap.md`, P1.8 row) records the restructure.
