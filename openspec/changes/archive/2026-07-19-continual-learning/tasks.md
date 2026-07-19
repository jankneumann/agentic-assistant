# continual-learning — Tasks

## 1. Config + feedback abstraction

- [x] 1.1 `core/learning.py`: `LearningConfig` + `parse_learning_config`
      (actionable errors; falsy default = dormant), `require_learning`
- [x] 1.2 Wire `learning:` into `PersonaConfig` + `PersonaRegistry.load`
      (+ annotated section in `personas/_template/persona.yaml`)
- [x] 1.3 `FeedbackEvent` (closed source vocabulary, payload round-trip)
      + `record_feedback` / `list_feedback` over the interactions table
      (`metadata.source=feedback`); `learning.feedback` audit span

## 2. Machine collectors (read-what-exists, no daemons)

- [x] 2.1 `collect_eval_feedback` (run-gate output parse: FAIL/SKIP/PASS)
- [x] 2.2 `collect_guardrail_feedback` (budget utilization ≥ 80% from the
      spend ledger)
- [x] 2.3 `collect_resilience_feedback` + read-only
      `CircuitBreakerRegistry.breakers()` snapshot
- [x] 2.4 `collect_cost_feedback` (unpriced cloud entries under a budget)
      + `collect_machine_feedback` aggregate (gated on learning config)

## 3. Reflection / consolidation

- [x] 3.1 `run_reflection`: watermark-filtered interactions → summary →
      provenance-stamped `learning/reflection/<ts>` fact +
      `learning/last_reflection` watermark; `learning.reflect` span
- [x] 3.2 Model-backed summarizer under the reflection consumer binding
      (`openai-compatible` via `OpenAICompatibleClient`, budget-gated),
      deterministic digest fallback
- [x] 3.3 Graphiti episode write-back via `MemoryManager.store_episode`
      (closes the deferred P21 follow-up)
- [x] 3.4 Scheduler `kind: agent|reflect` job key (parse + runner
      dispatch + daemon up-front validation)

## 4. Proposals + gated apply

- [x] 4.1 `ImprovementProposal` (kind/risk tiering, JSON file
      round-trip, `write_proposal`/`load_proposal`/`list_proposals`)
- [x] 4.2 `derive_proposals` (preference distillation LOW; human/eval →
      prompt_layer MEDIUM; guardrail/cost/resilience → routing_config
      HIGH; provenance merge); `learning.propose` span
- [x] 4.3 `run_eval_gate` (subprocess; SKIP-as-pass-with-warning,
      missing script = SKIP, `EVAL_GATE_SCRIPT` override)
- [x] 4.4 `apply_proposal` (guardrail `learning_apply` → eval gate →
      risk/`--approved`; preference via new
      `MemoryManager.store_preference`; prompt_layer append with
      path-escape check; routing_config review-only); `learning.apply`
      span; `maybe_auto_apply` (opt-in, LOW preference only)
- [x] 4.5 `MemoryManager.store_preference` upsert +
      `trace_memory_op` vocabulary `preference_write`
      (base.py + decorators target extraction + protocol test)

## 5. CLI + REPL

- [x] 5.1 `assistant feedback` (TEXT and/or `--prefer cat:key=value`)
      and REPL `/feedback` (help line updated)
- [x] 5.2 `assistant reflect`
- [x] 5.3 `assistant learning collect|propose|apply|list`
      (`_learning_memory_manager` as the single patchable seam)

## 6. Tests + docs

- [x] 6.1 `tests/test_learning.py` (config, persona load, feedback,
      collectors, reflection, proposals, risk tiering, apply gates,
      auto-apply, gate runner, scheduler kind) with in-memory
      `FakeLearningStore` + fixture persona `learning_lab`
- [x] 6.2 `tests/test_learning_cli.py` (all commands; dormant persona
      refusals; gate-fail refusal; status persistence)
- [x] 6.3 `store_preference` unit tests + telemetry op-vocabulary test
- [x] 6.4 OpenSpec deltas (learning ADDED; cli-interface, scheduler,
      memory-policy ADDED requirements; observability MODIFIED) +
      CLAUDE.md section
