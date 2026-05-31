# NetHack Launchpad — Spec (v3, CLI / TUI)

## Context

The repo has `tools/eval_dashboard.html`, `tools/replay_viewer.html`, and a constellation of CLIs (`exp16_obs_variants.py`, `compare_evals.py`, `eval_instrument.py`, `prime eval`, `prime gepa`, `prime rl`). Each does one thing well but you context-switch across terminal + editor + browser to: launch a run → tweak a reward → swap a tool → look at why an LLM died on turn 47 → kick off training.

Launchpad bundles those flows into one **command-line tool**. No desktop app, no browser, no window. Either a subcommand (`launchpad eval ...`) or — when run with no args / a "viewer" subcommand — a **Textual TUI** in the same terminal you're already in.

This is the right shape because:
- NetHack is ASCII-native. The Observer view is the *literal* game grid. Rendering it in a terminal is more faithful, not less.
- Researchers live in `ssh` + tmux + `vim`/`cursor`. A TUI runs over SSH; a GUI doesn't.
- No notarization, no auto-updater, no .dmg. Ships as a single Python package.
- Editing code/prompts already has a perfect tool: `$EDITOR`. Launchpad shells out to it instead of building a worse one.

## Two surfaces, one tool

### Surface A — non-interactive subcommands
For scripts, CI, and quick one-shots. Print to stdout, exit. Output is `--json` friendly.

```sh
launchpad eval --model gpt-4.1-mini --harness descend_aggressive \
               --tier descend_to_dlvl_3 -n 4 -r 2 --tag wave3,smoke
launchpad eval --local                       # vf-eval instead of prime eval
launchpad eval --watch                       # launch + auto-attach TUI to it

launchpad train rl   --base Qwen/Qwen2.5-7B --harness descend_aggressive \
                     --tier descend_to_dlvl_3 --hparams hp.toml
launchpad train gepa --harness default --target system_prompt \
                     --reward descent --generations 6

launchpad runs ls [--kind eval|train] [--tag wave3] [--limit 20]
launchpad runs show <run_id> [--json]
launchpad runs compare <run_a> <run_b> [--metric scout|descent|success]

launchpad trace <run_id> [--rollout N] [--turn T]   # opens TUI viewer
launchpad trace --latest                            # most recent run
launchpad trace --live                              # most recent running

launchpad harness ls
launchpad harness new <name> [--extends default]
launchpad harness edit <name>                       # $EDITOR opens the TOML
launchpad harness diff <name>                       # vs default
launchpad harness preview <name> [--state sample.json]   # what LLM sees turn 0
launchpad harness validate <name>

launchpad export <run_id> --out demo.mp4            # → tools/render_rollout_video.py
launchpad stop <task_id>
launchpad tail <task_id>                            # raw log stream
```

### Surface B — interactive TUI (Textual)
`launchpad` with no args opens the TUI. Same data, but a navigable layout with panes, scrubber, live attach. Four screens (cycled with `1`/`2`/`3`/`4`):

```
┌─ 1.LAUNCH ─ 2.TRAIN ─ 3.HARNESS ─ 4.TRACES ───────── q:quit  ?:help ─┐
│                                                                       │
│  (pane content per screen — see ASCII below)                          │
│                                                                       │
├───────────────────────────────────────────────────────────────────────┤
│  branch wave2-frontier · sha 3b6c2f9 · 1 task running ●               │
└───────────────────────────────────────────────────────────────────────┘
```

## Why Textual (and not pygame / GUI)

**Hard requirement: must work natively over SSH.** Most training runs live on a remote box; the viewer has to attach from a laptop without X11 forwarding, VNC, or any GUI plumbing. That rules out pygame, PyQt, Tk, Tauri, and anything else that needs a window server.

Textual:
- Renders ANSI to a normal terminal. `ssh box -t launchpad trace --latest` is the smoke test, and it just works.
- Python — same `uv` workspace as the rest of the repo.
- Real panes, mouse support (over SSH if the client supports it), scrolling, keybindings, focus.
- Async (`asyncio`), so `watchfiles` + subprocess streaming compose cleanly.
- `textual run --dev` for hot-reload.

The cost: no pixel art, no sprites, no smooth tweening. For NetHack that doesn't matter — the game is literally ASCII. The Observer view *is* the game's native representation.

## Screen mockups (ASCII, because that's what you'll actually see)

### Screen 4: TRACES (the marquee feature)

