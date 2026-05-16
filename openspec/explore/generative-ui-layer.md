# Exploration: Generative UI Layer for Personal Assistant

**Status:** Exploration — not yet a proposal
**Date:** 2026-05-15
**Origin:** Conversation while testing the `teacher` role; terminal UX felt underwhelming and ill-suited to teaching content (lessons, code, quizzes, diagrams, progress).
**Outcome:** Direction agreed. Next step is `/plan-feature` on the first OpenSpec change (`harness-ag-ui-bridge`).

---

## TL;DR — the decision

Adopt **two open standards** and build a thin web frontend alongside the existing CLI:

1. **AG-UI** (`ag-ui-protocol/ag-ui`) — event-based SSE protocol for streaming agent events from the Python harness to the browser. Backend-and-frontend-language-neutral. Already spoken by Microsoft Agent Framework (our future secondary harness) and Pydantic AI.
2. **OpenUI Lang** (`thesysdev/openui`, MIT) — compact streaming-friendly DSL the LLM emits inside assistant message bodies. Rendered progressively by `@openuidev/react-lang`'s `<Renderer/>` into typed React components.

Frontend: Vite + React + Tailwind SPA, designed to wrap as a Tauri desktop app later. Use `@openuidev/react-headless` for chat state (it speaks AG-UI natively); use `@openuidev/react-lang` for rendering OpenUI Lang inside messages. Hold a decision on `@openuidev/react-ui` (the pre-built chat layouts and component library) until we feel the cost of building a shell ourselves vs. accepting their visual defaults.

The Python harness is preserved. The persona × role abstraction is preserved. Roles gain a UI vocabulary appended to their system prompt; renderers live in the public frontend repo; vocabulary configuration can live per persona.

---

## Problem

The CLI is acceptable for shell-style interactions but misfits for content-rich roles. The `teacher` role surfaces this most clearly — it needs:

