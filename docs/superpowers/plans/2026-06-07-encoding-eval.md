---
change: encoding-eval
design-doc: docs/superpowers/specs/2026-06-07-encoding-eval-design.md
base-ref: 64d086551a75c4300323103f2e47603450cf0a5e
archived-with: 2026-06-07-encoding-eval
---

# Encoding-eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A benchmark harness comparing observation encodings across models, reusing existing eval instrumentation, with rollouts replayable in human-viewable and exact-LLM-input forms.

**Architecture:** A pure aggregation layer (`tools/encoding_eval/aggregate.py`) turns rollout samples into a per-encoding table via `tools.eval_instrument` + `balrog`. An orchestration layer (`tools/encoding_eval/run.py`) drives the `(encoding,model)` matrix through the existing eval runner via an injectable seam. Replay capture extends the per-turn NDJSON trace with full multimodal content (images → PNG files); a minimal renderer (`tools/encoding_eval/replay.py`) shows both forms behind a seam the Group B viewer will reuse.

**Tech Stack:** Python, pytest. Reuses `tools/eval_instrument.py`, `nethack_harness/prompt/balrog.py`, `legacy/replay.py`.

archived-with: 2026-06-07-encoding-eval
---

## Environment & test invocation (read first)

- On the build-isolation branch off `main`. `tools/` is repo-root (importable as `tools.*` — `tools/eval_instrument.py` is imported as `from tools.eval_instrument import ...`).
- **Test command** (cwd `environments/nethack`):
  ```bash
  cd environments/nethack
  python -m pytest ../../tests/<file> -p no:cacheprovider -q --no-header
  ```
  New tests go in repo-root `tests/`.
- **Known baseline:** 7 pre-existing failures (`test_integration`→`test_rewards` ordering pollution). Do NOT fix; new tests pass in isolation; full-suite failures stay ⊆ those 7.
- **Commit path-scoped** (`git add -- <paths>`).

## Grounded facts

- `tools/eval_instrument.py`: `summarize_eval(samples) -> {n, descent_rate, ci_lo, ci_hi, avg_score, failure_taxonomy, per_seed}`; `wilson_ci(k,n)`; `classify_failure(rollout)`; `load_hosted_eval_samples(path)`; `attach_local_traces(samples, trace_dir)`. A `sample` is `{reward, scout_reward, descent_reward, seed/example_id, trace?:[{rendered_user_message, raw_grid, status, ...}]}`.
- `nethack_harness/prompt/balrog.py`: `progression_score(max_dlvl, xp_level)`, `progression_tier(score)`.
- `_write_trace_entry(env_self, state, assistant_msg, tool_calls, action_indices, total_reward, obs_text)` in `nethack_harness/helpers.py` writes the NDJSON entry (already has `raw_grid`, `status`, `rendered_user_message`, `turn`, `variant`). Called once in `nethack.py` env_response main path as `_write_trace_entry(self, state, assistant_msg, tool_calls, action_indices, total_reward, content_to_text(content))`.
- `content` at that call site is `str | list` (the multimodal content from `compose_user_content`); image content is `[{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}, {"type":"text","text":...}]`.
- `legacy/replay.py`: `TrajectoryRecorder` (captures rendered tty frames), `Trajectory` (json-serializable).
- `configs/eval/*.toml`: `model`, `num_examples`, `rollouts_per_example`, `max_tokens`, `[[eval]] env_id`.

## File structure

- Create: `tools/encoding_eval/__init__.py`, `aggregate.py`, `run.py`, `replay.py`
- Modify: `environments/nethack/nethack_harness/helpers.py` (`_write_trace_entry` — add `rendered_user_content` + image capture), `environments/nethack/nethack.py` (pass full `content` to the trace writer)
- Create: `environments/nethack/configs/eval/qwen-3-5-vl.toml`
- Tests: `tests/test_encoding_eval_aggregate.py`, `tests/test_encoding_eval_run.py`, `tests/test_replay_capture.py`, `tests/test_encoding_eval_replay.py`

