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

#### Scenario: CH and B1 compared on matched seeds and policy
- **WHEN** the comparison runs
- **THEN** `CH` and `B1` are evaluated on the same seed set with the same policy model, and aggregated through `summarize_eval` / `compare_evals`

#### Scenario: Horizon long enough to amortize refinement
- **WHEN** the CH comparison is configured
- **THEN** max_turns is at least 500, so refinement has turns over which to take effect

#### Scenario: Underpowered run is not reported as a verdict
- **WHEN** fewer completed seeds than the configured minimum finish
- **THEN** the result is reported as preliminary/underpowered, not as a CH success-or-failure verdict
