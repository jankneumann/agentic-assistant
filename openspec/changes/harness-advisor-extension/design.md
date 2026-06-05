# Design: harness-advisor-extension

> First reference implementation of P1.6 `patterns-architecture`. Delivers
> `Capability.ADVISE` end-to-end on two harnesses (Deep Agents native,
> MS Agent Framework emulated).
>
> Prerequisites: P1.6 design.md (four-layer model, Capability concept,
> CapabilityInfo, required_capabilities, factory contract, anti-patterns).

---

## D1 — Capability Framework Concrete Types

P1.6 defined concepts; P1.7 pioneers the concrete representation that all
later capability proposals inherit.

### Capability StrEnum

```python
# src/assistant/core/capabilities.py
class Capability(StrEnum):
    ADVISE = "advise"
```

StrEnum chosen because: (a) string-serializable for YAML config, (b)
strongly typed in Python, (c) extensible by P12 adding `DELEGATE = "delegate"`
etc. without modifying existing entries.

### CapabilityInfo Dataclass

```python
@dataclass(frozen=True)
class CapabilityInfo:
    mode: Literal["native", "emulated", "transport_mediated", "not_supported"]
    cost_characteristic: Literal["cheap", "moderate", "expensive"]
    notes: str = ""
```

`frozen=True` because capability declarations are static per harness class
(per P1.6 D3 default: undeclared = not_supported).

### NOT_SUPPORTED Sentinel

```python
NOT_SUPPORTED = CapabilityInfo(
    mode="not_supported",
    cost_characteristic="expensive",
    notes="Capability not available on this harness.",
)
```

---

## D2 — AdvisorClient (Direct Anthropic SDK)

### Why bypass LangChain

The executor loop stays on LangChain (`init_chat_model()` at
`deep_agents.py:23`). The advisor call uses the `anthropic` SDK directly
because:

1. The `advisor_20260301` tool type and `anthropic-beta:
   advisor-tool-2026-03-01` header are raw Messages API features with no
   LangChain wrapper at time of writing.
2. Keeping one client (LangChain) for the loop and another (SDK) for the
   advisor scopes the new dependency to a single module (`advisor.py`).
3. The user chose this path explicitly at the P1.7 discovery gate.

### AdvisorClient shape

```python
# src/assistant/core/advisor.py
class AdvisorClient:
    def __init__(self, model: str = "claude-opus-4-6"):
        self._client = anthropic.AsyncAnthropic()
        self._model = model

    async def call(
        self, transcript: list[dict], question: str, budget_tokens: int = 1800
    ) -> AdvisorResponse: ...
```

### AdvisorResponse

```python
@dataclass
class AdvisorResponse:
    guidance: str
    model: str
    tokens_in: int
    tokens_out: int
    duration_ms: int
```

P4 observability will later wrap calls to `AdvisorClient.call()` with
spans using these fields. P1.7 records them; P4 wires the telemetry.

### Full transcript requirement (AP1)

Per P1.6 anti-pattern AP1 and G8 in `docs/gotchas.md`: the transcript
passed to `AdvisorClient.call()` MUST be the full executor conversation
including tool results. Never summarize. Budget concerns are handled by
capping the *response* via `budget_tokens`, not by truncating input.

---

## D3 — AdvisorTool (LangChain Integration)

`AdvisorTool` is a LangChain `StructuredTool` that wraps `AdvisorClient`.

### How it works

1. The role's `advisor:` config creates an `AdvisorClient` instance.
2. `AdvisorTool` is created from the client and added to the agent's
   tool list during `create_agent()`.
3. The executor's prompt includes a section: "when stuck on a non-obvious
   design decision or after repeated failures, call `advisor(question=...)`."
4. When the LLM emits `tool_use` for `advisor`, the tool handler:
   a. Collects the full transcript from agent state.
   b. Calls `AdvisorClient.call(transcript, question, budget_tokens)`.
   c. Returns `AdvisorResponse.guidance` as the tool result.
5. The executor reads the guidance and resumes.

### Two-roundtrip cost acknowledgment

This architecture requires two API calls per escalation: the executor's
LangChain call (which decides to invoke the tool) and the advisor's
direct-SDK call. The blog's single-Messages-API-call pattern is not
recoverable without integrating the advisor tool into the LangChain
request itself (which would require either a ChatAnthropic subclass or
extra_headers passthrough — both rejected at discovery). The quality
benefit (shared full-context consultation) is preserved; the cost
benefit is partial.

---

## D4 — Per-Role Executor Model

### Mechanism

`RoleConfig` gains an optional `executor_model` field. When present, the
Deep Agents adapter uses it instead of `persona.harnesses.deep_agents.model`
when calling `init_chat_model()`.

```yaml
# roles/coder/role.yaml
executor_model: "anthropic:claude-sonnet-4-6"
```

### Merge semantics

Persona role overrides can set/clear `executor_model` via the existing
shallow-merge path (`role.py:34-37`). Override wins; base role's value is
replaced entirely (not merged).

### Why this is needed

Without per-role executor_model, every role on a persona runs the same
model. The advisor pattern's cost story requires Sonnet/Haiku executors
with Opus advisors. If the persona default is Opus, `coder` can downshift
to Sonnet for the executor loop while keeping Opus for advisor calls.

---

## D5 — Emulated Fallback (MS Agent Framework)

The MS Agent Framework cannot use the `advisor_20260301` tool natively
(it is an Anthropic-specific API feature). The emulated path:

1. Reads `advisor:` config from the role.
2. Creates a standalone `AdvisorClient` instance.
3. On advisor request: calls `AdvisorClient.call()` with the transcript.
4. Returns the same `AdvisorResponse`.

The emulated path is functionally identical but: (a) always costs two
roundtrips (same as Deep Agents in this architecture), (b) the advisor
model is always Claude (even if the executor runs on a different provider).

CapabilityInfo: `mode=emulated, cost=expensive,
notes="Separate Opus call; same AdvisorResponse contract."`.

---

## D6 — Factory Capability Matching

`harnesses/factory.py` gains a single check after harness selection:

```python
for cap in role.required_capabilities:
    info = harness.capabilities.get(cap, NOT_SUPPORTED)
    if info.mode == "not_supported":
        raise ValueError(
            f"Harness '{harness.name()}' does not support capability "
            f"'{cap}' required by role '{role.name}'. "
            f"Evaluated: {list(harness.capabilities.keys())}"
        )
```

This is the contract-only check from P1.6 D5. No preference ordering,
no fallback chains, no tie-breaking — those belong to P11.