archived-with: 2026-06-07-encoding-eval
---

## Task 1: Aggregation layer (pure)

**Files:**
- Create: `tools/encoding_eval/__init__.py` (empty), `tools/encoding_eval/aggregate.py`
- Test: `tests/test_encoding_eval_aggregate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_encoding_eval_aggregate.py
from __future__ import annotations

from tools.encoding_eval.aggregate import aggregate_cells


def _sample(*, reward, descended, max_dlvl, xp, tokens_per_turn=None):
    trace = [{"rendered_user_message": "MAP", "status": {"depth": max_dlvl, "experience_level": xp}}]
    s = {"reward": reward, "scout_reward": 0.0, "descent_reward": 1.0 if descended else 0.0,
         "seed": 1, "trace": trace, "max_dlvl": max_dlvl, "xp_level": xp}
    if tokens_per_turn is not None:
        s["tokens_per_turn"] = tokens_per_turn
    return s


def test_table_has_one_row_per_encoding():
    cells = {
        "B1": [_sample(reward=1, descended=True, max_dlvl=2, xp=3, tokens_per_turn=500)],
        "JSON": [_sample(reward=0, descended=False, max_dlvl=1, xp=1, tokens_per_turn=1200)],
    }
    table = aggregate_cells(cells)
    assert set(table["rows"]) == {"B1", "JSON"}
    b1 = table["rows"]["B1"]
    # reuses summarize_eval + progression
    assert b1["descent_rate"] == 1.0
    assert "ci_lo" in b1 and "ci_hi" in b1
    assert b1["max_dlvl"] == 2
    assert b1["progression_tier"]  # non-empty
    assert b1["tokens_per_turn"] == 500


def test_missing_usage_marks_cost_unavailable():
    cells = {"IMG": [_sample(reward=0, descended=False, max_dlvl=1, xp=1)]}  # no tokens
    table = aggregate_cells(cells)
    assert table["rows"]["IMG"]["dollars_per_run"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_encoding_eval_aggregate.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ModuleNotFoundError: tools.encoding_eval.aggregate`.

- [ ] **Step 3: Write minimal implementation**

```python
# tools/encoding_eval/aggregate.py
"""Pure aggregation: rollout samples per encoding -> comparison table.

Reuses tools.eval_instrument.summarize_eval and nethack_harness.prompt.balrog
progression metrics. No model calls — fully unit-testable on synthetic samples.
"""
from __future__ import annotations

from typing import Any


def _max_dlvl(sample: dict) -> int:
    if sample.get("max_dlvl") is not None:
        return int(sample["max_dlvl"])
    best = 0
    for e in sample.get("trace") or []:
        d = (e.get("status") or {}).get("depth")
        if d is not None:
            best = max(best, int(d))
    return best


def _xp(sample: dict) -> int:
    if sample.get("xp_level") is not None:
        return int(sample["xp_level"])
    best = 0
    for e in sample.get("trace") or []:
        x = (e.get("status") or {}).get("experience_level")
        if x is not None:
            best = max(best, int(x))
    return best


def aggregate_cells(cells: dict[str, list[dict]]) -> dict[str, Any]:
    from tools.eval_instrument import summarize_eval
    from nethack_harness.prompt.balrog import progression_score, progression_tier

    rows: dict[str, Any] = {}
    for enc, samples in cells.items():
        summ = summarize_eval(samples)
        max_dlvl = max((_max_dlvl(s) for s in samples), default=0)
        xp = max((_xp(s) for s in samples), default=0)
        score = progression_score(max_dlvl, xp)
        tokens = [s["tokens_per_turn"] for s in samples if s.get("tokens_per_turn") is not None]
        tokens_per_turn = (sum(tokens) / len(tokens)) if tokens else None
        costs = [s["dollars"] for s in samples if s.get("dollars") is not None]
        rows[enc] = {
            "n": summ["n"],
            "descent_rate": summ["descent_rate"],
            "ci_lo": summ["ci_lo"],
            "ci_hi": summ["ci_hi"],
            "avg_score": summ["avg_score"],
            "failure_taxonomy": summ["failure_taxonomy"],
            "max_dlvl": max_dlvl,
            "progression_score": score,
            "progression_tier": progression_tier(score),
            "tokens_per_turn": tokens_per_turn,
            "dollars_per_run": (sum(costs) / len(costs)) if costs else None,
        }
    return {"rows": rows}


def table_to_markdown(table: dict) -> str:
    cols = ["n", "descent_rate", "progression_tier", "max_dlvl", "tokens_per_turn", "dollars_per_run"]
    lines = ["| encoding | " + " | ".join(cols) + " |",
             "|---|" + "|".join("---" for _ in cols) + "|"]
    for enc, r in table["rows"].items():
        cells = [("n/a" if r[c] is None else r[c]) for c in cols]
        lines.append(f"| {enc} | " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_encoding_eval_aggregate.py -p no:cacheprovider -q --no-header
```
Expected: PASS (2 passed). If `progression_score`/`progression_tier` signatures differ, read `nethack_harness/prompt/balrog.py` and adapt the call — do not change the test's intent.

