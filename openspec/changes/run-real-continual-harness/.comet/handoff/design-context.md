# Comet Design Handoff

- Change: run-real-continual-harness
- Phase: design
- Mode: compact
- Context hash: 49d2712b567a6cc9d60ca9e4b47255acd7ab52e2fb32abe87c49f89a9f23bd96

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/run-real-continual-harness/proposal.md

- Source: openspec/changes/run-real-continual-harness/proposal.md
- Lines: 1-68
- SHA256: 1f9f12518f36e3c34552ef7a5ecf7b9f916ca73b06f6f83707f0fc15ae1413f2

```md
## Why

The teacher-driven Continual Harness (arXiv:2605.09998) was implemented in this
repo — `refiner.py` (the `TeacherLLMRefiner` + four-pass CRUD over prompt /
sub-agents / skills / memory) and the `CH` variant wired into `nethack.py` and
`exp16_obs_variants.py` — but **it was never actually evaluated**. The wave-1
matrix (`experiments/results/wave1_summary.md`) only ran the degenerate `P`
variant (a self-refinement *directive* where the same model is asked to reflect),
which tied B1 — exactly as `refiner.py`'s own docstring predicted ("collapses to
*ask yourself to think harder*"). The single attempt to put a stronger model in
the loop (the Haiku promotion stage) **failed silently** with "no error_message —
most likely Anthropic API key not provisioned on the hosted runner."

So "CH failed" is an **operational and experimental-design failure, not an
algorithmic one**: the real teacher-driven mechanism has zero eval results on
disk. This change makes teacher-driven CH actually runnable and produces the
first real CH-vs-B1 measurement, which is the prerequisite for any later
prompt/config optimization of the refiner.

## What Changes

- **Credential resolution that fails loud.** The teacher refiner SHALL resolve
  its endpoint/key in the eval process (local env vars; hosted/sandbox injected
  secret). When `variant=CH` is requested but no teacher is configured, the
  rollout SHALL fail loudly (or emit a clearly-marked warning that propagates to
  results) instead of silently degrading to a no-op — the exact failure mode that
  killed the Haiku stage without a trace.
- **Separate, stronger teacher enforced.** `CH` SHALL use a teacher model
  distinct from (and intended to be stronger than) the policy model, guarding
  against the same-model collapse that makes CH equivalent to `P`.
- **Refiner-edit capture.** Each rollout SHALL record the refiner's per-interval
  CRUD edits (the `p`/`G`/`K`/`M` diffs) into the trace, so we can verify
  refinement actually fires and takes effect rather than inferring it from score.
- **Adequately-powered CH-vs-B1 A/B.** A harness SHALL run `CH` against `B1` at a
  horizon long enough for refinement to amortize (max_turns ≥ 500) and with
  enough seeds for a real hypothesis test — not the n=3, 200-turn underpowered
  `P` run.
- **First real result, local-first.** Produce a CH-vs-B1 comparison run locally
  (where teacher credentials are trivial), then document the hosted/sandbox
  secret-injection path so the run is reproducible on Prime infra.

## Capabilities

### New Capabilities
- `continual-harness`: the teacher-driven self-improving harness mechanism —
  teacher/policy separation, credential resolution, fail-loud-on-misconfig,
  refinement cadence, the four CRUD components actually taking effect, edit
  capture, and the CH-vs-baseline evaluation contract.

### Modified Capabilities
<!-- None. The encoding-eval matrix is already "configurable data" (adding CH as a
     cell needs no spec change); the continual-harness mechanism is a new,
     previously-unspecced capability. -->

## Impact

- `environments/nethack/nethack_harness/refiner.py` — credential resolution,
  fail-loud when teacher missing, edit capture.
- `environments/nethack/nethack.py` — `CH` wiring: teacher-model arg, refiner
  construction, threading edits into the trace; same-model guard.
- `experiments/exp16_obs_variants.py` (or a focused new experiment script) —
  CH-vs-B1 launch with a teacher-model argument, longer horizon, adequate n.
- `tests/test_refiner.py` — extend to lock the fail-loud + teacher-separation
  contract.
- `Dockerfile.prime` / sandbox docs — document teacher-credential secret
  injection for hosted/sandbox runs.
- External dependency: a teacher inference endpoint (Anthropic/OpenAI/Prime
  Inference) reachable from the eval process.
```

## openspec/changes/run-real-continual-harness/design.md

