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
