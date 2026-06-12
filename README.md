# nethack-rl

A training-grade RL + evaluation environment for NetHack, built on a custom
NetHack **fork** (the `third_party/NetHack` submodule) driven through a ctypes
binding — `nle`/`minihack` are no longer used. It ships a skill-based tool
interface, a milestone curriculum, a dozen+ observation encodings (ASCII /
BALROG / JSON / TOON / rendered tiles / tty raster), replay capture, and an
in-browser rollout viewer. The engine adds in-memory snapshot/branch, portable
level blobs, secure state modification, and parametric difficulty knobs. See
[`docs/engine-layer.md`](docs/engine-layer.md) for the engine reference.

**Mirrors:**
- Prime Hub: [`jonathanliu/nethack`](https://app.primeintellect.ai/dashboard/environments/jonathanliu/nethack) (v0.0.66+)
- GitHub: [`liujonathan24/NetHackHarness`](https://github.com/liujonathan24/NetHackHarness)

## Quick links

- [`WAKE_UP.md`](WAKE_UP.md) — the "first 5 minutes" doc for re-onboarding
- [`SESSION_SUMMARY.md`](SESSION_SUMMARY.md) — latest session writeup
- [`docs/EVAL_RECIPES.md`](docs/EVAL_RECIPES.md) — vf-eval / prime-eval reference (model picks, tier list, common errors)
- [`docs/TRAINING_RECIPE.md`](docs/TRAINING_RECIPE.md) — how to wire prime-rl GRPO against this env
- [`docs/HUB_VERSIONS.md`](docs/HUB_VERSIONS.md) — every Hub release + what it fixed
- [`docs/onboarding/`](docs/onboarding/) — 20 walkthrough docs, one per shipped fix
- [`docs/design.md`](docs/design.md) — the design doc
- [`openspec/specs/`](openspec/specs/) — capability specs (the current source of truth for each feature)

## Rollout viewer

`tools.rollout_view.live_server` serves a localhost UI for browsing recorded
rollouts and stepping a fresh one live. It renders each turn in two panes: the
**game state** (the tty grid the human sees) on the left and the exact **LLM
input** (the chosen encoding) on the right — so you can see precisely what the
model received each turn.

```bash
# (server binds 127.0.0.1:8765; runs-root is scanned for recorded rollouts)
PYTHONPATH="$PWD:$PWD/environments/nethack" \
  python -m tools.rollout_view.live_server \
  --runs-root environments/nethack/outputs/evals --port 8765

# generate keyless demo traces first if you have no recorded runs:
PYTHONPATH="$PWD:$PWD/environments/nethack" \
  python -m tools.rollout_view.demo --variants B1 JSON IMG
```

### Where the runs are

All eval/rollout output lives under **`environments/nethack/outputs/`** (gitignored).
`prime eval run --output-dir <dir>` writes a run there; point `--output-dir` at
`environments/nethack/outputs/evals/<name>` so runs are **persistent and show up in
the viewer** (writing to `/tmp` works but is ephemeral). Recent benchmark runs are
kept under `environments/nethack/outputs/evals/` (e.g. `n24_B1/`, `n24_JSON/`,
`final_<encoding>/`). The viewer's `--runs-root` defaults to that folder.

### Browse files + stats dashboard

The server has two extra views (linked from the index):

- **`/browse`** — a Finder-style click-through of the runs folder: navigate nested
  directories via breadcrumbs, and open any `.ndjson` trace or verifiers
  `results.jsonl` straight into the dashboard.
- **`/dashboard?path=<rel>`** — a self-contained stats dashboard over a run: KPI strip
  (mean max dlvl, death rate, kills…), a per-run outcome table, and inline time-series
  charts (dlvl / HP / XP / cumulative kills over turns). Also available as a CLI:

  ```bash
  PYTHONPATH="$PWD:$PWD/environments/nethack" \
    python -m tools.rollout_view.dashboard \
    environments/nethack/outputs/evals/n24_B1/evals/*/*/results.jsonl \
    -o dashboard.html -m dlvl,hp,xp,kills_cum
  ```

  Metrics are computed **post-hoc** over saved traces (`tools/rollout_view/stats.py`);
  define a **custom obs/metric** with `stats.register_metric(name, fn)` where
  `fn(turn_record) -> value` derives anything from the saved per-turn observation.

**Index** — recorded runs + a live-session launcher:

![Rollout viewer index](docs/assets/rollout_view/index.png)

**Run viewer** — scrubbable per-turn timeline (here, turn 46 of a 99-turn Monk
rollout). The right pane shows the exact encoding the model saw; the same
viewer, three encodings:

`IMG` (rendered NetHack tiles — the spatial channel is the image):

![IMG encoding](docs/assets/rollout_view/run_img.png)

`B1` (canonical ASCII map + status/inventory):

![B1 ASCII encoding](docs/assets/rollout_view/run_b1.png)

`JSON` (the canonical map model serialized as structured text):

![JSON encoding](docs/assets/rollout_view/run_json.png)

A recorded run opens at `/run?dir=<path>`; a live session at `/live?variant=<V>`
(POST `/step` advances one turn). `tools/launchpad/` is a companion TUI over the
same on-disk trace format.

## Architecture

A `uv` workspace with four members (`pyproject.toml` → `tool.uv.workspace`):

- **`nethack_core/`** — interface-agnostic substrate. `NetHackCoreEnv`
  (`NetHackScore-v0` wrapper, seed-before-reset), observation shaping
  (`StructuredObservation`), and the canonical typed **map model**
  (`build_map_model`: player pos + typed entities + compact grid, built from
  NLE glyph classifiers).
- **`nethack_interface/`** — a typed, pysc2-style interface over the core env:
  `Observation` / `observation_spec`, `Action` / `RawAction` / `action_spec`,
  and `NetHackInterface` with `reset() -> Observation` and
  `step(action) -> (Observation, reward, done, info)`. Typed actions dispatch
  through the same skill registry the harness uses; a raw NLE action-index
  escape hatch is always available.
- **`environments/nethack/`** — the verifiers wrapper for the Prime Hub
  (`nethack.py: load_environment`) plus the `nethack_harness/` package (prompt
  variants, curriculum, skills, navigation, memory, code-mode).
- **`tools/launchpad/`** — TUI for viewing rollouts (separate package).

See [docs/design.md](docs/design.md) for the full design doc, and
[openspec/specs/](openspec/specs/) for per-capability specs.

## Getting started

```bash
# system deps for the NetHack fork build (Debian/Ubuntu)
sudo apt install -y cmake bison flex libbz2-dev

# fetch the NetHack fork submodule + build libnethack.so
git submodule update --init --recursive
bash nethack_core/build_engine.sh   # -> third_party/NetHack/src/build/libnethack.so

# install the uv workspace. --all-packages is REQUIRED: numpy/gymnasium used
# to arrive transitively via nle; with nle/minihack removed they are direct
# workspace deps and a bare `uv sync` under-installs.
uv sync --extra dev --all-packages

# smoke test (no API keys)
pytest tests/ -q                # ~396 tests across 53 files
python experiments/run_all.py   # regression experiments → experiments/REPORT.md

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
post-construction). `interface="code"` via `-x` is silently ignored because the
tool list is baked at construction time. See
[`docs/EVAL_RECIPES.md`](docs/EVAL_RECIPES.md).

## Configuring a rollout

Everything below is a `load_environment` argument (pass as JSON via `-a`):

**Interface** — `interface`:
- `"skill"` (default): one OpenAI function-calling tool per skill.
- `"code"`: a single `code(source=...)` tool that runs sandboxed Python against
  an `nh` namespace exposing all skills + a queryable `nh.map` + sub-LM tools
  (`nh.summarize/plan/recall_lm`).

**Observation encoding** — `variant` (from `VARIANT_REGISTRY`):

| variant      | what the model sees |
|--------------|---------------------|
| `B1` (default), `B0` | canonical ASCII map + status/inventory/adjacency |
| `B`          | BALROG natural-language scene (no ASCII grid) |
| `G`          | glyph-box render (pair with `interface="code"`) |
| `JSON`, `TOON` | the canonical map model serialized as structured text (`map_detail` = `full`/`minimal`) |
| `IMG`        | rendered NetHack tiles (image is the sole spatial channel) |
| `IMG_TTY`    | tty-text raster image |
| `ND`, `FD`   | descent-salience blocks |
| `E1`, `E2`   | frontier-surface obs (text blocks / painted onto the map) |
| `R`          | summarize-and-reset history compaction |
| `P`, `CH`    | Continual-Harness self-refinement (`P`) / full continual harness (`CH`) |

**Skill set** — `skill_set`: `"full"` (default), `"move"`, `"dir8"`,
`"netplay"` (Jeurissen CoG 2024 profile), or a comma-separated allowlist.

**Curriculum** — `tier` (13 tiers in `nethack_harness/curriculum/curriculum.py`):
`empty_room`, `solo_combat`, `multi_combat`, `corridor_explore` (default),
`mini_dungeon`, `mines_to_minetown`, `sokoban_complete`, `oracle_consult`,
`full_dungeon_easy`, `full_nle`, `dynamic_subgoal`, `quest_complete`,
`castle_reached`. Pass `tier=None` to sample uniformly across all tiers.

**Memory / history** — `history_keep_full`, `history_drop_after`,
`belief_state_interval` (auto-summarize prior levels into the journal),
`journal_render_max_chars`, `continual` + `continual_lives` (auto-reset on
death, preserving journal/belief state).

**Capture** — `trace_dir`: write per-turn NDJSON (raw grid, structured obs,
rendered message, tool calls, action, reward, dlvl, hp) for the rollout viewer.

Rewards are always `scout_reward` + `descent_reward` + `success_reward` +
`ascension_reward` (a `vf.Rubric`).

## Where things are

```
nethack_core/             # layer 1 — interface-agnostic substrate
  env.py                  # NetHackCoreEnv: NetHackScore wrapper, seed-before-reset
  observations.py         # StructuredObservation: menu/inventory/status/map shaping
  map_model.py            # canonical typed map model (build_map_model)
nethack_interface/        # typed pysc2-style interface over the core env
  env.py                  # NetHackInterface: reset()/step() returning typed Observation
  observation.py          # Observation + observation_spec
  actions.py              # Action / RawAction + action_spec (derived from skill registry)
environments/nethack/      # layer 2 — verifiers wrapper for the Hub
  nethack.py              # load_environment, NetHackVerifiersEnv, rubric, code/skill dispatch
  nethack_harness/
    prompt/               # prompt_spec (VARIANT_REGISTRY), rendering, balrog (progression),
                          #   image_render (tiles/tty PNG), map_encoders (JSON/TOON)
    curriculum/           # curriculum (13 tiers), milestones, subgoals (dynamic_subgoal)
    navigation/           # pathfinding (A* + frontier autoexplore)
    memory/               # journal (per-rollout structured note store)
    tools/                # skills (SkillRegistry), code_mode (nh namespace), wiki
    helpers.py            # skill adapter, skill_set profiles, per-turn trace capture
    refiner.py            # Continual-Harness refinement
tools/
  rollout_view/           # in-browser viewer: live_server (/, /run, /live, /browse,
                          #   /dashboard), index, html, demo; browse.py (file browser),
                          #   stats.py (post-hoc time-series metrics), dashboard.py (charts)
  launchpad/              # TUI over the same trace format (4th workspace package)
  encoding_eval/          # run one task across encodings × models, compare metrics
  eval_instrument.py      # summarize_eval / classify_failure / wilson_ci
  bundle_for_hub.py       # vendor nethack_core into the env dir before push
  build_wiki_index.py     # scrape the NetHack wiki via the Mediawiki API
  record_demo.py / run_demo.py / profile_env.py / render_rollout_video.py
experiments/              # exp01..exp15 regression harness + run_all.py + build_report.py
tests/                    # 53 pytest files, ~396 test functions
configs/endpoints.toml    # vf-eval endpoint registry (OpenAI/Anthropic/pinference)
docs/                     # design.md, EVAL_RECIPES.md, TRAINING_RECIPE.md, onboarding/ (20)
openspec/                 # capability specs + change history (current source of truth)
Tiles16x16-nethack.png    # swappable tileset for the IMG GlyphMapper renderer
Dockerfile.prime          # builds libnethack.so from the fork submodule; image for Prime Sandbox / Hosted Training
```

## Publishing to the Prime Intellect Environments Hub

```bash
uv tool install prime
prime login
python tools/bundle_for_hub.py    # vendor nethack_core into the env package
cd environments/nethack
prime env push --visibility=PRIVATE --auto-bump
```

`bundle_for_hub.py` is critical — the Hub installs only `environments/nethack/`
as a tarball, so the workspace dep `nethack-core` is unresolvable there. The
script copies the substrate into `environments/nethack/nethack_core/` so the
built wheel is self-contained. Then anyone with the link can
`prime env install jonathanliu/nethack`.

## Project status

**Env v0.0.66+ on the Hub.** Default tier `corridor_explore` (NLE-only, reach
dlvl 2), default variant `B1`. ~396 tests green; regression experiments green
(`experiments/run_all.py` → `experiments/REPORT.md`). Active research axis:
observation-encoding comparison (`tools/encoding_eval/`) across ASCII / IMG /
IMG_TTY / JSON / TOON.

## Where to start contributing

The codebase is structured so each feature is a self-contained module with a
matching spec in [`openspec/specs/`](openspec/specs/) and a walkthrough in
[`docs/onboarding/`](docs/onboarding/). Start there. The repo uses an OpenSpec
workflow: capability specs live under `openspec/specs/`, and in-flight work is
proposed as a change under `openspec/changes/` before it lands.
