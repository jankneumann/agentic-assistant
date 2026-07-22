# Dependabot Vulnerability Triage — 2026-07-16

> **Integration addendum (main branch, 2026-07-16).** This triage ran in a
> worktree branched before the X3 dependency changes. On the current branch,
> the X3 re-lock (gen-eval removal + agent-framework-core/openai 1.10 pins)
> already **removed aiohttp, python-multipart, and mem0ai from the dependency
> graph entirely**, structurally resolving their advisories (11 aiohttp CVEs,
> 3 python-multipart, 1 mem0ai pickle-RCE). The remaining 11 bumps below were
> re-applied on the current lock via targeted `uv lock --upgrade-package`;
> starlette remains pin-blocked by `fastapi>=0.115,<0.116` as analyzed below.
> Gates after integration: 981 passed / 3 skipped, ruff clean, mypy clean.



Triage of the 37 Dependabot alerts reported on the default branch of
`jankneumann/agentic-assistant` (Dependabot aggregate: **8 high, 19
moderate, 10 low**). Work performed in an isolated worktree
(`worktree-agent-a2ebd6eaaf9637d02`).

## TL;DR

- **37 unique advisories across 14 packages** — enumerated locally and
  reconciled 1:1 with the Dependabot count.
- **29 advisories fixed** via targeted `uv lock --upgrade-package` bumps
  (12 packages). Full test suite green (**981 passed, 3 skipped**), ruff
  clean.
- **8 advisories deferred**: 7 × `starlette` (blocked by the tight
  `fastapi>=0.115,<0.116` pin) + 1 × `mem0ai` (only fix is a pre-release,
  `2.0.0b2`, and the package is unreachable in this deployment).
- No source code changed. No major-version *application* constraints
  relaxed. `cryptography` moved 46→48 as a single targeted transitive
  bump (see note).

## Methodology & a caveat on severity

Enumeration was done **locally**, not via a Dependabot MCP tool (none is
exposed) and not via `gh` (not installed). The egress proxy in this
sandbox **allows only PyPI** (`pypi.org`, `files.pythonhosted.org`);
`api.osv.dev`, `deps.dev`, and `github.com` all return `403`/tunnel
rejects. `uvx pip-audit` also could not run its pip dry-run resolution
(Windows-only `pywin32` + Python-version-pinned transitive deps break the
throwaway resolver).

Approach that worked:

1. Parsed the resolved dependency set out of `uv.lock` (235 registry
   packages) into pinned `name==version`.
2. Queried the **PyPI JSON API** (`/pypi/<name>/<version>/json`), whose
   `vulnerabilities[]` array mirrors the OSV/GHSA database, for every
   locked version. 67 raw records → **37 unique advisories** after
   collapsing GHSA/PYSEC/CVE aliases.
3. Built the direct-vs-transitive graph from `uv.lock` (forward +
   reverse edges from the `assistant` root).

**Severity caveat:** PyPI's vulnerability records carry `summary`/`details`
but **not** GitHub's severity label or CVSS. Because the GitHub Advisory
DB, OSV, and deps.dev are all proxy-blocked here, per-alert severity could
not be fetched authoritatively. The **aggregate 8/19/10 split is taken
from Dependabot (given)**; the per-item severity in the table below is
**inferred from advisory content** (marked *inf*) and may not match
Dependabot's exact label. Remediation decisions were driven by
fixed-version + reachability, which do not depend on the label.

### Deployment context used for reachability

`agentic-assistant` is a **single-user, local** personal assistant: a
Click CLI plus a **loopback-only** (`127.0.0.1`) FastAPI SSE server whose
`/chat` endpoint consumes **JSON**, not multipart forms. Outbound HTTP is
via **`httpx`** (not `aiohttp`). Per `CLAUDE.md`, the **`agent-framework`
(MSAF) harness and its subtree are stubbed/inactive** on the personal
persona, and the **MS Graph / mem0 extensions are disabled** until the
work persona lands (P15). These facts drive the "reachable?" column.

## Summary table

Legend — Dep: **D**=direct (in `pyproject.toml`), **T**=transitive
(root dep in parens). Sev is *inferred*. Reach: practical reachability in
*this* deployment. Action: ✅ fixed this change / ⛔ deferred.