- Inline code with syntax highlighting and copy/run affordances
- Lesson-step navigation (you're on 3/7, back/next, jump)
- Comprehension checks (multiple choice, free response with grading)
- Diagrams (mermaid, occasionally generated images)
- Progress state visible across turns

A pure text stream cannot express these well. The user also wants the UX layer to apply to *all* roles (configuration per role), not just teacher, and explicitly mentioned generative-UI concepts as a learning interest beyond just shipping a useful product.

---

## Constraints (from discussion)

| # | Constraint | Source |
|---|---|---|
| C1 | No hosted UI-synthesis services; no sending personal data to third-party UI generators | "Not looking to run this on a hosted service or send my data somewhere" |
| C2 | Web app first, wrap as desktop via Tauri later (per `agentic-content-analyzer` precedent) | Direct |
| C3 | Architecture must apply to all roles; per-role configuration only | Direct |
| C4 | Single user for now | Direct |
| C5 | OSS components, no vendor lock-in | Direct |
| C6 | "Learning project as much as useful product" — favor approaches that surface generative-UI concepts | Direct |
| C7 | Python harness (Deep Agents primary, MSAF secondary later) must remain the agent runtime | Repo invariant per `CLAUDE.md` |
| C8 | Persona × Role composition and privacy boundary preserved | Repo invariant per `CLAUDE.md` |

---

## Landscape

| Framework | Architecture | Eliminated? | Why |
|---|---|---|---|
| **Thesys C1** (hosted) | LLM → JSON UI spec via hosted API → Crayon SDK renders | Yes | Hosted-only; violates C1 |
| **Vercel AI SDK** (`streamUI`/RSC) | Tools return React Server Components | Yes | Requires Next.js + Node server; Tauri-hostile (C2); awkward from Python (C7) |
| **CopilotKit** | "Copilot embedded in existing React app" | Yes | Wrong shape — assumes the host app exists; we're building one |
| **assistant-ui** | Headless React primitives for chat shell + tool→UI mappers | **Hybrid candidate** | Could provide the chat shell while OpenUI handles message-body rendering |
| **OpenUI** (`thesysdev/openui`, MIT) | LLM emits OpenUI Lang DSL → `<Renderer/>` parses progressively into React | **Recommended** | Self-hostable (C1), Vite-compat (C2), OSS (C5), highest learning value (C6) |
| **AG-UI** (`ag-ui-protocol/ag-ui`) | Event-based SSE wire protocol for agent↔frontend | **Recommended as transport** | Open standard; already in MSAF (C7-future-aligned) and `@openuidev/react-headless` |

---

## Pattern A vs Pattern B

A reframing that anchored the discussion:

| | **Pattern A — Structured-output rendering** | **Pattern B — Generative UI** |
|---|---|---|
| What the LLM emits | Tool calls (which already happens) | UI tree expressed in a DSL |
| Vocabulary | Tool names you've registered | Components you've registered |
| System prompt | Small (tool descriptions) | Larger (UI vocabulary) — *auto-generated* with OpenUI |
| Streaming friendliness | Native (per-token deltas) | Hard with JSON; native with OpenUI Lang |
| Compositional UI | Limited to one tool's output shape | Agent composes layouts |
| Learning value | Moderate (a registry of React components) | High (vocabulary design, prompt design for UI, streaming DSL parsers) |
| Risk of agent misbehavior | Low (tool args are schema-validated) | Moderate (must degrade gracefully on malformed DSL) |
| Cost in extra prompt tokens | None | ~hundreds of tokens per turn (the vocabulary) |
| Token cost in output stream | Same as text reply | ~52% lower than equivalent JSON (per OpenUI benchmarks) |

Pattern B is selected because (a) C6 favors it for learning, (b) OpenUI's three innovations (streaming DSL, auto-generated prompts, typed Zod vocabulary) defuse most of the standard objections to Pattern B, and (c) the teacher role's UI primitives are exactly the kind of bounded vocabulary OpenUI Lang handles well.

---

## OpenUI — what it actually is

Four MIT-licensed packages from `thesysdev/openui` (5,650 stars, updated 2026-05-15, actively developed):

| Package | Role | Adopt? |
|---|---|---|
| `@openuidev/react-lang` | Parser, **streaming renderer**, prompt generation from component library | **Yes** |
| `@openuidev/react-headless` | Chat state, streaming adapters for **OpenAI and AG-UI**, message format converters | **Yes** |
| `@openuidev/react-ui` | Pre-built chat layouts + two component libraries (charts, forms, tables, markdown, syntax highlighting via Radix + Recharts) | **Defer** — start without, adopt selectively if their defaults match what we want |
| `@openuidev/cli` | Scaffolding + system-prompt generation from `library.ts` | **Yes** (as a dev tool, not a runtime dep) |

### Key facts from inspecting the source

- `<Renderer />` props: `response: string \| null` (the accumulated OpenUI Lang text), `library: Library`, `isStreaming?: boolean`, `onAction`, `onStateUpdate`, `onError`, `initialState`, `toolProvider` (function map *or* MCP client), `onParseResult`.
- The renderer's `ElementErrorBoundary` deliberately shows the **last successfully rendered children** when a render error occurs — preventing UI blank-out during streaming or transient evaluation errors.
- `onError` returns structured `OpenUIError[]` shaped for LLM correction loops (unknown components, missing required props, tool-not-found) — designed for self-healing prompts.
- The package exports `createParser` and `createStreamingParser` from `lang-core` for backend use, plus `generatePrompt` "with no Zod deps — usable on backend." The JS parser is intended to run server-side in Node; for us it stays client-side.
- Peer deps: React 18.3+ or 19, Zod 3.25+ or 4, optional `@modelcontextprotocol/sdk`. **No Next.js, no React-DOM in `react-lang`** — pure Vite-compat.

### OpenUI Lang in one snippet

```
root = Stack([
  LessonStep(step=3, total=7, title="Decorators", children=[
    CodeBlock(lang="python", code="...")
  ]),
  Quiz(prompt="What does @decorator do?", options=[...])
])
```

Line-oriented; stream-parseable (the renderer can mount `Stack` before children finish); LLM emits it progressively; UI grows top-down: layout first, data fills in.

### Format-stability risk

OpenUI Lang is at **v0.5** (v0.5 "extends v0.1 with reactive state, data fetching, built-in functions" per the repo). Breaking changes before v1.0 are likely. This is acceptable for a learning project but should be tracked. Migration cost is bounded: roles' prompt addenda + renderer setup. Not vendor lock-in (it's MIT) but **format-stability lock-in**.

