# harness-routing — Tasks

## 1. Rule schema + persona wiring

- [x] 1.1 `core/harness_routing.py` — `HarnessRoutingRule`,
  `HarnessRoutingError`, `parse_harness_routing` (shape validation:
  list of mappings, keys `role`/`tools`/`harness`, at least one
  matcher, non-empty strings), `rule_matches` +
  `role_prefers_ms_tools` matching helpers
- [x] 1.2 `core/persona.py` — pop `harnesses.routing:` at load, parse
  onto `PersonaConfig.harness_routing` with persona/config-path error
  context (same posture as models/guardrails/schedules)
- [x] 1.3 `personas/_template/persona.yaml` — commented
  `harnesses.routing:` example + schedules `harness:` key doc

## 2. Factory selection

- [x] 2.1 `harnesses/factory.py` — `select_harness(persona, role, *,
  requested=None)`: explicit → rules (first match; disabled target
  skipped with WARNING; unknown/host target raises) → built-in
  defaults (MS-source preferred_tools + MSAF enabled → MSAF; else
  deep_agents; else remaining enabled SDK harness; else actionable
  ValueError). Host harnesses never auto-selected.
- [x] 2.2 Routing decision telemetry — `harness.routing` span via
  `start_span` escape hatch + INFO log line; defensive emission

## 3. CLI + scheduler consumption

- [x] 3.1 `cli.py run` — `-H` choice gains `auto`, default `auto`,
  resolved via the `_select_harness` seam after role load
- [x] 3.2 `cli.py serve` — default `auto`, resolved before
  `create_harness` validation and `make_app`
- [x] 3.3 `cli.py daemon` — default `auto`; per-job startup
  validation of `job.harness or -H` resolution (replaces the single
  stale-role check); `--serve` resolves the AG-UI app harness against
  the persona default_role
- [x] 3.4 `core/scheduler.py` — `ScheduledJob.harness` (optional,
  default inherit), `_JOB_KEYS` + parse validation,
  `HarnessJobRunner.run` per-run resolution

## 4. Tests + gates

- [x] 4.1 `tests/test_harness_selection.py` — precedence order,
  MS-source detection, disabled-harness fallback, host-never-auto,
  rule first-match/globs/skip/raise, parse errors, telemetry span
- [x] 4.2 CLI tests — `run`/`serve`/`daemon` auto default resolution +
  explicit override passthrough
- [x] 4.3 Scheduler tests — job `harness:` parse + runner override /
  inherit / auto paths
- [x] 4.4 Gates: `uv run pytest tests/`, `ruff check src tests`,
  `mypy src tests`, `openspec validate harness-routing --strict`

## 5. Docs

- [x] 5.1 CLAUDE.md — harness routing note (auto default, precedence,
  host-tier explicit-only)
