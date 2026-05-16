# Experiments

Each script here demonstrates that an onboarding-doc fix actually fixes its
bug. Pattern:

1. Define `legacy_<thing>(...)` inline — reproduces the buggy behavior we
   replaced. Small, comment-cited to the doc it relates to.
2. Import `fixed_<thing>` from `nethack_core` — the current code.
3. Run both on the **same seed** and capture the comparable metric.
4. Save `results/<exp>.json` + `results/<exp>.png`.
5. Print a one-line verdict.

## Running

```bash
source ../.venv/bin/activate
uv pip install matplotlib  # NB: NOT in any pyproject — `uv sync` will uninstall it
python experiments/exp02_scout_reward.py
```

Matplotlib lives outside the workspace deps because it's only used here, and
adding it to nethack-core would bloat the Hub install. If `uv sync` runs and
your plots stop generating, just reinstall it.

Or all at once:

```bash
python experiments/run_all.py
```

## Mapping to onboarding docs

| Exp | Doc | Type | Status |
|-----|-----|------|--------|
| exp01 | 01-seeding | regression (binary) | ✓ |
| exp02 | 02-scout-reward-delta | regression (plot) | ✓ |
| exp03 | 03-menu-region-masking | regression (diff) | ✓ |
| exp04 | 04-bootstrap-character | regression (table) | ✓ |
| exp05 | 05-terminal-outcome-detection | regression (event) | ✓ |
| exp06 | 06-journal-skill | demo | TODO (no before/after — pure addition) |
| exp07 | 07-milestones | demo | TODO (pure addition) |
| exp08 | 08-pathfinding-autoexplore | demo (plot) | ✓ |
| exp09 | 09-replay-viewer | demo (use `tools/record_demo.py`) | done |
| exp10 | 10-profiling | demo (use `tools/profile_env.py`) | done |
| exp11 | 11-pufferlib | demo | TODO |
| exp12 | 12-wiki | demo | TODO (pure addition; see `tools/build_wiki_index.py`) |
| exp13 | 13-code-mode | demo | ✓ (with Track B wiring) |
| exp14 | 14-dynamic-subgoals | demo (autoexplore baseline) | ✓ |
| exp15 | 15-compaction | benchmark (per-turn + cumulative savings) | ✓ |
| baseline_agents | (no doc) | reward distribution sweep | ✓ |

Also recorded: hosted-eval writeups in `results/hosted_eval_*.md` document
real prime-eval runs against the live Hub env, including the v0.0.16
reward-bug-fix validation and the qwen3.5-9b vs 35b-a3b comparison.

## How to add a new experiment

Copy `exp02_scout_reward.py` as a template, replace the legacy function and
the metric. Keep it self-contained — one file per fix, no shared utilities,
no test fixtures.
