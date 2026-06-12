---
change: run-real-continual-harness
design-doc: docs/superpowers/specs/2026-06-12-continual-harness-real-eval-design.md
base-ref: 0fb2b931984e099411ce6e13d56cbda47367f867
---

# Continual Harness — real teacher-driven eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `variant=CH` run a real, separate teacher model (fail-loud on misconfig), capture refiner edits into the trace, and produce the first powered CH-vs-B1 result.

**Architecture:** The CH refiner already exists (`refiner.py`) and is wired into the rollout (`_ch_refiner_hook` already stamps `state["_ch_last_edits"]`). The gaps are: (1) `nethack.py` silently falls back to `OfflineRefiner` when no teacher is set — invert to fail-loud; (2) no teacher/policy separation guard; (3) the captured `_ch_last_edits` is not written into the trace; (4) no 500-turn CH-vs-B1 launch config.

**Tech Stack:** Python, verifiers `StatefulToolEnv`, pytest/pytest-asyncio, OpenAI-compatible clients, `tools/compare_evals.py`.

**Key paths:**
- Modify: `environments/nethack/nethack_harness/refiner.py` (add `CHMisconfigured`, `resolve_teacher`)
- Modify: `environments/nethack/nethack.py:251-262` (fail-loud), `setup_state` (separation guard), `_write_trace_entry` call site `:923`
- Modify: `tests/test_refiner.py:169` (invert old fallback test) + new tests
- Modify: `experiments/exp16_obs_variants.py` (CH `teacher_model` + 500-turn config)

**Reinstall note (from AGENTS.md):** after editing `nethack_core/` or `environments/nethack/`, run
`uv sync --extra dev --all-packages --reinstall-package nethack --reinstall-package nethack-core` before pytest, or pytest imports the stale installed copy.

---

### Task 1: Fail loud when CH has no resolvable teacher

**Files:**
- Modify: `environments/nethack/nethack_harness/refiner.py`
- Modify: `environments/nethack/nethack.py:251-262`
- Test: `tests/test_refiner.py`

- [ ] **Step 1: Update the test that locks the OLD behavior to the NEW contract**

Replace `test_load_environment_ch_variant_falls_back_to_offline` (`tests/test_refiner.py:169`) with a fail-loud test:

```python
def test_load_environment_ch_without_teacher_fails_loud(monkeypatch):
    """variant=CH with no refiner_model and no teacher credential must NOT
    silently degrade to OfflineRefiner — it must raise CHMisconfigured."""
    monkeypatch.delenv("REFINER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PI_API_KEY", raising=False)
    from nethack_harness.refiner import CHMisconfigured
    import nethack
    with pytest.raises(CHMisconfigured):
        nethack.NetHackVerifiersEnv(variant="CH")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_refiner.py::test_load_environment_ch_without_teacher_fails_loud -v`
Expected: FAIL — `CHMisconfigured` does not exist / no exception raised.

- [ ] **Step 3: Add `CHMisconfigured` + `resolve_teacher` to `refiner.py`**

Add near the top of `refiner.py` (after imports):

```python
class CHMisconfigured(RuntimeError):
    """variant=CH was requested but the teacher is not usably configured."""


def resolve_teacher(refiner_model: Optional[str]) -> dict:
    """Return a usable teacher client config or raise CHMisconfigured.

    Resolution order for the key: REFINER_API_KEY -> ANTHROPIC_API_KEY ->
    OPENAI_API_KEY -> PI_API_KEY. Base URL from REFINER_BASE_URL (else the
    anthropic default already used by TeacherLLMRefiner).
    """
    if not refiner_model:
        raise CHMisconfigured(
            "variant=CH requires refiner_model (the teacher model id), got None."
        )
    key = (
        os.getenv("REFINER_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("PI_API_KEY")
    )
    if not key:
        raise CHMisconfigured(
            "variant=CH teacher has no resolvable API key. Set REFINER_API_KEY "
            "(or ANTHROPIC_API_KEY/OPENAI_API_KEY/PI_API_KEY)."
        )
    return {"model": refiner_model, "base_url": os.getenv("REFINER_BASE_URL"), "api_key": key}
```

- [ ] **Step 4: Invert the fallback in `nethack.py:251-262` to fail-loud**

Replace the `if variant == "CH" and self.refiner is None:` block with:

```python
        self.refiner = refiner
        self.refiner_model = refiner_model
        self._ch_real = False
        if variant == "CH" and self.refiner is None:
            from nethack_harness.refiner import (
                OfflineRefiner, TeacherLLMRefiner, resolve_teacher,
            )
            if kwargs.get("allow_offline_refiner"):
                # explicit test/control escape hatch — tagged not-a-real-CH-run
                self.refiner = OfflineRefiner()
            else:
                cfg = resolve_teacher(refiner_model)  # raises CHMisconfigured
                self.refiner = TeacherLLMRefiner(model=cfg["model"])
                self._ch_real = True
```

(Pop `allow_offline_refiner` from kwargs before `super().__init__` so verifiers does not choke on it.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_refiner.py::test_load_environment_ch_without_teacher_fails_loud -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add environments/nethack/nethack_harness/refiner.py environments/nethack/nethack.py tests/test_refiner.py
git commit -m "feat(ch): fail loud when CH variant has no resolvable teacher"
```

---

### Task 2: Keep an explicit offline escape hatch tagged not-a-real-CH-run

**Files:** `environments/nethack/nethack.py`, `tests/test_refiner.py`

- [ ] **Step 1: Failing test for the escape hatch + tag**

```python
def test_ch_offline_escape_hatch_is_tagged(monkeypatch):
    monkeypatch.delenv("REFINER_API_KEY", raising=False)
    import nethack
    from nethack_harness.refiner import OfflineRefiner
    env = nethack.NetHackVerifiersEnv(variant="CH", allow_offline_refiner=True)
    assert isinstance(env.refiner, OfflineRefiner)
    assert env._ch_real is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_refiner.py::test_ch_offline_escape_hatch_is_tagged -v`
Expected: FAIL until `allow_offline_refiner` kwarg is popped/handled.

- [ ] **Step 3: Handle the kwarg** (pop `allow_offline_refiner` in `__init__` before `super().__init__`; already referenced in Task 1 Step 4). Ensure `self._ch_real` stays `False` on this path.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_refiner.py::test_ch_offline_escape_hatch_is_tagged -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add environments/nethack/nethack.py tests/test_refiner.py
git commit -m "feat(ch): explicit offline escape hatch, tagged ch_real=false"
```

---

### Task 3: Teacher/policy separation guard at rollout time

**Files:** `environments/nethack/nethack.py` (`setup_state`, ~`:265`), `tests/test_refiner.py`

- [ ] **Step 1: Failing test** — when the policy model id (in state) equals the teacher model id, `setup_state` records refusal unless `allow_same_teacher`:

```python
@pytest.mark.asyncio
async def test_ch_same_teacher_as_policy_is_flagged(monkeypatch):
    monkeypatch.setenv("REFINER_API_KEY", "x")
    import nethack
    env = nethack.NetHackVerifiersEnv(variant="CH", refiner_model="glm-5")
    state = {"task": {}, "info": {}, "model": "glm-5"}  # policy == teacher
    state = await env.setup_state(state)
    assert state.get("ch_separation") == "refused-same-model"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_refiner.py::test_ch_same_teacher_as_policy_is_flagged -v`
Expected: FAIL.

- [ ] **Step 3: Implement the guard** in `setup_state` (after the existing task/info parsing), reading the policy id from `state.get("model")` (or the injected client) — set `state["ch_separation"]` to `"refused-same-model"` / `"separate"` / `"operator-asserted"` (when policy id unobservable), and raise `CHMisconfigured` on `refused-same-model` unless `self.kwargs.get("allow_same_teacher")`. Record the value in `state` for results/metadata either way.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_refiner.py::test_ch_same_teacher_as_policy_is_flagged -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add environments/nethack/nethack.py tests/test_refiner.py
git commit -m "feat(ch): teacher/policy separation guard at setup_state"
```

---

### Task 4: Write captured refiner edits into the trace

**Files:** `environments/nethack/nethack.py` (`_write_trace_entry` call at `:923`), `tests/test_refiner.py`

The hook already stamps `state["_ch_last_edits"] = edits.to_trace_dict()` (`prompt_spec.py:231`). Thread it into the trace record.

- [ ] **Step 1: Failing test** — a trace entry written on a refinement turn includes `ch_edits`:

```python
def test_trace_entry_includes_ch_edits(tmp_path):
    from nethack import _write_trace_entry  # adjust import to actual module path
    state = {"_ch_last_edits": {"prompt_addendum": "go downstairs", "notes_set": {}}}
    path = tmp_path / "trace.ndjson"
    _write_trace_entry(str(path), state=state, turn=20, record={"turn": 20})
    import json
    line = json.loads(path.read_text().strip().splitlines()[-1])
    assert line["ch_edits"]["prompt_addendum"] == "go downstairs"
```

(Match the real `_write_trace_entry` signature found at `nethack.py:923`; adjust args accordingly in the test.)

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_refiner.py::test_trace_entry_includes_ch_edits -v`
Expected: FAIL — `ch_edits` absent.

- [ ] **Step 3: Implement** — in `_write_trace_entry`, add `if state.get("_ch_last_edits"): record["ch_edits"] = state["_ch_last_edits"]` before serialization.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_refiner.py::test_trace_entry_includes_ch_edits -v`
Expected: PASS.

- [ ] **Step 5: Confirm `run_macro` exposure under CH** — extend/keep the existing macro-exposure assertion in `tests/test_refiner.py` (around `:198`) so it stays green.

- [ ] **Step 6: Commit**

```bash
git add environments/nethack/nethack.py tests/test_refiner.py
git commit -m "feat(ch): write per-interval refiner edits into the trace"
```

---

### Task 5: CH-vs-B1 launch config (teacher arg + 500-turn matched seeds)

**Files:** `experiments/exp16_obs_variants.py`

- [ ] **Step 1:** Add an explicit `teacher_model` field to the `CH` `Variant` (`exp16_obs_variants.py:218`) that maps to `load_environment(refiner_model=…)`, independent of the policy `-m`.

- [ ] **Step 2:** Add a CH-vs-B1 config: same seed set as B1, same policy model, `max_turns=500`, env-arg `refiner_model` set to the teacher (default `glm-5`). Default policy a weaker model (e.g. `Qwen/Qwen3.5-9B` or `glm-4.6`).

- [ ] **Step 3:** Ensure results aggregate through `tools/compare_evals.py` and that runs below a configured min seed count are labeled preliminary (string in the emitted summary).

- [ ] **Step 4: Commit**

```bash
git add experiments/exp16_obs_variants.py
git commit -m "feat(ch): exp16 CH-vs-B1 launch with explicit teacher_model + 500-turn config"
```

---

### Task 6: Verification + first local run

**Files:** none new (run + write-up)

- [ ] **Step 1:** Reinstall + full test suite:

Run:
```bash
uv sync --extra dev --all-packages --reinstall-package nethack --reinstall-package nethack-core
pytest tests/ -q
```
Expected: all green (including the inverted CH tests).

- [ ] **Step 2:** Local CH smoke — 1 seed, short horizon, real teacher key in shell:

Run:
```bash
REFINER_API_KEY=$YOUR_TEACHER_KEY \
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 1 -r 1 \
  -a '{"variant":"CH","refiner_model":"glm-5","tier":"corridor_explore","max_turns":60,"trace_dir":"environments/nethack/outputs/evals/ch_smoke"}'
```
Expected: completes; the trace under `ch_smoke` contains `ch_edits` records on refinement turns (confirm the teacher fired).

- [ ] **Step 3:** Local real CH-vs-B1 run (≥500 turns, planned seeds) via exp16; aggregate with `compare_evals`; record the first CH number and edit-capture evidence in `experiment_log.md`.

- [ ] **Step 4: Commit**

```bash
git add experiment_log.md
git commit -m "docs(ch): first real CH-vs-B1 result + edit-capture evidence"
```

---

## Self-Review

- **Spec coverage:** teacher-separation → Task 3 (+ operator-asserted metadata); credentials-fail-loud → Task 1; offline-not-real-CH tag → Task 2; refinement-fires/edits-captured → Task 4; run_macro under CH → Task 4 Step 5; powered CH-vs-B1 → Task 5 + Task 6. All four spec requirements have tasks.
- **Placeholders:** none — every code step shows code; the one signature to confirm at execution time is the real `_write_trace_entry` arg list (`nethack.py:923`), flagged inline.
- **Type consistency:** `CHMisconfigured`, `resolve_teacher`, `_ch_real`, `ch_separation`, `ch_edits`, `allow_offline_refiner`, `allow_same_teacher` used consistently across tasks.