---

## AG-UI — the transport finding

`@openuidev/react-headless` depends on `@ag-ui/core`. AG-UI is the **Agent-User Interaction Protocol** — an open, event-based SSE protocol introduced by the CopilotKit team and now community-maintained at `ag-ui-protocol/ag-ui`.

### What it gives us

- ~16 event types in 5 categories: **Lifecycle** (run start/end), **Text Messages** (`TEXT_MESSAGE_START / _CONTENT / _END`), **Tool Calls**, **State Management** (`STATE_DELTA`), **Custom**.
- SSE-based by default; WebSocket as needed.
- Already integrated with **Microsoft Agent Framework** (the planned secondary harness per `CLAUDE.md`'s `ms-graph-extension` phase) and **Pydantic AI**.
- Maps cleanly onto Deep Agents/LangChain event streams (text deltas + tool events are the LangChain default; AG-UI is essentially a normalization layer over that).

### Why this matters specifically for this repo

- **Cross-harness uniformity.** Today: Deep Agents. Later: MSAF. If both speak AG-UI, the frontend has one wire format regardless of which harness is active. That's directly aligned with the persona/role/harness layering in `CLAUDE.md`.
- **One less bespoke schema to invent.** Avoids the discriminated-union-event-format I sketched in earlier drafts. We pick up validation, tooling, and ecosystem.
- **Future MCP clients.** If a personal-assistant component (e.g., a quiz answer block) needs to call a tool from inside the UI, both `<Renderer toolProvider={…} />` and AG-UI accommodate MCP-compatible providers natively.

### Open question

**Does the Deep Agents / LangChain integration already exist?** The AG-UI repo lists multiple framework integrations; need to verify LangChain/LangGraph specifically. If not, we'd write a thin adapter — Deep Agents emits LangChain events; the adapter translates to AG-UI event types. Estimated effort: 1–2 days. Not a blocker; flagged for `/plan-feature` of `harness-ag-ui-bridge`.

---

## Recommended architecture

```
┌─────────────────────────────────────────────┐
│  Browser (Vite SPA, later Tauri wrap)      │
│  ┌───────────────────────────────────────┐ │
│  │ Chat shell (custom or react-ui)       │ │
│  │  ┌─────────────────────────────────┐  │ │
│  │  │ Assistant message body          │  │ │
│  │  │   <Renderer                     │  │ │
│  │  │     response={openUILangBuf}    │  │ │
│  │  │     library={teacherLib}        │  │ │
│  │  │     isStreaming={!done}         │  │ │
│  │  │     onAction={handle}           │  │ │
│  │  │     onError={correctionLoop}    │  │ │
│  │  │   />                            │  │ │
│  │  └─────────────────────────────────┘  │ │
│  │  Chat state via @openuidev/          │ │
│  │  react-headless (AG-UI adapter)       │ │
│  └───────────────────────────────────────┘ │
└──────────────────┬──────────────────────────┘
                   │ SSE (AG-UI events)
                   ▼
┌─────────────────────────────────────────────┐
│  FastAPI app (Python)                       │
│  /chat (POST → SSE) emits AG-UI events:    │
│    RUN_STARTED                              │
│    TEXT_MESSAGE_START / _CONTENT / _END    │
│    TOOL_CALL_START / _ARGS / _END          │
│    STATE_DELTA                              │
│    RUN_FINISHED                             │
└──────────────────┬──────────────────────────┘
                   │ Python function call
                   ▼
┌─────────────────────────────────────────────┐
│  src/assistant/  (existing)                 │
│  ├── core/        persona × role compose    │
│  ├── harnesses/                             │
│  │    ├── deep_agents/    (primary)         │
│  │    └── ms_agent_framework/  (later)      │
│  └── extensions/  Gmail, GCal, GDrive, MS  │
│                                             │
│  Role system prompt is augmented with:      │
│    1. Existing role behavior prompt         │
│    2. Generated OpenUI Lang vocabulary      │
│       (from <roleName>/library.ts in TS,    │
│        exported as text for the prompt)     │
└─────────────────────────────────────────────┘
```

### Where each new concern lives

| Concern | Location | Visibility |
|---|---|---|
| AG-UI emitter (LangChain → AG-UI events) | `src/assistant/transports/ag_ui/` (new) | Public |
| FastAPI SSE app | `src/assistant/web/app.py` (new) | Public |
| Frontend SPA | `web/` (new, sibling of `src/`) | Public |
| Component library definitions (`library.ts`) | `web/src/libraries/<role>.ts` | Public (the components themselves) |
| Role↔library mapping | `roles/<role>/role.yaml` gains a `ui:` block | Public (default), per-persona override allowed |
| Persona-specific renderers | `personas/<name>/web/components/` (only if needed) | Private (via submodule) |

The privacy boundary stays clean: renderer code is public, persona configuration of which renderers a role uses can be private.

---

## Phased OpenSpec plan (proposed, not yet specced)

Five changes, each independently shippable and reversible:

1. **`harness-ag-ui-bridge`** — Python AG-UI emitter + FastAPI SSE endpoint. No UI yet. Verifiable with `curl -N` to the SSE endpoint and observing well-formed AG-UI events. Test against both `text_role` (chat) and a tool-using role to validate text + tool event types.

2. **`web-frontend-shell`** — Vite + React + Tailwind SPA, wired to `@openuidev/react-headless` AG-UI adapter, plain text rendering of assistant messages (no OpenUI Lang yet). Verifiable end-to-end as a "terminal in a browser" — confirms transport works.

3. **`openui-lang-rendering`** — Adopt `@openuidev/react-lang`. Define a minimal shared component library (`Text`, `CodeBlock`, `Callout`, `Markdown`). Wire the assistant message body to `<Renderer/>` with `response={accumulatedBuf}`. Teach one simple role the vocabulary; verify rendering, error degradation, and the `onError` correction-loop hook.

4. **`teacher-ui-vocabulary`** — Define teacher's full primitives: `LessonStep`, `CodeBlock` (with run/copy), `Quiz`, `FreeResponse`, `ProgressIndicator`, `MermaidDiagram`. Generate the prompt addendum via `@openuidev/cli`. Update teacher's role prompt to use it. Run end-to-end teacher session, capture failure modes.

5. **`tauri-shell`** — Wrap the Vite SPA in Tauri for a desktop experience. Likely uncomplicated since we never adopted SSR. Validate: file-system isolation, persistent local state, dock/menu integration.

Each phase is the right size for `/plan-feature` and `/implement-feature`. Each can stop being worked on without leaving the codebase broken.

---

## Open questions to resolve at `/plan-feature` time

These are deliberately deferred until the first OpenSpec change is being scoped:

1. **LangChain → AG-UI adapter.** Does `ag-ui-protocol/ag-ui` ship one? If not, we write it. Size: small; risk: low (the LangChain event vocabulary is well-known).
2. **Tool-call round-tripping.** When a rendered `Quiz` component fires an answer event, how does it become the next user turn? AG-UI has `TOOL_CALL_*` event types; need to verify the round-trip pattern (likely just a new user-message event with structured content).
3. **Streaming buffer management.** Should the frontend re-render on every `TEXT_MESSAGE_CONTENT` chunk or debounce? React 18 concurrent rendering may make this a non-issue; verify with a token-heavy load.
4. **`react-ui` adoption decision.** Build a custom chat shell on shadcn/ui, or take `@openuidev/react-ui`'s pre-built layouts? Tradeoffs: time vs. visual control, Radix dependency surface vs. shadcn copy-in, theme system. Decision deferred until `web-frontend-shell` is being designed.
5. **AG-UI version pinning.** Pre-1.0 protocol; pick a version and document the upgrade policy.
6. **OpenUI Lang version pinning.** Same — currently v0.5; document upgrade policy and which version each role's vocabulary is authored against.
7. **`<Renderer toolProvider />` use case.** Do any v1 components need in-UI tool calls (e.g., quiz grading via a backend tool), or do all interactions roundtrip through a new user-turn? Architectural choice; affects API surface.

---

## Risks / things to watch

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenUI Lang breaking change before our v1 ships | Medium | Low (we own the renderers, prompts) | Pin version, manual upgrade per change |
| AG-UI breaking change | Medium | Low–Medium | Same; smaller surface area |
| LangChain AG-UI adapter doesn't exist and is harder than expected | Low | Medium | Spike during `harness-ag-ui-bridge` planning |
| The agent does not reliably emit valid OpenUI Lang | Medium initially | Medium | The `onError` correction-loop hook exists by design; budget prompt iteration time |
| `react-ui` carries unwanted visual opinions | Low | Low | Defer adoption; build minimal shell first |
| Two-LLM-call temptation (text then UI) creeps back in | Low | High | Architectural principle: agent emits OpenUI Lang *directly* as part of its response; no synthesis step |
| Privacy boundary leaks via UI assets in submodules | Low | High | Stay disciplined: renderer code public, only configuration in submodules; extend the two-layer privacy guard if any assets land in submodules |

---

## What this design teaches (the learning-project lens)

Per C6, here's what we expect to surface as concepts while building:

- **Generative UI vocabulary design.** How to choose primitives (broad enough for compositional freedom, narrow enough to keep prompts small and validate).
- **Streaming DSL design.** Why JSON is awkward for streaming, why line-oriented DSLs aren't, how progressive parsing works.
- **Prompt engineering for UI generation.** How adding a vocabulary to a system prompt changes model behavior; how to debug malformed output; the `onError` self-healing loop pattern.
- **Agent-frontend protocols.** AG-UI as an example of standardizing what was previously bespoke. Comparing it to OpenAI's streaming format, LangChain's event vocabulary, MCP, etc.
- **Architectural decoupling via standards.** Two open standards (AG-UI + OpenUI Lang) for two concerns (transport + rendering) — and how that hedges against vendor or framework changes.
- **The harness boundary as the right seam.** Reaffirming that the UX layer is not a Python rewrite — it's an adapter at the harness boundary, the same shape as the planned MSAF integration.

---

## Decision record

- **Eliminated:** Thesys C1 (hosted), Vercel AI SDK + RSC (Next-coupled, Tauri-hostile), CopilotKit (wrong shape).
- **Adopted as transport:** AG-UI protocol over SSE.
- **Adopted as rendering format:** OpenUI Lang via `@openuidev/react-lang`.
- **Adopted as chat state:** `@openuidev/react-headless` (AG-UI adapter).
- **Deferred:** `@openuidev/react-ui` adoption — decide during `web-frontend-shell` phase.
- **Deferred:** Tauri wrapper — last phase.
- **Pattern:** Pattern B (generative UI), specifically because OpenUI's three innovations (streaming DSL, auto-generated prompts, typed bounded vocabulary) address the standard Pattern B drawbacks.
- **Frontend stack:** Vite + React 19 + Tailwind + shadcn/ui (TBD whether to add `@openuidev/react-ui` later).

---

## Next step

Run `/plan-feature` on **`harness-ag-ui-bridge`** — the smallest valuable slice: Python emits AG-UI events from the Deep Agents harness over a FastAPI SSE endpoint, verified with `curl -N`. No frontend yet. Captures the wire format decision and proves Python↔AG-UI integration before building any UI.