| Package | Cur → Fixed | Adv. | Sev(inf) | Dep | Reachable? | Action |
|---|---|---|---|---|---|---|
| aiohttp | 3.13.5 → **3.14.1** | CVE-2026-34993 (CookieJar.load RCE) | high | T (agent-framework) | No — MSAF subtree inactive; app uses httpx | ✅ |
| aiohttp | ″ | CVE-2026-50269 (multipart header smuggling) | high | T | No | ✅ |
| aiohttp | ″ | CVE-2026-47265, -54275, -54276, -54278 | moderate | T | No | ✅ |
| aiohttp | ″ | CVE-2026-54273, -54274, -54277, -54279, -54280 | low | T | No | ✅ |
| click | 8.3.2 → **8.4.2** | CVE-2026-7246 (command injection in `click.edit()`) | high | **D** | Low — CLI never calls `click.edit()` with untrusted input | ✅ |
| cryptography | 46.0.7 → **48.0.1** | GHSA-537c-gmf6-5ccf (bundled OpenSSL in wheels) | moderate | T (msal, deepagents, gen-eval) | Low — TLS via bundled OpenSSL | ✅ |
| idna | 3.11 → **3.18** | CVE-2026-45409 (resource-consumption; CVE-2024-3651 redux) | moderate | T (httpx, …) | Yes — httpx resolves outbound hostnames | ✅ |
| langchain | 1.2.15 → **1.3.13** | CVE-2026-55443 (path traversal / glob) | high | **D** | Medium — agent file/glob tooling | ✅ |
| langchain-anthropic | 1.4.0 → **1.4.8** | CVE-2026-55443 (same) | high | **D** | Medium | ✅ |
| langgraph-checkpoint | 4.0.1 → **4.1.1** | CVE-2026-48775 (checkpoint deserialization → object reconstruction) | high | T (langchain→langgraph) | Low — checkpoints are local/trusted | ✅ |
| langgraph-sdk | 0.3.13 → **0.4.2** | CVE-2026-48776 (path injection in request paths) | moderate | T (langchain→langgraph) | No — platform SDK client not used | ✅ |
| langsmith | 0.7.31 → **0.10.5** | CVE-2026-45134 (prompt-pull) | moderate | T (deepagents, langchain-core) | Low — tracing/hub opt-in | ✅ |
| langsmith | ″ | GHSA-f4xh-w4cj-qxq8 (TracingMiddleware SSRF-class) | moderate | T | No — middleware not served | ✅ |
| pydantic-settings | 2.13.1 → **2.14.2** | GHSA-4xgf-cpjx-pc3j (`secrets_dir` traversal) | moderate | **D** | Low — secrets_dir is local/trusted | ✅ |
| pyjwt | 2.12.1 → **2.13.0** | CVE-2026-48525 (detached-JWS verify bypass) | high | T (msal, gen-eval) | Low — MS auth disabled on personal persona | ✅ |
| pyjwt | ″ | CVE-2026-48522, -48523, -48526 | moderate | T | Low | ✅ |
| pyjwt | ″ | CVE-2026-48524 (JWKS-fetch DoS) | low | T | Low | ✅ |
| python-multipart | 0.0.27 → **0.0.32** | CVE-2026-53538, -53539, -53540 (form-parse DoS) | moderate | T (fastapi, gen-eval→fastmcp) | Low — SSE `/chat` takes JSON, loopback-only | ✅ |
| starlette | 0.46.2 → *(blocked)* | CVE-2025-54121 (multipart spool blocking DoS) | moderate | T (fastapi) | Low — loopback-only, single-user | ⛔ |
| starlette | ″ | CVE-2025-62727 (Range-header quadratic DoS) | moderate | T | Low | ⛔ |
| starlette | ″ | CVE-2026-48710 (Host-header URL reconstruction) | moderate | T | Low | ⛔ |
| starlette | ″ | CVE-2026-48818 (StaticFiles traversal, Windows) | moderate | T | No — Linux, no StaticFiles mount | ⛔ |
| starlette | ″ | CVE-2026-54282 (path not validated pre-reconstruction) | moderate | T | Low | ⛔ |
| starlette | ″ | CVE-2026-48817 (HTTPEndpoint method handling) | low | T | Low | ⛔ |
| starlette | ″ | CVE-2026-54283 (`form()` max_fields bypass DoS) | low | T | Low | ⛔ |
| mem0ai | 1.0.11 → *(prerelease only)* | CVE-2026-7597 (`pickle.load/dump` RCE) | high | T (agent-framework→…→mem0) | No — MSAF/mem0 inactive | ⛔ |

Co-upgrades pulled in by the resolver to satisfy the above (not
independently vulnerable, all within-major): `anthropic` 0.94→0.116,
`langchain-core` 1.4.0→1.4.9, `langchain-protocol` 0.0.15→0.0.18,
`langgraph` 1.1.6→1.2.9, `langgraph-prebuilt` 1.0.9→1.1.0; `websockets`
16.0→15.0.1 (a *downgrade* the new constraint set selected — verified
harmless by the green suite).

## High-severity detail (inferred-high items)

All eight inferred-high advisories are **fixed** except `mem0ai`
(deferred, and unreachable). Reachability is the operative axis here, not
the label:

1. **aiohttp CVE-2026-34993 — `CookieJar.load()` arbitrary code
   execution** (→3.14.1). Highest raw impact of the set, but `aiohttp`
   enters the graph *only* through `agent-framework →
   agent-framework-azurefunctions → azure-functions-durable`. That subtree
   is a stub/inactive on the personal persona, and the app's own HTTP
   client is `httpx`. **Not reachable today**; fixed for free.
