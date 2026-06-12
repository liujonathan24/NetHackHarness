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
