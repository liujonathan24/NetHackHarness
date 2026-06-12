## Context

Continual Harness (arXiv:2605.09998) is already implemented here: `refiner.py`
holds `OfflineRefiner` (no-op) and `TeacherLLMRefiner` (calls an OAI/Anthropic
endpoint and emits CRUD edits over `p`/`G`/`K`/`M`); `prompt_spec.py` wires the
`CH` variant via `_ch_refiner_hook` + `_ch_subagents_hook`; `exp16_obs_variants.py`
defines a `CH` cell; `tests/test_refiner.py` locks parts of the contract. What is
missing is any **real CH eval result**. Wave-1 ran only `P` (same-model
self-refinement directive) at 200 turns, n=3 — tied B1, as predicted. The Haiku
promotion stage, which could have provided a stronger teacher, failed silently
because the Anthropic key was not provisioned on the hosted runner.

The root causes are operational, not algorithmic: (1) a missing teacher credential
degraded the refiner to a silent no-op; (2) only the degenerate `P` stand-in was
ever measured; (3) the one CH-shaped run was underpowered and too short.

## Goals / Non-Goals

**Goals:**
- Make `variant=CH` actually run a separate teacher model end-to-end, locally
  first (trivial credentials), then on hosted/sandbox.
- Eliminate the silent-no-op failure mode: misconfigured CH fails loud and
  attributable.
- Capture the refiner's per-interval edits so we can see whether refinement fired
  and what it changed.
- Produce the first adequately-powered CH-vs-B1 comparison (≥500 turns, enough
  seeds for a hypothesis test) on a matched seed set + policy.

**Non-Goals:**
- Layer-2 optimization of the refiner's prompt/config (refine_interval sweep,
  teacher-prompt search). That is the *next* change; it has nothing to optimize
  until a real CH baseline exists.
- Inventing a new refinement algorithm. We run the paper's mechanism as-built.
- Online cross-episode continual play (`continual=True` reseeding) — orthogonal;
  not required to measure single-episode CH lift.
- Changing any observation encoding or the B1 baseline.

## Decisions

**D1 — Run locally first, with env-var teacher credentials.** The dominant
failure was credential provisioning on the hosted runner. Local `prime eval` /
`vf-eval` inherits the shell environment, so a teacher key (`REFINER_API_KEY` /
`ANTHROPIC_API_KEY`) is available with zero infra work. We get the first real
number locally, then document the hosted/sandbox secret-injection path as a
separate, verifiable step. *Alternative considered:* fix hosted secrets first —
rejected because it blocks the result on infra we don't need for the measurement.

**D2 — Fail loud on missing/!separate teacher, don't degrade.** `load_environment`
constructing a `CH` env without a resolvable teacher credential, or with a teacher
equal to the policy, must raise or record an explicit, results-visible error. The
no-op `OfflineRefiner` stays for tests but a run using it is marked "not a real CH
run." *Alternative:* warn-and-continue — rejected; that is precisely how wave-1
lost 12 jobs with "no error_message."

**D3 — Capture edits in the existing trace.** `trace_dir` already writes per-turn
NDJSON. Add the refiner's CRUD diff (including no-ops) to the per-interval record,
reusing `RefinerEdits.to_trace_dict()`. This makes "did refinement fire / take
effect" answerable from the trace, decoupling mechanism-verification from the
score. *Alternative:* a separate edits log — rejected; one trace is simpler and
the viewer already reads NDJSON.

**D4 — Reuse the wave-1 aggregation, not a new metrics path.** CH-vs-B1 goes
through `exp16_obs_variants.py` (add a teacher-model arg + 500-turn config) and
`tools/compare_evals.py` for Welch-t / Mann-Whitney, matching how every other
variant was judged. *Alternative:* bespoke CH script — rejected for
comparability; a thin focused launcher is acceptable if exp16 is awkward.

**D5 — Teacher choice: stronger-than-policy.** Default intent is a frontier
teacher (Opus/Haiku-class) refining a weaker open policy (e.g. Qwen3.5-9B), per
the paper's process-reward co-learning premise. The teacher arg is explicit so the
asymmetry is a deliberate, recorded choice.

## Data flow

```
policy model ── acts ──> rollout (env_response) ──> trajectory window
                                   │ every refine_interval turns
                                   ▼
                         TeacherLLMRefiner.refine(window)  ── teacher model (M_t)
                                   │  RefinerEdits {p,G,K,M}
                                   ▼
              apply_edits(state) → system addendum / sub-agents / macros / journal
                                   │
                                   ▼
                    trace NDJSON  (+ per-interval edit diff)   →  compare_evals (CH vs B1)
```

## Risks / Trade-offs

- **Teacher cost.** A frontier teacher firing every interval over a 500-turn
  rollout × seeds is non-trivial spend. → Start with a small seed set + a
  cost-aware teacher (Haiku-class), report teacher tokens separately, scale only
  after the directional signal.
- **CH may still tie B1.** A real result could be negative. → That is an
  acceptable, publishable outcome; the spec requires reporting underpowered/null
  results honestly rather than as a verdict. The edit capture (D3) lets us
  diagnose *why* (refiner not firing vs. firing-but-useless).
- **Code-mode perf bug interaction.** Wave-1 noted code-mode rollouts hung >2h
  ("Python loops executing many ticks without yielding"). CH uses the skill
  interface, not code-mode, so it should be unaffected — but if `K` macros get
  large, watch rollout wallclock. → Keep `CH` on the skill interface for the first
  run.
- **Same-model guard false positives.** Legitimately wanting policy==teacher for a
  control arm. → Allow an explicit `--allow-same-teacher` escape hatch that records
  the run as a `P`-equivalent control, not a real CH run.

## Migration Plan

1. Land refiner credential-resolution + fail-loud + edit-capture (with tests).
2. Local CH-vs-B1 smoke (1 seed, short) to confirm the teacher actually fires and
   edits appear in the trace.
3. Local CH-vs-B1 real run (≥500 turns, ≥ planned seeds); aggregate via
   compare_evals.
4. Document hosted/sandbox teacher-secret injection; re-run one seed hosted to
   confirm parity. Rollback is trivial — `CH` is opt-in via `variant`.

## Open Questions

- Exact seed count for adequate power (depends on observed CH variance — set after
  the smoke run).
- Teacher model pick for the first real run: Haiku-class (cheap) vs Opus-class
  (closest to the paper's "frontier teacher"). Resolve at build time per budget.
