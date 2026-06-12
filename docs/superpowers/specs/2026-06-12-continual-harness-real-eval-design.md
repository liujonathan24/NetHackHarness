---
comet_change: run-real-continual-harness
role: technical-design
canonical_spec: openspec
---

# Continual Harness — real teacher-driven eval (technical design)

Requirements are canonical in `openspec/changes/run-real-continual-harness/specs/continual-harness/spec.md`.
This doc covers *how*: implementation approach, boundary conditions, testing.

## Problem recap

`refiner.py` + the `CH` variant exist but were never evaluated; only the
degenerate `P` ran (tied B1), and the one stronger-teacher attempt died on an
unprovisioned key (silent no-op). We make teacher-driven CH runnable, fail-loud,
edit-capturing, and produce the first powered CH-vs-B1 number.

## Implementation approach

### 1. Credential resolution + fail-loud (`refiner.py`, `nethack.py`)
- Add `resolve_teacher() -> TeacherConfig` to `refiner.py`: reads
  `REFINER_BASE_URL` / `REFINER_API_KEY` → `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
  / Prime Inference; raises `CHMisconfigured` when nothing usable resolves.
- In `nethack.py` `CH` construction: if `variant=="CH"`, call `resolve_teacher()`;
  on failure raise (constructor) or stamp `state["ch_error"]` so the failure is
  attributable in results. Never silently fall back to `OfflineRefiner` under
  `CH`. The `OfflineRefiner` path stays for tests but any run using it is tagged
  `ch_real=false` in metadata.

### 2. Teacher/policy separation (boundary condition)
- The policy model is the verifiers client injected at **rollout time**, not known
  at `load_environment` construction. So the separation guard runs where the
  policy id is observable — `setup_state` — comparing teacher id vs policy id.
- Three outcomes (mirrors the spec): equal → refuse unless `allow_same_teacher`
  (then mark `P`-equivalent control); distinct → proceed; policy id unobservable →
  proceed but stamp `teacher_separation: "operator-asserted"` in metadata.

### 3. Edit capture (`prompt_spec.py` `_ch_refiner_hook`, `nethack.py` trace)
- `RefinerEdits.to_trace_dict()` already exists. After each `refiner.refine(...)`,
  append the dict (including no-ops, flagged) to the per-interval trace record in
  `_write_trace_entry`. Decouples "did it fire / change anything" from score.

### 4. Launch + measurement (`exp16_obs_variants.py` / focused launcher)
- `CH` cell gains explicit `teacher_model` → `load_environment(refiner_model=…)`,
  separate from policy `-m`. 500-turn, matched-seed CH-vs-B1, aggregated via
  `tools/compare_evals.py` (Welch-t / Mann-Whitney, tokens/turn, **teacher tokens
  reported separately**). Under-minimum seeds → reported preliminary.

### Model choice (resolves design open question)
- Default pairing: **GLM-5 teacher over a weaker policy** (GLM-4.6 or Qwen3.5-9B)
  — matches the paper's strong-teacher/weak-student premise. GLM is wired as an
  OpenAI-compatible endpoint (new `endpoints.toml` block for policy; `REFINER_*`
  for teacher) with *different model ids* on each surface. Smoke-test GLM
  tool-call shape first (verifiers ToolCall contract is fragile).

## Testing strategy
- Stub teacher (deterministic `RefinerEdits`) → edit-capture test, no API.
- `monkeypatch` credential env → fail-loud + offline-tagging tests.
- Teacher==policy → refused / control-tagged test; unobservable → operator-asserted
  metadata test.
- `run_macro` exposed under `CH` (extend existing assertion).
- All in `tests/test_refiner.py`; `pytest tests/ -q` green gate.

## Risks / trade-offs
- Teacher cost (frontier × 500 turns × seeds) → start cheap/small, scale on signal.
- CH may still tie B1 → report honestly; edit capture diagnoses why.
- Same-model guard needs policy id → handled via observable-where-possible + metadata flag.
- GLM tool-calling compatibility → smoke test before full run; keep CH on skill interface (dodge code-mode perf bug).

## Migration / rollback
Land §1–3 with tests → local smoke (1 seed) confirming teacher fires + edits in
trace → local real run (≥500 turns) → write up → document hosted/sandbox teacher
secret + one hosted parity seed. `CH` is opt-in via `variant`; rollback trivial.