```
┌─ 4.TRACES ───────────────────── run: wave2/E2_seed27 · rollout 3/16 ─┐
│ runs ▾              │ ─◀ ──────────●─────────── ▶─  step 4/5  t:57   │
│ ● E2 seed27 LIVE    │ ┌──── Observer ────────┬──── LLM view ───────┐ │
│   E2 seed11 .7 ✓    │ │ HP 13/18 AC 8 Dlvl 3 │ system:             │ │
│   E2 seed14 ✗ t41   │ │ $47   hunger:Not-hgy │  You are playing... │ │
│   E1 seed22 .34 ✓   │ │                      │                     │ │
│   N  seed24 .22 ✓   │ │      ----------      │ user (turn 57):     │ │
│                     │ │      |........|      │  HP 13/18  Dlvl 3   │ │
│ harness ▾           │ │      |...@....|      │  ADJACENT: floor    │ │
│ ● default           │ │      |........|      │  VISIBLE: > at ...  │ │
│   descend_aggr      │ │      |.f......|      │  [map snippet]      │ │
│   journal_heavy     │ │      ----+-----      │                     │ │
│                     │ │          #           │ assistant:          │ │
│                     │ │     ------+----      │  New level. Kitten  │ │
│                     │ │     |....<....|      │  follows. Explore   │ │
│                     │ │     -----------      │  east toward >.     │ │
│                     │ │                      │                     │ │
│                     │ │ reward: scout +0.180 │ tool_call:          │ │
│                     │ │         descent+1.000│  autoexplore()      │ │
│                     │ └──────────────────────┴─────────────────────┘ │
├──────────────────────────────────────────────────────────────────────┤
│ ← → step · ⇧← ⇧→ jump 10 · j k rollout · f follow · g goto-turn      │
└──────────────────────────────────────────────────────────────────────┘
```

Live mode just adds a pulsing `LIVE` pill in the header and follows the latest turn by default. `f` toggles follow off so you can scrub backward without the UI yanking you forward.

### Screen 1: LAUNCH

```
┌─ 1.LAUNCH ────────────────────────────────────────────────────────────┐
│  Label:   wave3_E2_descend_smoke                                      │
│  Model:   [gpt-4.1-mini ▾]      Harness: [descend_aggressive ▾]       │
│  Tier:    [descend_to_dlvl_3 ▾]  Max turns: 200                       │
│  N ex:    4    Rollouts/ex: 2    Tags: wave3,smoke                    │
│                                                                       │
│  [ Launch ]  [ Launch & watch ]  [ Dry run ]  [ Save as TOML ]        │
│                                                                       │
│  ─── recent ──────────────────────────────────────────────────────────│
│  ● wave3_E2_descend_smoke   running   2/8 done   t=00:03:12           │
│    wave2/E2_seed27          done      scout 0.41  desc 1.6  t=94      │
│    wave2/E1_seed22          done      scout 0.34  desc 1.2  t=87      │
└───────────────────────────────────────────────────────────────────────┘
```

### Screen 2: TRAIN

```
┌─ 2.TRAIN ─────────────────────────────────────────────── mode: [RL] ──┐
│  [ RL (prime rl) ] [ GEPA (prime gepa) ]                              │
│                                                                       │
│  Base model:   Qwen/Qwen2.5-7B          Harness: descend_aggressive   │
│  Tiers:        corridor_explore, descend_to_dlvl_3                    │
│  lr 1e-6  kl 0.04  group 8  rollouts/ex 4  max-turns 200  batch 64    │
│  Eval every 200 steps on descend_to_dlvl_3 × 16                       │
│                                                                       │
│  [ Launch training ]                                                  │
│                                                                       │
│  ─── live: qwen2.5-7b_descend_v3 (step 1840/5000) ───────────────────│
│      loss ▁▂▃▂▂▁▁▂▁▁ 0.42      kl ▁▁▂▂▃▃▂▁▁ 0.038                    │
│  eval-R ▁▃▅▆▇▇▆▇█ 0.71  ├─ scout 0.41  desc 1.2  succ 0.18           │
│  tok/s: 18.2k   GPU mem: 71G/80G   ETA 1h 12m                         │
│                                                                       │
│  [ Promote step 1800 to Launch tab ]   [ Stop ]                       │
└───────────────────────────────────────────────────────────────────────┘
```

GEPA mode swaps the form for: target (`system_prompt` / `per_step_prompt` / both), reward signal, population, generations, proposer model. Output: a new harness TOML auto-listed in the Harness tab.

**Shipping order**: RL ships in v1, GEPA in v1.1. Both modes are scaffolded in v1 with the same `Train` screen and `TrainSpec` shape, but only the RL form is wired to a working subprocess; GEPA shows a "coming soon" empty state with a link to run `prime gepa` directly from the terminal. Reason: RL is the higher-leverage workflow for this team, and `prime rl` is more stable today.

**Harness overlay storage**: git-tracked under `tools/launchpad/harnesses/`. Confirmed. Per-user scratch (`~/.config/launchpad/harnesses/`) is not searched in v1 — keeps "which harness did this run use" reproducible from a sha.

