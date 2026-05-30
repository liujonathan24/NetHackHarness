# NetHack Launchpad — Spec

## Context

The repo already has `tools/eval_dashboard.html`, `tools/replay_viewer.html`, and a constellation of CLI scripts (`exp16_obs_variants.py`, `compare_evals.py`, `eval_instrument.py`). They each do one thing well but you have to context-switch across terminal + editor + browser to: launch a run → tweak a reward → look at why an LLM died on turn 47.

Launchpad bundles those flows into one local SPA. It is a **thin orchestrator** over the existing CLIs and trace files — no new persistence, no new schemas. Everything it shows is already on disk under `experiments/results/` or in `environments/nethack/`.

## Three workflows (one app)

| Pane | Backed by | What it does |
|---|---|---|
| **Launch** | `prime eval` / `exp16_obs_variants.py` | Pick model, variant, tier, seeds → POST to backend → tail logs. |
| **Edit** | Files in `environments/nethack/` and `nethack_core/` | Browse + edit `SYSTEM_PROMPT`, reward functions, configs; diff vs git HEAD; "save & relaunch". |
| **Traces** | NDJSON in `state["env"].trace_dir` | Pick run → scrub timeline → flip between Observer and LLM views. |

## Backend (FastAPI, ~200 LOC)

```
GET  /api/runs                          # list metadata.json across results/
GET  /api/runs/{run_id}                 # one run's metadata + rollout index
GET  /api/runs/{run_id}/trace/{idx}     # NDJSON for one rollout, parsed
GET  /api/files?path=...                # read file (whitelisted dirs)
PUT  /api/files                         # write file (creates git stash backup)
GET  /api/git/diff?path=...             # diff vs HEAD
POST /api/launch                        # spawn `prime eval ...` as subprocess, return task_id
GET  /api/launch/{task_id}/log          # SSE stream of stdout
GET  /api/configs                       # list TOMLs in environments/nethack/configs/
```

Whitelist for `/api/files`: `environments/nethack/**`, `nethack_core/**`, `experiments/*.py`.

## Trace data model (already exists — do not change)

From `environments/nethack/nethack.py:1907–1980`, each line of the NDJSON:

```json
{
  "turn": 47,
  "t_wall": 1748621234.5,
  "variant": "B1",
  "raw_grid": ["....", "..@.", "...."],
  "status": {"hp": 12, "max_hp": 18, "dlvl": 2, "ac": 8, "hunger": "Hungry", "gold": 47},
  "dlvl": 2, "hp": 12, "max_hp": 18,
  "rendered_user_message": "...full text sent to LLM...",
  "assistant_message": "I should head for the stairs...",
  "tool_calls": [{"name": "move", "arguments": {"direction": "south"}}],
  "action_indices": [3],
  "reward": {"scout": 0.012, "descent": 0.0, "success": 0.0, "ascension": 0.0}
}
```

**Observer view** uses `raw_grid` + `status`. **LLM view** uses `rendered_user_message` + `assistant_message` + `tool_calls`. Same data, two presentations.

## UI structure

```
┌──────────────────────────────────────────────────────────────────────┐
│ Launchpad   [Launch] [Edit] [Traces]                  model: gpt-4.1 │
├────────────┬─────────────────────────────────────────────────────────┤
│ left rail  │   center pane (tab-dependent)                           │
│            │                                                         │
│ recent     │   Launch: form  + live log tail                         │
│ runs +     │   Edit:   file tree → editor + diff                     │
│ branches   │   Traces: rollout picker → scrubber + dual view         │
│            │                                                         │
└────────────┴─────────────────────────────────────────────────────────┘
```

### Traces pane (the most novel piece)

```
[run: wave2/E1_seed22]   rollout 3/16   turn ◄ [====●═══════] ► 47/210
┌─────────── Observer ───────────┬─────────── LLM view ───────────────┐
│  HP 12/18  AC 8  Dlvl 2  $47   │  > system: You are playing...      │
│  ┌────────────────────────────┐│  > user (turn 47):                  │
│  │ -------                    ││    HP 12/18  Hungry                 │
│  │ |....|                     ││    ADJACENT: kobold(N), door(W)     │
│  │ |.@..|                     ││    VISIBLE: > at (12,8)             │
│  │ |...d|                     ││    [map snippet]                    │
│  │ ------                     ││  > assistant: "Kobold is N. I'll    │
│  └────────────────────────────┘│     attack."                        │
│                                │  > tool_call: attack(direction=N)   │
│  reward Δ: scout +0.012        │  reward returned: +0.0              │
└────────────────────────────────┴─────────────────────────────────────┘
```

Keyboard: ←/→ step turn, ⇧←/⇧→ jump 10, `j`/`k` next/prev rollout, `o`/`l` swap pane focus.

## Sample specs (concrete)

### A `LaunchSpec` (POST `/api/launch`)
```json
{
  "label": "B1_descent_smoke",
  "model": "gpt-4.1-mini",
  "env_args": {"tier": "descend_to_dlvl_3", "variant": "B1", "max_turns": 200},
  "num_examples": 4,
  "rollouts_per_example": 2,
  "tags": ["wave3", "smoke"]
}
```

### A `RunSummary` (returned by `/api/runs`)
```json
{
  "run_id": "wave2/E1_seed22_eeu2691bgjl3ylud28yzswlj",
  "label": "E1 seed22",
  "model": "gpt-4.1-mini",
  "variant": "E1",
  "num_rollouts": 16,
  "avg_reward": {"scout": 0.34, "descent": 1.2, "success": 0.0, "ascension": 0.0},
  "avg_turns": 87,
  "created": "2026-05-28T14:22:11Z",
  "git_sha": "5e82bca",
  "trace_dir": "experiments/results/wave2/traces/E1_seed22/"
}
```

## Verification

- `pytest tests/ -q` still passes (no changes to env code).
- `uvicorn tools.launchpad.server:app --reload` boots; visiting `/` serves the SPA.
- Launch a smoke eval from the UI, confirm a metadata.json appears under `experiments/results/`.
- Open a trace, step turns, confirm Observer grid matches the saved `raw_grid` exactly (no re-rendering).

## Out of scope (v1)

- Multi-user / auth — single-user local app.
- Editing while a run is in flight (warn but don't lock).
- RL training loop integration — that's a v2; today's "Launch" is eval-only.