- [ ] **Step 5: Commit**

```bash
git add -- tools/encoding_eval/__init__.py tools/encoding_eval/aggregate.py tests/test_encoding_eval_aggregate.py
git commit -m "feat(encoding-eval): pure aggregation layer reusing eval_instrument + balrog"
```

archived-with: 2026-06-07-encoding-eval
---

## Task 2: Replay capture (trace extension + image PNGs)

**Files:**
- Modify: `environments/nethack/nethack_harness/helpers.py` (`_write_trace_entry`)
- Modify: `environments/nethack/nethack.py` (pass full content to the trace writer)
- Test: `tests/test_replay_capture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_capture.py
from __future__ import annotations

import json
from pathlib import Path

from nethack_harness.helpers import _capture_user_content


def test_text_content_passthrough(tmp_path):
    out = _capture_user_content("OBS TEXT", tmp_path, run_id="r", turn=3)
    assert out == "OBS TEXT"  # string content stored as-is


def test_image_content_written_as_png_and_referenced(tmp_path):
    import base64
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE").decode()
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
        {"type": "text", "text": "STATUS"},
    ]
    out = _capture_user_content(content, tmp_path, run_id="r", turn=3)
    # image entry replaced with a relative path; no base64 inline
    img_entry = next(e for e in out if e["type"] == "image_url")
    ref = img_entry["image_url"]["path"]
    assert "base64" not in json.dumps(out)
    assert (tmp_path / ref).exists()
    assert next(e for e in out if e["type"] == "text")["text"] == "STATUS"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_replay_capture.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ImportError: cannot import name '_capture_user_content'`.

- [ ] **Step 3: Write minimal implementation**

Add `_capture_user_content` to `helpers.py` (above `_write_trace_entry`):

```python
def _capture_user_content(content, out_dir, *, run_id: str, turn: int):
    """Return a trace-safe copy of the per-turn user content.

    Strings pass through. For a multimodal list, each image_url data URI is
    decoded and written to ``<out_dir>/images/<run_id>_<turn>.png`` and the entry
    is rewritten to reference the relative path instead of the inline base64, so
    the exact image the model saw is replayable without bloating the NDJSON.
    """
    if isinstance(content, str):
        return content
    import base64 as _b64
    images_dir = Path(out_dir) / "images"
    out = []
    idx = 0
    for entry in content:
        if entry.get("type") == "image_url":
            url = (entry.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and "base64," in url:
                images_dir.mkdir(parents=True, exist_ok=True)
                b64 = url.split("base64,", 1)[1]
                fname = f"{run_id}_{turn}_{idx}.png"
                (images_dir / fname).write_bytes(_b64.b64decode(b64))
                out.append({"type": "image_url", "image_url": {"path": f"images/{fname}"}})
                idx += 1
            else:
                out.append(entry)
        else:
            out.append(entry)
    return out
```