- Source: openspec/changes/run-real-continual-harness/design.md
- Lines: 1-122
- SHA256: 47653f86fd46f690476344be257d87e31a4742a44ce49cea31f7029edeff2e2f

[TRUNCATED]

```md
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
```

Full source: openspec/changes/run-real-continual-harness/design.md

## openspec/changes/run-real-continual-harness/tasks.md

- Source: openspec/changes/run-real-continual-harness/tasks.md
- Lines: 1-34
- SHA256: b3a890647997ff7c1b0449b408223d889bd1a58d4a5bf76339c61deb7dedcc9d

```md
## 1. Refiner credential resolution + fail-loud (TDD)

- [ ] 1.1 Add a failing test in `tests/test_refiner.py`: constructing a `CH` env with no resolvable teacher credential raises/records an attributable misconfiguration error (not a silent no-op).
- [ ] 1.2 Add a failing test: `CH` with teacher model == policy model is refused unless an explicit same-teacher escape hatch is set (and that control run is marked `P`-equivalent, not a real CH run).
- [ ] 1.3 Implement teacher credential resolution in `refiner.py` (`REFINER_BASE_URL`/`REFINER_API_KEY` → `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/Prime Inference) and the fail-loud path; wire the check into `nethack.py` `CH` construction. Make 1.1–1.2 pass.
- [ ] 1.4 Ensure a run using the offline/no-op refiner is tagged "not a real CH run" in results metadata; add a test asserting the tag.

## 2. Refiner-edit capture into the trace

- [ ] 2.1 Failing test: a `CH` rollout with a stub teacher writes one edit record per refinement interval (including no-op edits) into the trace via `RefinerEdits.to_trace_dict()`.
- [ ] 2.2 Thread the per-interval CRUD diff into `_write_trace_entry` (or the per-interval record) in `nethack.py`; make 2.1 pass.
- [ ] 2.3 Confirm `run_macro` is exposed to the agent under `variant=CH` (extend the existing `test_refiner.py` macro-exposure assertion if needed).

## 3. CH-vs-B1 launch wiring

- [ ] 3.1 Add an explicit teacher-model argument to the `CH` cell in `experiments/exp16_obs_variants.py` (or a focused launcher), separate from the policy `-m`/model arg.
- [ ] 3.2 Add a 500-turn CH-vs-B1 config (matched seed set, same policy model) that aggregates through `tools/compare_evals.py` (Welch-t / Mann-Whitney, tokens/turn, teacher tokens reported separately).
- [ ] 3.3 Mark results below the configured minimum seed count as preliminary/underpowered, not a verdict.

## 4. Local smoke + first real run

- [ ] 4.1 Local CH-vs-B1 smoke (1 seed, short horizon) with a real teacher key in the shell env; verify from the trace that the teacher fired and edits appear.
- [ ] 4.2 Local CH-vs-B1 real run (≥500 turns, planned seed count); produce a comparison report via `compare_evals` and record the first real CH number.
- [ ] 4.3 Write up the result (CH-on vs CH-off vs B1) in `experiment_log.md`, including whether refinement fired and the edit-capture evidence.

## 5. Hosted/sandbox reproducibility

- [ ] 5.1 Document teacher-credential secret injection for `--hosted`/sandbox runs in `Dockerfile.prime` / eval recipes (the exact gap that killed the Haiku stage).
- [ ] 5.2 Re-run one CH seed hosted/sandbox to confirm the teacher authenticates and parity with the local run; capture in the write-up.

## 6. Verification

