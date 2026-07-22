# model-provider-routing — Design

The archived P24 contracts (`openspec/specs/model-provider/spec.md`,
`credential-provider`, `capability-resolver` slot #6) are binding;
this document records only the implementation-level judgment calls
made while landing them, plus the owner-review verdicts (see "Owner
review" below). Deltas are kept minimal.

## Owner review verdicts (2026-07-16)

1. **Accepted as-is** — D1 `model_id` wire-identifier field.
2. **Accepted as-is** — D4 `require_confirmation=True` denies until
   the approval interrupt flow lands.
3. **Registry-only cleanup (this rework)** — since no working
   personas exist yet, the backward-compat dual config path is churn
   with no beneficiaries (Churn Rule: the owner funds the migration,
   and today the migration set is empty, so pay the breaking change
   now). `StaticModelProvider`, its `for_harness()` re-binding step
   (old D5 first half), and every read of `harnesses.<name>.model`
   (persona template, harness adapters, telemetry fallback) are
   deleted; the persona `models:` registry — reshaped to `entries:` +
   consumer `bindings:` — is the ONLY model-selection mechanism, with
   a synthesized default registry covering personas that declare
   none. See D9/D10. Consequence: the byte-identical single-argument
   `init_chat_model` assertion against a persona-configured
   `model` string was removed from the test suite (the persona
   config string no longer exists); the synthesized-default path
   still asserts the exact single-argument call for the built-in
   defaults.
4. **Accepted as-is** — D6 MSAF binding covers `openai-compatible`
   refs only.
5. **Accepted as-is** — D3 `required_tags` filtering of the whole
   chain, fallbacks included.

## D1: `model_id` — the wire identifier ModelRef was missing

The archived `ModelRef` field list has no slot for the identifier the
wire actually needs: `name` is the *registry entry* name
(`"local-fast"`), but bindings must send `"llama-3.1-8b-instruct"`.
The OpenRouter `/models` schema — which the catalog metadata already
mirrors — carries this as `id`.

**Decision.** `ModelRef` gains `model_id: str`, populated from the
registry entry's `id:` key and defaulting to `name` when omitted.
Synthesized default-registry entries (D10) store the harness-default
`provider:model` string verbatim in both `name` and `model_id`; the
LangChain binding uses a `model_id` containing `:` as-is (registry
`id` values use `/`, never `:`), reproducing the exact
single-argument `init_chat_model(model_str)` call for the defaults.
Delta: ADDED requirement "ModelRef Wire Identifier".

## D2: Default-entry dialect inference

The synthesized default registry (D10) infers each entry's dialect
from the LangChain provider prefix (`anthropic:` → `anthropic`,
`openai:`/`ollama:` → `openai-compatible`, `google_genai:`/`gemini:`
→ `gemini`, `bedrock*:` → `bedrock`, `google_vertexai:`/`vertex:` →
`vertex`; unknown prefixes default to `openai-compatible`). Because
the binding passes the original string through verbatim (D1), a
mis-inferred dialect on the default path affects only span labeling,
never routing. Default entries carry no tags, so a `ModelRequest`
with `required_tags` raises `ModelResolutionError` rather than
silently returning a non-matching model (per the protocol
requirement).

## D3: Registry resolution ordering

Bindings resolve first (D9). On the unbound path, `resolve()` =
entries carrying **all** `required_tags`, ordered by preferred-tag
match count (desc) then declaration order; each candidate is followed
by its declared `fallbacks`, which are also filtered by
`required_tags` (the privacy scenario: a fallback that drops
`private-data-ok` never enters the chain — accepted as-is, verdict
#5). First occurrence wins on duplicates. On the bound path the same
`required_tags` filter applies to the bound entry + its fallbacks; an
all-filtered bound chain raises rather than silently substituting an
unbound entry.

## D4: Binding-time budget gate; deny-safe `require_confirmation`

The spec gates "every model dispatch" — for harness bindings the
construction site is the single choke point, so `check_action` fires
before client construction; the raw client re-checks before every
wire call (it is the only binding that itself dispatches). A
`require_confirmation=True` decision **denies** with an explanatory
error: the approval interrupt flow rides on durable sessions, which
are not wired. Deny-safe beats silently proceeding. Delta: ADDED
requirement "Confirmation Requests Deny Until Interrupt Flow Exists".
A guardrail denial propagates without trying fallback refs — policy
stops are not provider failures.

## D5: Harness fallback iteration (re-binding step removed)

Harnesses walk the resolved chain at `create_agent` time: first ref
whose binding constructs wins; all-fail raises `ModelResolutionError`
chained to the last binding error. (Mid-conversation runtime failover
is follow-up scope — the chain is honored at construction.) The
original `StaticModelProvider.for_harness()` re-binding step is gone
(verdict #3): each harness now resolves
`ModelRequest(consumer=self.name())` and the registry's consumer
bindings select the entry — the resolver no longer needs to know
which harness consumes the provider, and the harness no longer
post-processes it.

## D6: MSAF binding scope

`agent-framework` 1.10.x ships only the OpenAI connector, so the MSAF
binding adapts `openai-compatible` refs (passing `model_id` /
`api_key` / `base_url` only when non-empty, keeping env-driven
configs working) and raises `ModelBindingError` for other dialects.
The `chat_client: azure_openai` persona branch is untouched and
degrades to its documented install error (CLAUDE.md packaging note).

## D7: Cost attribution rides `_active_model_ref`

Following the existing `_active_model` pattern, harnesses stash the
resolved ref on `self._active_model_ref`; `@traced_harness` merges
`{model_ref, model_dialect, cost_usd}` into span metadata, computing
`cost_usd` from OpenRouter-shaped per-token string rates × the token
counts the decorator already captures. Missing/unparseable pricing
omits the cost (never guessed). No new billing system; span shapes
for call sites without an active ref are byte-identical to pre-P19.

## D8: CapabilitySet.models is `Optional` at the type level

`CapabilitySet.models: ModelProvider | None = None` — the resolver
always fills it (both branches), but hand-assembled sets (tests,
host-context exports) keep constructing without it, mirroring the
existing `context` slot precedent.

## D9: `models:` shape — `entries:` + consumer `bindings:` (verdict #3)

The registry gains an explicit consumer-binding layer:
`models.entries:` declares the callable models (unchanged field
schema); `models.bindings:` maps consumer names → entry names.
Consumer names are harness names (`deep_agents`,
`ms_agent_framework`) today and non-harness consumers (`embeddings`,
`memory`) later; the reserved `default` key covers any consumer
without an explicit binding, and `ModelRequest.consumer` becomes an
open-vocabulary string defaulting to `"default"` (the old closed
`chat`/`embedding` set is gone). Resolution is binding-first: bound
consumer → bound entry + its declared fallbacks (tag-filtered);
unbound consumer → the pre-existing tag-filtered whole-registry
resolution, so tags-only personas keep working. Bindings that target
undeclared entries fail persona load; the old flat entry map is
rejected with a pointer to the new shape (deliberate — a silently
reinterpreted config is worse than a load error, and no deployed
configs exist).

## D10: Default synthesis — a synthesized registry, not a new provider

Chosen: synthesize a `ModelRegistry` from the known harness defaults
(`default_model_registry()` over the `DEFAULT_HARNESS_MODELS` table
in `models.py`) and hand it to the same `RegistryModelProvider` —
rather than adding a `DefaultModelProvider` class. One resolution
code path, no second provider to keep in behavioral lockstep, and
the synthesized registry is inspectable via `list_models()` like any
other. The defaults table lives in core (`models.py`) and the harness
classes point their span-default `_DEFAULT_MODEL` at it, so core
never imports harness modules and the default cannot drift between
the registry and the span label. Synthesized entries store the full
`provider:model` string as `name`/`model_id` (D1 verbatim-passthrough
rule), preserving each harness's exact pre-P19 client construction.