In `_write_trace_entry`, change the signature to also accept the full content and store it. Replace the signature line and add the field:

```python
def _write_trace_entry(env_self, state, assistant_msg, tool_calls,
                       action_indices, total_reward, obs_text, obs_content=None):
```
and in the `entry` dict, after `"rendered_user_message": obs_text,` add:
```python
            "rendered_user_content": _capture_user_content(
                obs_content if obs_content is not None else obs_text,
                out_dir, run_id=run_id, turn=state.get("turn_count", 0)),
```

In `nethack.py`, change the trace call at the env_response main path to pass the full content:
```python
        _write_trace_entry(
            self, state, assistant_msg, tool_calls,
            action_indices, total_reward, content_to_text(content), obs_content=content,
        )
```
(Read the current call site first; `content` is the `str|list` already computed by `compose_user_content`.)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_replay_capture.py -p no:cacheprovider -q --no-header
python -m py_compile nethack.py && echo OK
# trace writer still works for text rollouts:
python -m pytest ../../tests/test_integration.py -p no:cacheprovider -q --no-header
```
Expected: capture tests PASS; py_compile OK; test_integration green except the known baseline `test_success_reward_zero_then_one`.

- [ ] **Step 5: Commit**

```bash
git add -- environments/nethack/nethack_harness/helpers.py environments/nethack/nethack.py tests/test_replay_capture.py
git commit -m "feat(encoding-eval): capture full multimodal content + image PNGs in the trace"
```

archived-with: 2026-06-07-encoding-eval
---

## Task 3: Minimal replay renderer + integration seam

**Files:**
- Create: `tools/encoding_eval/replay.py`
- Test: `tests/test_encoding_eval_replay.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_encoding_eval_replay.py
from __future__ import annotations

import json
from pathlib import Path

from tools.encoding_eval.replay import render_replay, REPLAY_LOG_KEYS


def _write_trace(run_dir: Path):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "r.ndjson").write_text("\n".join(json.dumps(e) for e in [
        {"turn": 0, "raw_grid": ["@.."], "rendered_user_message": "MAP txt",
         "rendered_user_content": "MAP txt"},
        {"turn": 1, "raw_grid": ["..>"], "rendered_user_message": "STATUS",
         "rendered_user_content": [{"type": "image_url", "image_url": {"path": "images/r_1_0.png"}},
                                   {"type": "text", "text": "STATUS"}]},
    ]))


def test_human_form_shows_game_state(tmp_path):
    _write_trace(tmp_path)
    out = render_replay(tmp_path, form="human")
    assert "@.." in out and "..>" in out  # tty frames present


def test_llm_form_shows_text_and_image_ref(tmp_path):
    _write_trace(tmp_path)
    out = render_replay(tmp_path, form="llm")
    assert "MAP txt" in out          # text encoding turn
    assert "images/r_1_0.png" in out  # image preserved (as a reference) for the pixel turn
    assert "STATUS" in out


def test_seam_documents_log_keys():
    # The stable seam Group B's viewer relies on.
    assert {"rendered_user_content", "raw_grid"} <= set(REPLAY_LOG_KEYS)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_encoding_eval_replay.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ModuleNotFoundError: tools.encoding_eval.replay`.

- [ ] **Step 3: Write minimal implementation**

```python
# tools/encoding_eval/replay.py
"""Minimal replay renderer + the documented log seam for Group B's viewer.

A recorded run dir contains per-turn NDJSON trace files (keys below) and an
images/ dir. ``render_replay`` produces a plain-text rendering in either the
human-viewable game-state form or the exact LLM-input form. The rich viewer
(Group B / tools/launchpad) reads the same format via this entry point.
"""
from __future__ import annotations

