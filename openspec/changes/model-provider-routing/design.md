# model-provider-routing — Design

The archived P24 contracts (`openspec/specs/model-provider/spec.md`,
`credential-provider`, `capability-resolver` slot #6) are binding;
this document records only the implementation-level judgment calls
made while landing them. Deltas are kept minimal — everything already
specced is implemented as written.

## D1: `model_id` — the wire identifier ModelRef was missing

The archived `ModelRef` field list has no slot for the identifier the
wire actually needs: `name` is the *registry entry* name
(`"local-fast"`), but bindings must send `"llama-3.1-8b-instruct"`.
The OpenRouter `/models` schema — which the catalog metadata already
mirrors — carries this as `id`.

**Decision.** `ModelRef` gains `model_id: str`, populated from the
registry entry's `id:` key and defaulting to `name` when omitted.
`StaticModelProvider` stores the persona's full `provider:model`
config string verbatim in both `name` and `model_id`; the LangChain
binding uses a `model_id` containing `:` as-is (registry `id` values
use `/`, never `:`), reproducing today's exact single-argument
`init_chat_model(model_str)` call. Delta: ADDED requirement "ModelRef
Wire Identifier".

## D2: Static dialect inference

`StaticModelProvider` infers the dialect from the LangChain provider
prefix (`anthropic:` → `anthropic`, `openai:`/`ollama:` →
`openai-compatible`, `google_genai:`/`gemini:` → `gemini`,
`bedrock*:` → `bedrock`, `google_vertexai:`/`vertex:` → `vertex`;
unknown prefixes default to `openai-compatible`). Because the binding
passes the original string through verbatim (D1), a mis-inferred
dialect on the static path affects only span labeling, never routing.
A static ref carries no tags, so a `ModelRequest` with
`required_tags` raises `ModelResolutionError` rather than silently
returning a non-matching model (per the protocol requirement).

## D3: Registry resolution ordering

`resolve()` = entries carrying **all** `required_tags`, ordered by
preferred-tag match count (desc) then declaration order; each
candidate is followed by its declared `fallbacks`, which are also
filtered by `required_tags` (the privacy scenario: a fallback that
drops `private-data-ok` never enters the chain). First occurrence
wins on duplicates. `ModelRequest.consumer` is validated
(`chat`/`embedding`) and carried but not yet used for filtering — the
embedding consumers arrive with P20/P21 and can extend the schema
without breaking entries.

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

## D5: Harness fallback iteration + `for_harness` re-binding

Harnesses walk the resolved chain at `create_agent` time: first ref
whose binding constructs wins; all-fail raises `ModelResolutionError`
chained to the last binding error. (Mid-conversation runtime failover
is follow-up scope — the chain is honored at construction.) The
resolver's default `StaticModelProvider` cannot know which harness
will consume it (the resolver receives only `harness_type`), so each
SDK harness re-binds a resolver-built static provider to its own
config entry via `StaticModelProvider.for_harness(name,
default_model=...)` — preserving the pre-P19 per-harness `model`
lookup and the harness's own default model exactly.

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