### Screen 3: HARNESS (the adjust-tools/prompts surface)

```
┌─ 3.HARNESS ─────────────────────────────── descend_aggressive (dirty) ┐
│ harnesses          │  [ Edit in $EDITOR ]  [ Diff vs default ]        │
│ ● default          │                                                  │
│   descend_aggr  *  │  ── system_prompt (mode: replace) ────────────── │
│   journal_heavy    │  You are playing NetHack. PRIMARY OBJECTIVE:     │
│   gepa_run42       │  descend. Never search empty corridors. Never... │
│                    │                                                  │
│ [+ new]            │  ── per_step_prompt ──────────────────────────── │
│                    │  template = B1_minimal                           │
│                    │  include_inventory = true                        │
│                    │  include_messages_n = 3                          │
│                    │  map_window = [21, 13]                           │
│                    │                                                  │
│                    │  ── tools ────────────────────────────────────── │
│                    │  ✓ move attack descend search eat pickup         │
│                    │    move_to autoexplore                           │
│                    │  ✗ pray kick throw quaff read journal.*          │
│                    │                                                  │
│                    │  ── rewards (overrides) ──────────────────────── │
│                    │  descent  ×2.0                                   │
│                    │                                                  │
│                    │  ── PREVIEW: what the LLM sees on turn 0 ─────── │
│                    │  [scrollable; re-renders on save]                │
└───────────────────────────────────────────────────────────────────────┘
```

`e` opens the TOML in `$EDITOR` (vim, cursor, code, …). On save, Launchpad re-reads the file, re-renders the preview, and the dirty flag clears. No in-TUI text editor — `$EDITOR` is already perfect.

## Harness overlay (unchanged from v2)

TOML files at `tools/launchpad/harnesses/*.toml`. A ~50-LOC loader in `environments/nethack/nethack.py` checks `NETHACK_HARNESS` and overlays on top of `SYSTEM_PROMPT`, the per-step formatter, the skills registry, and reward weights. No source edits to A/B prompts/tools.

```toml
# tools/launchpad/harnesses/descend_aggressive.toml
name = "descend_aggressive"
extends = "default"

[system_prompt]
mode = "replace"   # replace | append | patch
text = "..."

[per_step_prompt]
template = "B1_minimal"
include_inventory  = true
include_messages_n = 3
include_adjacent   = true
include_visible    = true
map_window         = [21, 13]
ascii_legend       = false

[tools]
enabled  = ["move","attack","descend","search","eat","pickup","move_to","autoexplore"]
disabled = ["pray","kick","throw","quaff","read","journal.add_note","journal.recall","journal.pin_objective"]

[tools.move]
description_override = "Move 1 step in a cardinal direction. Use move_to for paths > 3 steps."

[tools.descend]
require_on_staircase = true

[rewards]
descent = 2.0
```

## Sample specs

### `LaunchSpec`
```json
{
  "label": "B1_descent_smoke",
  "model": "gpt-4.1-mini",
  "harness": "descend_aggressive",
  "env_args": {"tier": "descend_to_dlvl_3", "max_turns": 200},
  "num_examples": 4,
  "rollouts_per_example": 2,
  "tags": ["wave3","smoke"]
}
```

### `TrainSpec` (RL)
```json
{
  "mode": "rl",
  "label": "qwen2.5-7b_descend_v3",
  "base_model": "Qwen/Qwen2.5-7B",
  "harness": "descend_aggressive",
  "tiers": ["corridor_explore","descend_to_dlvl_3"],
  "hparams": {"lr": 1e-6, "kl_coef": 0.04, "group_size": 8,
              "rollouts_per_example": 4, "max_turns": 200, "batch_size": 64},
  "filtering": {"min_difficulty": 0.1, "max_difficulty": 0.9, "oversample_hard": true},
  "eval": {"every_steps": 200, "tiers": ["descend_to_dlvl_3"], "n_examples": 16}
}
```

### `TrainSpec` (GEPA)
```json
{
  "mode": "gepa",
  "label": "gepa_system_v2",
  "harness": "default",
  "target": "system_prompt",
  "reward": "descent",
  "population": 8,
  "generations": 6,
  "proposer_model": "claude-opus-4-7"
}
```

### Trace turn (already exists — unchanged)
NDJSON, one line per turn, at `state["env"].trace_dir/<rollout_id>.ndjson`:
```json
{
  "turn": 47, "t_wall": 1748621234.5, "variant": "B1",
  "raw_grid": ["....","..@.","...."],
  "status": {"hp": 12, "max_hp": 18, "dlvl": 2, "ac": 8, "hunger": "Hungry", "gold": 47},
  "rendered_user_message": "...",
  "assistant_message": "I should head for the stairs...",
  "tool_calls": [{"name": "move", "arguments": {"direction": "south"}}],
  "reward": {"scout": 0.012, "descent": 0.0, "success": 0.0, "ascension": 0.0}
}
```

