# nethack

A Prime Intellect verifiers environment for training and evaluating language-model agents on NetHack.

This is **layer 2** — a thin wrapper around the interface-agnostic `nethack_core` substrate. See `../../docs/design.md` for the full architecture and feature roadmap.

## Quickstart

```bash
# from the repo root: fetch + build the NetHack fork engine first
# (needs cmake/bison/flex/libbz2-dev). nle/minihack are no longer deps.
git submodule update --init --recursive
bash nethack_core/build_engine.sh   # -> third_party/NetHack/src/build/libnethack.so

# install the workspace (--all-packages pulls numpy/gymnasium, formerly
# transitive via nle)
uv sync --all-packages

# smoke test against an OpenAI-compatible endpoint
uv run vf-eval nethack -m gpt-4.1-mini -n 3 -r 1 -a '{"tier": "mini_dungeon"}'
```

See [`../../docs/engine-layer.md`](../../docs/engine-layer.md) for the engine
API (snapshot/branch, level blobs, state modification, difficulty knobs).

## Arguments

`load_environment(...)` accepts:

| arg                | type             | default              | meaning                                              |
|--------------------|------------------|----------------------|------------------------------------------------------|
| `tier`             | str or None      | `"corridor_explore"` | Curriculum tier name; None = uniform across all      |
| `n_examples`       | int              | 256                  | Dataset size                                         |
| `seed`             | int              | 0                    | RNG seed for dataset construction                    |
| `max_turns`        | int              | 200                  | Per-rollout LM turn cap                              |
| `interface`        | str              | `"skill"`            | `"skill"` (one tool per skill) or `"code"` (sandboxed Python with `nh` namespace) |
| `sub_lm`           | SubLM or None    | None                 | Backend for `nh.summarize/plan/recall_lm`. Default at rollout time: `OfflineSubLM` |
| `subgoal_proposer` | Proposer or None | None                 | Backend for the `dynamic_subgoal` tier. Default: `OfflineSubgoalProposer` |
| `variant`          | str              | `"B1"`               | Observation/skill preset (see [Observation variants](#observation-variants)). |
| `compact_obs`      | bool             | True                 | Glyph-run encoding, blank-row strip, inventory diff. Token lever, not a capability lever. |
| `skill_set`        | str              | `"full"`             | `"full"`, `"dir8"`, `"move"`, or a CSV whitelist of skills (NetPlay uses a curated CSV with no low-level `move`). |
| `trace_dir`        | str or None      | None                 | If set, writes per-turn NDJSON (raw grid + rendered obs + assistant msg + tool calls + reward) for offline replay. |
| `continual`        | bool             | False                | Auto-reseed NLE on death and carry the journal/belief state across lives. |
| `continual_lives`  | int              | 5                    | Max lives when `continual=True`. |

### CLI gotcha: `-a` vs `-x`

Override env args from the CLI with `-a` (env-args, baked at construction), NOT
`-x` (extra-env-kwargs, applied via `env.set_kwargs()` AFTER construction):

```bash
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 1 -r 1 \
  -a '{"tier": "dynamic_subgoal", "interface": "code", "max_turns": 30}'
```

`interface` (skill vs code) bakes the tool list at construction time, so passing
it via `-x` is silently ignored. The hosted-eval writeup for Qwen3.5-9B v0.0.14
hit exactly this: `-x '{"max_turns": 30}'` had no effect and the rollout ran to
the default cap of 200 turns. **Always pass env config through `-a`.** See
`docs/EVAL_RECIPES.md`.

## Observation variants

The `variant` kwarg selects a per-turn observation/skill preset. These let you
A/B the observation surface without touching env internals; each is a single
`load_environment(variant=...)` setting. They are wired up and swept by
`experiments/exp16_obs_variants.py`; see `experiment_log.md` for findings.

| code | source | what it changes |
|------|--------|-----------------|
| `B1` | current default | Standing baseline: ASCII grid + compaction + journal. |
| `B0` | calibration | All compaction off (raw rendering). Isolates whether compaction is load-bearing. |
| `G`  | Glyphbox (Wang, 2026) | ASCII + adjacency + hostile-list + code-mode tool surface. |
| `B`  | BALROG (Paglieri et al., ICLR 2025) | No ASCII grid; natural-language scene description only. |
| `N`  | NetPlay (Jeurissen, CoG 2024) | Skill-only action surface (no low-level `move(direction=…)`). |
| `R`  | CPP/GPP | Belief state every 25 turns + hard-drop history before the last checkpoint. |
| `P`  | Continual Harness (arXiv:2605.09998) | Periodic self-refinement directive (update journal objective / record a lesson). |
| `CH` | Continual Harness (full) | Teacher "Refiner" model edits prompt + sub-agents + skill macros + memory. |
| `ND` | this repo | NetPlay skill set + a persistent `=== DESCENT STATUS ===` salience block. |
| `FD` | this repo | `find_and_descend` autopilot skill surface + descent salience block. |
| `E1` | this repo (Wave-3 C) | Surfaces `find_frontiers` output: `=== FRONTIERS ===` (top-5 nearest, with bearing + tile kind), `=== EXPLORATION ===` (coverage + per-turn scout delta), `=== SPATIAL BELIEF ===` (bearings + known stairs coords). Replaces the legacy descent-salience exhortation with pure spatial information. Skill-only + compacted obs (same as `N`). |

**Findings so far** (preliminary, Qwen3.5-9B, seeds 22–26, 200-turn budget):
the ASCII grid is load-bearing — `B` (no grid) collapses capability. Compaction
(`B0` vs `B1`) is a token/cost lever, not a capability lever. The descent
bottleneck (reaching dungeon level 2) is the dominant failure mode: agents
explore but starve or die while looping on the first level. Skill-only surfaces
(`N`) and the `v0.0.65` deadlock-breaker are the levers under active study;
see `experiment_log.md` for the live numbers.

## Tiers

All tiers now run on the NetHack fork engine. The former MiniHack synthetic
tiers have been **retired** in the engine migration; a `nle_task` containing
`"MiniHack"` raises at construction. Synthetic levels are now produced via the
engine's level-blob load path instead (`save_level`/`load_level`,
[`../../docs/engine-layer.md`](../../docs/engine-layer.md)).

### Native NetHack tiers

| tier               | nle_task          | max_steps | success milestone                | description                                            |
|--------------------|-------------------|-----------|----------------------------------|--------------------------------------------------------|
| `corridor_explore` | `NetHackScore-v0` | 2,000     | `reach_dlvl(2)`                  | **Default.** Real NetHack; reach dungeon level 2.      |
| `mini_dungeon`     | `NetHackScore-v0` | 4,000     | `reach_dlvl(3)`                  | Reach dungeon level 3.                                 |
| `mines_to_minetown`| `NetHackScore-v0` | 8,000     | `mine_town_milestone`            | Find the Gnomish Mines branch; reach Mine Town.        |
| `sokoban_complete` | `NetHackScore-v0` | 10,000    | `sokoban_complete_milestone`     | Solve the Sokoban puzzle branch.                       |
| `oracle_consult`   | `NetHackScore-v0` | 8,000     | `oracle_consult_milestone`       | Find and pay the Oracle of Delphi.                     |
| `full_dungeon_easy`| `NetHackScore-v0` | 10,000    | `reach_dlvl(6)`                  | Standard NetHack with reduced max depth.               |
| `full_nle`         | `NetHackScore-v0` | 100,000   | none (ascension via tty markers) | The full game. Ascend.                                 |
| `dynamic_subgoal`  | `NetHackScore-v0` | 4,000     | per-rollout (LLM-proposed)       | Proposer LLM emits an objective + termination_check; the env compiles it into a Milestone. |

### MiniHack synthetic (retired)

The old `empty_room` / `solo_combat` / `multi_combat` MiniHack tiers (formerly
`MiniHack-Skill-Custom-v0`, gated behind `pip install nethack[minihack]`) have
been removed. `minihack` is no longer a dependency. Selecting a `"MiniHack"`
task now raises at `NetHackCoreEnv` construction. The replacement for fixed
synthetic levels is the engine's concrete level-blob path (generate a floor,
`save_level` it to an asset, `load_level` it at reset).