- [ ] 6.1 `pytest tests/test_refiner.py -q` green; full `pytest tests/ -q` green.
- [ ] 6.2 Confirm a misconfigured `CH` run now fails loud (manual: launch `CH` with no teacher key, observe attributable error in results).
```

## openspec/changes/run-real-continual-harness/specs/continual-harness/spec.md

- Source: openspec/changes/run-real-continual-harness/specs/continual-harness/spec.md
- Lines: 1-92
- SHA256: 196ee4ec5746071e5ea0396738708638f10136590cecee247980cdb73cb9e1fc

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Teacher model is separate from the policy model

Under `variant=CH`, the refinement teacher SHALL be a model configuration
distinct from the policy (acting) model. The harness SHALL expose a teacher-model
argument independent of the eval's policy model, and SHALL NOT default the teacher
to the policy model. Running the teacher as the same model as the policy collapses
Continual Harness to the degenerate `P` self-refinement directive, which wave-1
already showed ties baseline.

#### Scenario: Teacher configured distinctly from policy
- **WHEN** a `CH` rollout is launched with policy model `M_p` and teacher model `M_t`
- **THEN** the refiner's chat-completion calls go to `M_t`, not `M_p`

#### Scenario: Teacher defaulting to policy is refused
- **WHEN** `variant=CH` is requested with no teacher model specified
- **THEN** the harness SHALL NOT silently reuse the policy model as the teacher; it SHALL surface a misconfiguration (see fail-loud requirement) rather than degrade to same-model refinement

#### Scenario: Separation enforced where the policy identity is observable
- **WHEN** the policy model identity is visible to the environment (e.g. at rollout/`setup_state` time, when the policy client is injected) and it equals the teacher model
- **THEN** the run SHALL be refused as a real CH run unless an explicit same-teacher escape hatch is set, in which case it is recorded as a `P`-equivalent control

#### Scenario: Unobservable policy identity is recorded as an operator assertion
- **WHEN** the environment cannot observe the policy model identity to compare against the teacher
- **THEN** the run SHALL record in its metadata that teacher/policy separation is an unverified operator assertion, so the result is not mistaken for a guaranteed-separate CH run

### Requirement: Teacher credentials resolve in the eval process and fail loud

The teacher refiner SHALL resolve its endpoint and API key from the process
environment (e.g. `REFINER_BASE_URL`, `REFINER_API_KEY`, falling back to
`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/Prime Inference). When `variant=CH` is
requested but no usable teacher credential is resolvable, the rollout SHALL fail
loudly: it SHALL raise or record an explicit, attributable error that propagates
into the run's results, rather than silently producing a no-op refiner. This is
the exact failure mode that killed the wave-1 Haiku promotion stage ("all jobs
FAILED with no error_message — API key not provisioned").

#### Scenario: Missing teacher credential is attributable
- **WHEN** a `CH` rollout starts and no teacher credential can be resolved
- **THEN** the run records a clearly-labelled configuration error identifying the missing credential, and the failure is distinguishable from a normal low-score rollout

#### Scenario: Credential present, refiner active
- **WHEN** a teacher credential is resolvable in the process environment
- **THEN** the refiner issues live teacher calls and is not the offline no-op refiner

#### Scenario: A no-op refiner never masquerades as CH
- **WHEN** the offline/no-op refiner is in effect (e.g. tests, no credential)
- **THEN** the run is not reported as a valid `CH` result; it is marked as not-a-real-CH-run

### Requirement: Refinement fires on cadence and its edits are captured

The refiner SHALL run every `refine_interval` turns over the recent trajectory
window and emit CRUD edits across the four harness components — prompt addendum
`p`, sub-agents `G`, skills/macros `K`, and memory `M`. Each rollout SHALL record
the per-interval edits into its trace so that whether refinement actually fired
and what it changed is inspectable post-hoc, independent of the final score. A
refiner error SHALL be logged and swallowed without killing the rollout.

#### Scenario: Edits are recorded per refinement interval
- **WHEN** a `CH` rollout completes `k` refinement intervals
- **THEN** the trace contains `k` edit records, each capturing the CRUD diff applied to `p`/`G`/`K`/`M` (including no-op edits, marked as such)

#### Scenario: Refiner failure does not abort the rollout
- **WHEN** a teacher call errors mid-rollout
- **THEN** the error is logged, that refinement window is skipped, and the rollout continues

#### Scenario: run_macro tool is available under CH
- **WHEN** `variant=CH` is active
- **THEN** the agent is offered the `run_macro` tool so refiner-authored skills `K` are actually invocable

### Requirement: CH is evaluated against baseline with adequate power and horizon

The change SHALL produce a CH-vs-`B1` comparison run designed so refinement can
amortize and so the result supports a hypothesis test. The run SHALL use a horizon
of at least 500 turns (vs the 200-turn `P` run) and a seed count sufficient for a
Welch-t / Mann-Whitney comparison, reusing the existing aggregation
(`tools/eval_instrument.py`, `tools/compare_evals.py`) rather than a re-implemented
metrics path. The comparison SHALL report CH-on vs CH-off (`B1`) on the same seeds
and the same policy model.
```

Full source: openspec/changes/run-real-continual-harness/specs/continual-harness/spec.md

