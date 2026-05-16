# nethack

A Prime Intellect verifiers environment for training and evaluating language-model agents on NetHack.

This is **layer 2** — a thin wrapper around the interface-agnostic `nethack_core` substrate. See `../../docs/design.md` for the full architecture and feature roadmap.

## Quickstart

```bash
# from the repo root
uv pip install -e ../../nethack_core
uv pip install -e .

# smoke test against an OpenAI-compatible endpoint
uv run vf-eval nethack -m gpt-4.1-mini -n 3 -r 1 -a '{"tier": "empty_room"}'
```

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

## Tiers

Tier `nle_task` decides whether you get a real NetHack game or a MiniHack
synthetic level. The substring `"MiniHack"` in `nle_task` is the marker.

### Real NLE (no extra deps)

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

### MiniHack synthetic (requires `pip install nethack[minihack]`)

| tier            | nle_task                     | max_steps | success milestone   | description                                  |
|-----------------|------------------------------|-----------|---------------------|----------------------------------------------|
| `empty_room`    | `MiniHack-Skill-Custom-v0`   | 200       | reach dlvl 2 (tty)  | 3x3 room with a downstair. Descend to win.   |
| `solo_combat`   | `MiniHack-Skill-Custom-v0`   | 400       | reach dlvl 2 (tty)  | One jackal + a sword in a small room.        |
| `multi_combat`  | `MiniHack-Skill-Custom-v0`   | 600       | reach dlvl 2 + HP>0 | Three weak monsters in a larger room.        |

MiniHack tiers carry a `des_file` body that's compiled by
`MiniHack-Skill-Custom-v0`; the NLE tiers leave `des_file=None`. The Hub
install does not include MiniHack — if you select a MiniHack tier without
the optional dep installed, `NetHackCoreEnv` raises a friendly install hint.

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

### Reward signal calibration

Recent hosted-eval writeups (`experiments/results/hosted_eval_*.md`) report
`reward: 0.0` across 146–162 turns at 9B and 35B-A3B. Two reasons this is
expected before treating it as a bug:

1. **Sparse by design.** `descent_reward` requires reaching dlvl 2; neither
   model managed it in the 10-minute wallclock. `success_reward` and
   `ascension_reward` only fire on terminal milestones. For a non-fine-tuned
   LM on `corridor_explore`, only `scout_reward` is expected to be nonzero
   in a short eval.
2. **Per-step averaging hides scout reward.** Verifiers reports `avg_metrics`
   as a per-step mean. `scout_reward = scout_delta / 1000.0` is at most
   ~0.05/step (50 new tiles × 1/1000) and is exactly 0 on any step that
   didn't reveal new tiles — including journal-op steps, blocked moves, and
   menu navigation. A 144-step rollout that revealed ~200 tiles total
   averages to ~0.0014/step, which rounds to 0.0 in two-decimal display.

To verify scout is actually accumulating (not a code bug), look at
`state["scout_tiles_seen"]` size or the **sum** of scout reward across the
trajectory rather than the per-step mean. Replay JSONs in
`tools/replay_viewer.html` show this directly.

#### Suspected scout-reward bug (under investigation)

A separate subagent is auditing this; flagging the suspect for the doc.
`env_response` updates `state["scout_tiles_seen"]` inside the per-action
loop via `_iterate_visible_tiles(last_obs)`, which reads `obs.chars` as an
**attribute**. Other code paths in the same function read the same obs as a
**dict** (`raw_obs.get("blstats")` in `_check_halt_condition`). If
`NetHackCoreEnv.step` returns a dict, the attribute access raises
`AttributeError` inside the tile-iteration loop — and because the loop is
the only writer to `scout_tiles_seen`, scout_delta stays 0 for the whole
rollout while everything else proceeds normally. Two related quirks worth
noting either way:

- Tiles are keyed by `(max_dlvl_reached, x, y)` but `max_dlvl_reached` is
  only bumped at the **end** of `env_response`, so the first step on a new
  dlvl attributes its tiles to the previous dlvl.
- Journal-op skills explicitly zero `scout_delta` and return before any
  env stepping, which is correct but also means a journal-heavy agent will
  show `scout_reward: 0` regardless of what's on screen.

Don't patch from this README — defer to subagent C.

## Status

Live on the Hub at [`jonathanliu/nethack`](https://app.primeintellect.ai/dashboard/environments/jonathanliu/nethack).
Latest verified: **v0.0.14** running end-to-end against Qwen3.5-9B and
Qwen3.5-35B-A3B in hosted eval (no crashes, both `skill` and `code`
interfaces). Reward is currently 0 for short rollouts — long-horizon eval,
that's the design. See `experiments/results/` for full eval writeups.