## Rewards

The rubric is built from four `@vf.reward(weight=...)` functions in
`nethack.py`:

| reward             | weight | fires on                                                                 |
|--------------------|--------|--------------------------------------------------------------------------|
| `scout_reward`     | 1.0    | Per-step `scout_delta / 1000.0` — newly-revealed dungeon tiles this step. |
| `descent_reward`   | 10.0   | +1 (× weight) the first time the agent reaches a new max dungeon level.   |
| `success_reward`   | 100.0  | +1 (× weight) when the tier's `success_milestone` fires.                  |
| `ascension_reward` | 1000.0 | +1 (× weight) when `_detect_terminal_outcome` finds an ascension marker.  |

We deliberately do **not** use NetHack's in-game score as a training signal —
it's gameable. See design doc §3.4. The four shaped rewards form an
exponentially-spaced ladder (1 → 10 → 100 → 1000) so the gradient always
points at the deepest unlocked rung.

### Reading the reward signal

`avg_score` reported by `prime eval` is the **unweighted sum** of the four
raw reward-function values, *not* the rubric-weighted total. Decompose it
with `prime eval samples <id> -o json` — each sample carries `scout_reward`,
`descent_reward`, `success_reward`, and `ascension_reward` directly. A score
of `2.155`, for example, is `scout 0.155 + descent 1 + success 1` — a rollout
that explored, descended to dlvl 2, and fired the `corridor_explore`
milestone. Real Qwen3.5-9B rollouts reach this; scout reward accumulates
correctly across the trajectory.