## Live mode

Same UX as v2, simpler implementation:
- **Local runs** → `watchfiles` on the trace dir; new file = new rollout, appended lines = new turns. ~50ms latency.
- **Hosted runs (v1)** → poll `prime eval samples <id> --output json` every 2s for finished rollouts; parse `prime eval logs --follow` text for coarse progress. Per-turn live for hosted = v1.1 (needs Prime CLI to expose `--ndjson-events` or a webhook).
- Follow toggle (`f`) default on. `End` re-engages after manual scroll.
- Multi-rollout dashboard in the rail when N rollouts are in flight.

## Architecture

```
tools/launchpad/
├── __init__.py
├── __main__.py            # entry — dispatches CLI or boots TUI
├── cli.py                 # click/typer subcommands (eval, train, runs, trace, ...)
├── tui/
│   ├── app.py             # Textual App with 4 screens
│   ├── screens/
│   │   ├── launch.py
│   │   ├── train.py
│   │   ├── harness.py
│   │   └── traces.py      # dual-pane scrubber + live
│   ├── widgets/
│   │   ├── ascii_map.py   # colorize raw_grid
│   │   ├── llm_turn.py    # system/user/assistant/tool_call render
│   │   ├── scrubber.py
│   │   └── log_tail.py
│   └── theme.py
├── core/
│   ├── runs.py            # walk experiments/results, parse metadata + traces
│   ├── traces.py          # NDJSON reader + cache
│   ├── harness.py         # TOML loader/writer/validator/preview
│   ├── launcher.py        # spawn prime eval / vf-eval, stream stdout
│   ├── trainer.py         # spawn prime rl / prime gepa, parse metrics
│   ├── live.py            # watchfiles + prime poll fallback
│   └── git.py             # diff vs HEAD
├── harnesses/             # *.toml overlays (committed to git or local-only)
│   └── default.toml
└── SPEC.md                # this file
```

A small overlay loader (~50 LOC) lands in `environments/nethack/nethack.py` to honor `NETHACK_HARNESS`.

## Packaging & shipping

Pure Python, distributed via the existing `uv` workspace.

### `pyproject.toml` addition
```toml
[project]
name = "nethack-launchpad"
version = "0.1.0"
dependencies = [
  "textual>=0.80",
  "typer>=0.12",
  "watchfiles>=0.21",
  "tomli-w",
  "rich",
]

[project.scripts]
launchpad = "tools.launchpad.__main__:main"
```

### Install paths (in order of preference)

1. **Workspace member** (default — you and the team): already part of `uv sync` in the repo. After `uv sync`, `launchpad` is on PATH. No extra step.
2. **PyPI** (for collaborators outside the repo): `uv pip install nethack-launchpad`. Then `launchpad` is on PATH and finds the repo via `--repo PATH` flag or `$LAUNCHPAD_REPO` env var (defaults to CWD).
3. **uvx zero-install**: `uvx nethack-launchpad trace --latest` runs without persistent install — useful for trying it once.

That's it. No notarization, no `.dmg`, no auto-updater. `uv pip install -U nethack-launchpad` is the upgrade path.

### CI

GitHub Actions: on tag `v*`, run tests + `uv build` + `uv publish` to PyPI. ~15 LOC of YAML.

## Verification

- `uv sync && launchpad --help` lists subcommands.
- `launchpad eval --local -n 1 -r 1` runs a smoke eval end-to-end.
- `launchpad` (no args) opens the TUI; tab cycling works; `q` quits cleanly.
- `launchpad trace --latest` opens the Traces screen with a real rollout; scrubber + dual-pane render `raw_grid` exactly as saved.
- `launchpad eval --watch` launches and auto-attaches Live mode; turns appear within 100 ms of being written.
- `launchpad harness new test --extends default && launchpad harness edit test` opens `$EDITOR`; save → preview re-renders.
- `launchpad train gepa --harness default --target system_prompt --reward descent --generations 2` runs to completion; new `harnesses/gepa_<id>.toml` appears and is selectable in Launch.
- `pytest tests/ -q` still passes (overlay loader is no-op when `NETHACK_HARNESS` unset).
- Over SSH: `ssh box -t launchpad trace --latest` works (validates the no-GUI claim).

## Out of scope (v1)

- Inject-step (human takes over mid-rollout) — v1.1, needs env cooperation.
- Per-turn live for hosted Prime runs — v1.1, needs Prime CLI changes.
- Multi-user / remote — single-user terminal tool.
- In-TUI text editor — we shell out to `$EDITOR`.
- Editing a harness while a run using it is in flight — warn, don't lock.