2. **aiohttp CVE-2026-50269 — multipart-header request smuggling**
   (→3.14.1). Same unreachable path. Fixed.
3. **click CVE-2026-7246 — command injection in `click.edit()`**
   (→8.4.2). `click` is a direct dep and powers the CLI, but the
   vulnerable sink (`click.edit()`, which shells out to `$EDITOR`) is only
   dangerous with attacker-controlled `text`/`editor`. A grep of `src/`
   shows no `click.edit()` usage. **Low practical risk**; fixed anyway.
4. **langchain / langchain-anthropic CVE-2026-55443 — path traversal in
   path/glob-resolving components** (→1.3.13 / →1.4.8). Both are direct
   deps and central to the agent. Reachable if agent tools resolve
   filesystem paths/globs from model- or user-supplied strings — plausible
   in an assistant. **Highest genuinely-reachable item; fixed.**
5. **langgraph-checkpoint CVE-2026-48775 — checkpoint deserialization
   reconstructs Python objects** (→4.1.1). RCE-class *if* an attacker can
   plant checkpoint payloads; checkpoints live in the app's own
   local/trusted store, so exposure is low for a single-user local app.
   Fixed.
6. **pyjwt CVE-2026-48525 — detached-JWS verification bypass** (→2.13.0).
   Matters where JWTs from untrusted issuers are verified; here `pyjwt`
   arrives via `msal`, and MS auth is disabled on the personal persona
   until P15. Low now; fixed pre-emptively.
7. **mem0ai CVE-2026-7597 — `pickle.load/dump` RCE** (→ only `2.0.0b2`).
   Reached only through the inactive `agent-framework → …→ mem0` subtree.
   **Deferred** — see below.

## Won't-fix / accepted-risk

### starlette (7 advisories) — blocked by the FastAPI pin

`pyproject.toml` pins `fastapi>=0.115,<0.116`. FastAPI 0.115.x caps
`starlette<0.47`, so the resolver keeps `starlette==0.46.2`; every fix
requires `0.47.2`+ (and most require `1.x`). Confirmed empirically:
`uv lock --upgrade-package starlette` produces **no change**.

- **Why accept for now:** the FastAPI surface is **loopback-only
  (`127.0.0.1`), single-user**, and `/chat` consumes JSON rather than
  multipart forms; the advisories are DoS / Host-header / Windows-
  StaticFiles issues with no untrusted network reaching the socket. Real-
  world exposure is low.
- **Remediation path (follow-up):** relaxing the pin to
  `fastapi>=0.115,<1` (which the comment in `pyproject.toml` deliberately
  tightened as "the wire surface") pulls a newer `starlette` and would
  clear all 7. That is a deliberate constraint change with wire-surface
  regression risk and should be its own reviewed change — out of scope for
  a minimal dependency bump. **Recommended as a fast follow.**

### mem0ai (1 advisory) — only a pre-release fixes it

`CVE-2026-7597` (`pickle` RCE) is fixed only in `mem0ai==2.0.0b2`, a
**pre-release major**. `uv` will not select it without an explicit
pre-release opt-in, and pinning an app to a beta major of a transitive
dep is inappropriate.

- **Why accept:** `mem0ai` is reached **only** through
  `agent-framework → agent-framework-core → agent-framework-mem0 → mem0ai`
  — the MSAF harness/mem0 integration that is **stubbed and inactive** on
  the personal persona. The vulnerable `pickle` path is not executed.
- **Follow-up:** revisit once `mem0ai` ships a stable `2.x`, or when/if the
  MSAF+mem0 path is activated on the work persona.

## Actions taken

- `uv lock --upgrade-package` for the 12 fixable packages (targeted, no
  blanket upgrade). Resulting lock passes `uv lock --check`.
- Validated by installing the 18 changed distributions into a clone of the
  project venv and running the full suite against the worktree source:
  **981 passed, 3 skipped** (identical to the pre-bump baseline); `ruff
  check src tests` clean.
- Committed `uv.lock` + this report as a single commit on the worktree
  branch. **Not pushed.**

### Environment note (not committed)

`uv lock`/`uv sync` cannot run out-of-the-box in this worktree because the
`gen-eval` workspace source (`[tool.uv.sources] gen-eval = { path =
"../agentic-coding-tools/packages/gen-eval" }`) is **absent** from this
environment. To let the real `uv` resolver run, a **metadata-faithful
stub** of `gen-eval` (matching the locked `requires-dist` exactly) was
created *outside* the git tree at
`.claude/worktrees/agentic-coding-tools/packages/gen-eval`. It is not
tracked, does not affect the resolved graph (the `gen-eval` lock entry is
unchanged), and can be deleted. On a machine with the real workspace
checked out, re-running the same `uv lock --upgrade-package …` set
reproduces this `uv.lock`.