Two things to keep in mind when interpreting short evals:

1. **Sparse by design.** `descent_reward`/`success_reward`/`ascension_reward`
   only fire on milestones. For a non-fine-tuned LM, only `scout_reward` is
   expected to be nonzero until the agent actually descends.
2. **Per-step averaging hides scout reward.** If you look at verifiers'
   per-step `avg_metrics` rather than the trajectory sum, `scout_reward`
   (≤ ~0.05/step, exactly 0 on steps that reveal no new tiles) rounds to 0.0
   in a two-decimal display. Sum across the trajectory, or read
   `state["scout_tiles_seen"]`, to see it accumulating.

Implementation notes for anyone extending the rubric: scout tiles are keyed
by `(max_dlvl_reached, x, y)`, and `max_dlvl_reached` is bumped at the end of
`env_response`, so the first step on a new dlvl attributes its tiles to the
previous dlvl. Journal-op skills deliberately zero `scout_delta` and return
before stepping, so a journal-heavy agent shows `scout_reward: 0` for those
turns regardless of what's on screen.

### Replaying rollouts

`tools/render_rollout_video.py` renders an animated GIF/MP4 of a rollout
(ASCII map + status + per-turn tool call) from either a hosted eval
(`--eval-id`) or a local `trace_dir` NDJSON (`--ndjson`). `tools/dashboard.py`
is a browseable web dashboard over all evals: per-variant reward decomposition
plus a turn-by-turn replay view.

## Status

Live on the Hub at [`jonathanliu/nethack`](https://app.primeintellect.ai/dashboard/environments/jonathanliu/nethack).
Published: **v0.0.64** (hosted eval pins the latest published version, not
local code). Verified end-to-end against Qwen3.5-9B in hosted eval across the
observation variants above — no crashes, both `skill` and `code` interfaces.
Rollouts reach descent + the `corridor_explore` success milestone (e.g. the
NetPlay `N` variant on seeds 22–23). The descent-reliability work in
`v0.0.65` (deadlock-breaker + descent-salience obs) is under validation; see
`experiment_log.md` and `experiments/results/` for the live numbers.