import json
from pathlib import Path

# The stable on-disk seam: keys a viewer can rely on per trace entry.
REPLAY_LOG_KEYS = ("turn", "raw_grid", "rendered_user_message", "rendered_user_content")


def _load_turns(run_dir: Path):
    turns = []
    for f in sorted(Path(run_dir).glob("*.ndjson")):
        for line in f.read_text().splitlines():
            if line.strip():
                turns.append(json.loads(line))
    return turns


def _content_to_lines(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    out = []
    for e in content:
        if e.get("type") == "image_url":
            ref = (e.get("image_url") or {}).get("path") or (e.get("image_url") or {}).get("url", "")
            out.append(f"[image: {ref}]")
        elif e.get("type") == "text":
            out.append(e.get("text", ""))
    return out


def render_replay(run_dir, *, form: str = "human") -> str:
    turns = _load_turns(run_dir)
    blocks = []
    for t in turns:
        head = f"=== turn {t.get('turn')} ==="
        if form == "human":
            body = "\n".join(t.get("raw_grid") or [])
        elif form == "llm":
            body = "\n".join(_content_to_lines(
                t.get("rendered_user_content", t.get("rendered_user_message", ""))))
        else:
            raise ValueError(f"unknown form: {form!r} (expected 'human' or 'llm')")
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_encoding_eval_replay.py -p no:cacheprovider -q --no-header
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add -- tools/encoding_eval/replay.py tests/test_encoding_eval_replay.py
git commit -m "feat(encoding-eval): minimal dual-form replay renderer + Group B seam"
```

archived-with: 2026-06-07-encoding-eval
---

## Task 4: Matrix orchestration (injectable runner seam)

**Files:**
- Create: `tools/encoding_eval/run.py`
- Test: `tests/test_encoding_eval_run.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_encoding_eval_run.py
from __future__ import annotations

from tools.encoding_eval.run import run_matrix


def test_dispatches_each_cell_with_variant_and_detail():
    calls = []

    def stub_runner(cell):
        calls.append(cell)
        # return a couple of fake samples for this cell
        return [{"reward": 1.0, "descent_reward": 1.0, "seed": 1, "trace": []}]

    matrix = {
        "encodings": [{"variant": "B1"}, {"variant": "JSON", "map_detail": "minimal"}],
        "models": ["qwen-instruct"],
    }
    table = run_matrix(matrix, runner=stub_runner)
    # one cell per (encoding, model)
    variants = sorted(c["variant"] for c in calls)
    assert variants == ["B1", "JSON"]
    assert any(c.get("map_detail") == "minimal" for c in calls)
    assert set(table["rows"]) == {"B1", "JSON:minimal"}  # cell keys distinguish detail
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_encoding_eval_run.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ModuleNotFoundError: tools.encoding_eval.run`.

- [ ] **Step 3: Write minimal implementation**

```python
# tools/encoding_eval/run.py
"""Matrix orchestration over (encoding, model) cells.

The default runner shells out to the existing vf-eval/prime eval runner with a
per-cell config and loads samples via tools.eval_instrument. Tests inject a stub
runner, so this module is exercisable without model calls. The matrix (encodings
x models) is config data.
"""
from __future__ import annotations

from typing import Any, Callable

from tools.encoding_eval.aggregate import aggregate_cells


def _cell_key(enc: dict) -> str:
    v = enc["variant"]
    return f"{v}:{enc['map_detail']}" if enc.get("map_detail") else v


def _default_runner(cell: dict) -> list[dict]:
    # Render a per-cell eval config + invoke the existing runner + load samples.
    # Kept thin; real wiring uses tools.eval_instrument.load_hosted_eval_samples /
    # attach_local_traces. Raises if invoked without configuration (real runs are
    # an operational step) so CI always injects a stub.
    raise NotImplementedError(
        "default runner needs eval config + model access; inject a runner for tests")


def run_matrix(matrix: dict, *, runner: Callable[[dict], list[dict]] = _default_runner) -> dict[str, Any]:
    cells: dict[str, list[dict]] = {}
    for enc in matrix["encodings"]:
        for model in matrix["models"]:
            cell = {**enc, "model": model}
            samples = runner(cell)
            cells[_cell_key(enc)] = samples
    return aggregate_cells(cells)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_encoding_eval_run.py -p no:cacheprovider -q --no-header
```
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add -- tools/encoding_eval/run.py tests/test_encoding_eval_run.py
git commit -m "feat(encoding-eval): matrix orchestration with injectable runner seam"
```

archived-with: 2026-06-07-encoding-eval
---

## Task 5: VLM config + verification + tasks.md

**Files:**
- Create: `environments/nethack/configs/eval/qwen-3-5-vl.toml`
- Modify: `openspec/changes/encoding-eval/tasks.md`

- [ ] **Step 1: Create the VLM config**

```toml
# environments/nethack/configs/eval/qwen-3-5-vl.toml
# Qwen3.5-VL — vision-language model, for the IMG / IMG_TTY encodings.
model = "Qwen/Qwen3.5-VL-7B"

num_examples = 20
rollouts_per_example = 1
max_tokens = 1024

[[eval]]
env_id = "nethack"
# variant / map_detail are supplied per-cell by the encoding-eval orchestrator.
```

- [ ] **Step 2: Run new tests in isolation**

```bash
cd environments/nethack
python -m pytest ../../tests/test_encoding_eval_aggregate.py ../../tests/test_replay_capture.py ../../tests/test_encoding_eval_replay.py ../../tests/test_encoding_eval_run.py -p no:cacheprovider -q --no-header
```
Expected: all PASS.

- [ ] **Step 3: Full suite (failure set ⊆ baseline 7)**

```bash
cd environments/nethack
python -m pytest ../../tests -p no:cacheprovider -q --no-header 2>&1 | tail -12
```
Expected: only the 7 known baseline failures; passed count up by the new tests.

- [ ] **Step 4: Document running a real benchmark** — add a short docstring/README note in `tools/encoding_eval/run.py` (or `tools/encoding_eval/README.md`) describing the operational follow-up: supply a real `runner` (vf-eval/prime + model configs incl. the VLM), set `trace_dir` to `outputs/evals/<run>/`, then `render_replay(run_dir, form=...)` and read `table.json`/`table.md`.

- [ ] **Step 5: Check off `openspec/changes/encoding-eval/tasks.md`** and commit.

```bash
git add -- environments/nethack/configs/eval/qwen-3-5-vl.toml tools/encoding_eval/run.py openspec/changes/encoding-eval/tasks.md
git commit -m "feat(encoding-eval): VLM config + operational run note; mark tasks complete"
```

archived-with: 2026-06-07-encoding-eval
---

## Self-review notes

- **Spec coverage:** Task 1 → metrics-reuse + mock-testable aggregation + missing-usage-marked. Task 2 → full-multimodal capture (image not elided). Task 3 → replay both forms + viewer seam (REPLAY_LOG_KEYS). Task 4 → matrix harness (configurable encoding set, dispatched per variant/detail). Task 5 → VLM config + comparison-table emission (`table_to_markdown` from Task 1; JSON via the table dict). The comparison-table-emitted scenario is satisfied by writing `aggregate_cells` output (JSON) + `table_to_markdown` (md) under `outputs/evals/` — wire this in the orchestrator's real path / run note.
- **Type consistency:** `aggregate_cells(cells) -> {"rows": {...}}`, `table_to_markdown(table)`, `run_matrix(matrix, runner)`, `render_replay(run_dir, form)`, `_capture_user_content(content, out_dir, run_id, turn)`, `REPLAY_LOG_KEYS` — consistent across tasks.
- **Out of scope:** real paid benchmark run; rich Group B viewer.
