# nethack-rl

A training-grade RL environment for NetHack, built on `heiner/nle` + MiniHack.

**Live on the Prime Hub:** [`jonathanliu/nethack`](https://app.primeintellect.ai/dashboard/environments/jonathanliu/nethack)

## Quick links

- [`WAKE_UP.md`](WAKE_UP.md) — the "first 5 minutes" doc for re-onboarding
- [`SESSION_SUMMARY.md`](SESSION_SUMMARY.md) — full Day-3 + Day-4 writeup
- [`docs/EVAL_RECIPES.md`](docs/EVAL_RECIPES.md) — vf-eval / prime-eval reference (model picks, tier list, common errors)
- [`docs/TRAINING_RECIPE.md`](docs/TRAINING_RECIPE.md) — how to wire prime-rl GRPO against this env (concrete recipe, no run yet)
- [`docs/HUB_VERSIONS.md`](docs/HUB_VERSIONS.md) — every Hub release + what it fixed
- [`docs/onboarding/`](docs/onboarding/) — 14 walkthrough docs, one per shipped fix
- [`experiments/REPORT.md`](experiments/REPORT.md) — auto-generated regression-experiment slide

## Architecture

Two layers:

- **`nethack_core/`** — interface-agnostic gymnasium-shaped wrapper with reproducibility, menu/inventory handling, skill API, curriculum, replay. Usable by anyone (verifiers, PufferLib, Sample Factory, scripts).
- **`environments/nethack/`** — verifiers wrapper for the Prime Intellect Environments Hub.

See [docs/design.md](docs/design.md) for the full design doc.

## Getting started

```bash
# system deps for NLE (Debian/Ubuntu)
sudo apt install -y cmake bison flex libbz2-dev

# install (uv workspace handles both packages)
uv sync --extra dev --all-packages

# smoke test the env
pytest tests/ -q              # 219 tests, ~33s
python experiments/run_all.py # 9 regression experiments

# smoke test the verifiers wrapper against the Hub-deployed env
# (needs OPENAI_API_KEY or PI_API_KEY)
vf-eval nethack -m gpt-4.1-mini -n 1 -r 1 \
  -a '{"tier": "corridor_explore"}' --endpoints configs/endpoints.toml

# or hosted (uses Prime Inference, billed to your account)
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 1 -r 1 \
  -a '{"tier": "corridor_explore", "max_turns": 30}'
```

**Key CLI gotcha**: pass env config via `-a` (env-args, goes to
`load_environment`), NOT `-x` (extra-env-kwargs, goes to `set_kwargs`
post-construction). `interface="code"` via `-x` is silently ignored
because the tool list is baked at construction time. See
[`docs/EVAL_RECIPES.md`](docs/EVAL_RECIPES.md).

## Publishing to the Prime Intellect Environments Hub

```bash
uv tool install prime
prime login
python tools/bundle_for_hub.py    # vendor nethack_core into the env package
cd environments/nethack
prime env push --visibility=PRIVATE --auto-bump
```

`bundle_for_hub.py` is critical — the Hub installs only `environments/nethack/`
as a tarball, so `nethack_core` must be vendored in. Then anyone with the
link can `prime env install jonathanliu/nethack`.

## Where things are

```
nethack_core/             # layer 1 — interface-agnostic substrate
  env.py                  # NetHackCoreEnv: NetHackScore wrapper, seed-before-reset
  observations.py         # menu / inventory / status / map shaping (ICLR 2026 fixes)
  skills.py               # SkillRegistry + move/attack/descend/journal/move_to/autoexplore
  journal.py              # Per-rollout structured note store (Pokemon-lesson)
  pathfinding.py          # A* over the glyph grid + frontier autoexplore
  milestones.py           # Pokemon-route-style termination predicates
  curriculum.py           # TierSpec catalog wired to milestones
  replay.py               # TrajectoryRecorder + TrajectoryFrame + audit_reproducibility
environments/nethack/     # layer 2 — verifiers wrapper for the Hub
  nethack.py              # NetHackVerifiersEnv, rubric (scout/descent/success/ascension)
tests/                    # pytest; 88 tests as of Day 3
docs/
  design.md               # the design doc you walked into Monday with
  onboarding/             # one doc per shipped fix, read in order
tools/
  replay_viewer.html      # single-file HTML for replaying trajectories
  record_demo.py          # produce a sample trajectory for the viewer
  profile_env.py          # microbench for the layer-1 hot path
Dockerfile.prime          # NLE-preinstalled image for Prime Sandbox / Hosted Training
```

## What's done

- **Hub-installable** at `jonathanliu/nethack@latest` (v0.0.11+).
- Two-package layout (`nethack-core` + `nethack`) via uv workspace; `tools/bundle_for_hub.py` vendors the substrate into the env package for self-contained Hub installs.
- Reproducibility: `NetHackScore-v0` + seed-before-reset is byte-deterministic.
- ICLR 2026 observation fixes: menu extraction, inventory prompt resolution, role/race/align bootstrap.
- Rewards: per-step scout delta, per-dlvl descent, milestone success, ascension. Death detection from tty.
- Skills (interface="skill"): move/attack/descend/search/pickup/menu_option/inventory_item + `move_to` (A\*) + `autoexplore` (frontier BFS) + journal trio (add_note/recall/pin_objective) + wiki_lookup/wiki_search.
- **Code mode** (interface="code"): one `code(source=...)` tool runs sandboxed Python against an `nh` namespace exposing all skills + sub-LM tools (`nh.summarize/plan/recall_lm`).
- **Dynamic-subgoal curriculum** (the autoresearch axis): tier `dynamic_subgoal` proposes a per-rollout objective via a swappable `SubgoalProposer` and compiles its termination check into a `Milestone`.
- **Belief-state distillation**: at level transitions, auto-summarize prior level into journal via the SubLM backend.
- **Wiki snapshot scraper** (`tools/build_wiki_index.py`) — 30 page seed, Mediawiki API extracts.
- **Replay viewer**: single-file HTML, scrubbable timeline.
- **PufferLib adapter**: `nethack_core/puffer_env.py` (gymnasium-shaped; install separately due to gym pin conflict).
- **Regression experiment harness**: `experiments/run_all.py` tabulates 7 FIX-CONFIRMED verdicts.
- **Tests**: 151 pytest, 7-9 second runtime.

## How to run

```bash
# pytest sanity (no API keys)
pytest tests/ -q

# regression experiments (no API keys)
python experiments/run_all.py

# the full Monday demo (no API keys; pass --model to add live eval)
python tools/run_demo.py --model gpt-4.1-mini   # if you have the key

# live eval against the Hub-installed env
prime eval jonathanliu/nethack -m Qwen/Qwen3-32B -n 5 -r 3
```

See [docs/EVAL_RECIPES.md](docs/EVAL_RECIPES.md) for model picks + tier list +
common-error reference.

## Where things are

```
nethack_core/             # layer 1 — interface-agnostic substrate (13 modules)
  env.py                  # NetHackCoreEnv, seed-before-reset, friendly minihack-missing error
  observations.py         # menu / inventory / status / map shaping
  skills.py               # SkillRegistry + 14 skills + defensive kwarg filtering
  journal.py              # Per-rollout structured note store
  pathfinding.py          # A* over the glyph grid + frontier autoexplore
  milestones.py           # Pokemon-route-style termination predicates
  curriculum.py           # 11 tiers (3 MiniHack, 7 NLE, 1 dynamic_subgoal)
  replay.py               # TrajectoryRecorder + frame capture + audit
  wiki.py                 # WikiPage + WikiIndex (substring + title-weighted ranking)
  code_mode.py            # AST-validated sandboxed Python + nh namespace + SubLM API
  subgoals.py             # SubgoalProposer + predicate compiler (the autoresearch DSL)
  puffer_env.py           # Gym dict adapter for PufferLib (separate venv)
environments/nethack/     # layer 2 — verifiers wrapper for the Hub
  nethack.py              # NetHackVerifiersEnv, rubric, code-mode dispatch, distillation
tests/                    # 151 pytest tests across 15 files
experiments/              # 7 regression experiments + run_all.py + baseline_agents.py
tools/
  replay_viewer.html      # single-file HTML replay viewer
  record_demo.py          # produce a sample trajectory
  profile_env.py          # microbench layer-1 hot path
  build_wiki_index.py     # scrape NetHack wiki via Mediawiki API
  bundle_for_hub.py       # vendor nethack_core into env dir before push
  run_demo.py             # one-command Monday demo runner
configs/endpoints.toml    # vf-eval endpoint registry (OpenAI/Anthropic/pinference)
docs/
  design.md               # original design doc
  EVAL_RECIPES.md         # vf-eval / prime-eval reference
  onboarding/             # 14 docs, one per shipped fix; read in order
Dockerfile.prime          # NLE-preinstalled image for Prime Sandbox / Hosted Training
SESSION_SUMMARY.md        # latest session writeup (Day 3 + Day 4)
```

## Project status

**v0.0.11+** as of 2026-05-15 evening EDT. Hub-live, 151 tests, 7 regression
experiments green, both Track A and Track B headlines wired. Default tier
`corridor_explore` (NLE-only, reach dlvl 2).

## Where to start contributing

The codebase is structured so each "feature" is a self-contained file. Start
with `docs/onboarding/` (14 docs, ~80–200 lines each, one per shipped fix).

Open TODOs in order of value:
1. **Real prime-rl SubLM proposer** for `dynamic_subgoal` tier (currently
   `OfflineSubgoalProposer` returns canned per-role specs).
2. **PufferLib upstream PR** to `pufferlib.environments.nethack` using our
   adapter — needs a fresh venv with NLE 1.2 pin (gymnasium conflict).
3. **More wiki pages** — `tools/build_wiki_index.py --full` scrape (~3000
   pages, ~5MB, ~20min runtime; not yet implemented).
4. **Src-layout refactor** — move source under `nethack_core/nethack_core/`
   so editable installs Just Work. See [[uv-workspace-non-editable]] memory.
5. **C-side**: optional `rn2` tracing patch in `nle_patches/` for true
   RNG-level reproducibility audits. Stretch.
Awaiting Monday design review with Alex Zhang.
