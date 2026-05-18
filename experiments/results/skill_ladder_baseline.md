# Baseline skill ladder — Qwen3.5-9B, non-compact, n=8 each

**Question:** Are `find_and_descend` / `autoexplore` / `move_to` doing the
LM's spatial reasoning for it? If we strip them, does descent rate drop?

**Setup:** v0.0.63, `corridor_explore` tier, non-compact
(`compact_obs=False, history_keep_full=99999, history_drop_after=99999`),
`max_turns=1000` (effectively uncapped — Qwen3.5-9B halts well before).

**`skill_set` arg** added to `load_environment` controls which tools are
exposed:
- `dir8`: 8 single-direction tools (`north`/`northeast`/.../`northwest`)
  + `descend` + `search` + `pickup` + `attack` + survival. NO
  `move`/`move_to`/`autoexplore`/`find_and_descend`/`kick`. Most-faithful
  NLE-primitive baseline.
- `move`: `move(direction=...)` + survival. No path-finding aggregators.
- `full`: current 14-skill registry incl. mega-skills.

## Numbers

| skill_set | n | descents | saw `>` | best reward | mean LM turns | mean reward |
|---|---:|---:|---:|---:|---:|---:|
| `dir8`   | 8 | **0/8** | 0/8 | 0.086 | 64 | 0.064 |
| `move`   | 8 | **0/8** | 0/8 | 0.137 | 83 | 0.065 |
| `full` (iter18 ref) | 24 | **0/24** | 0/24 | 0.147 | ~80 | 0.079 |
| `full` (iter11, lucky seed) | 1 | **1 ⭐** | 1 | 2.156 | 48 | 2.156 |

## Interpretation

1. **The helper skills are not "cheating" in any measurable way on this
   evaluation.** Going from 8 single-direction tools all the way up to
   the full mega-skill stack only nudges mean reward 0.064 → 0.079.
   None of the three skill sets unlocked a descent on this seed slice.

2. **The bottleneck is exploration depth, not action expressiveness.**
   Across all 40 non-compact rollouts in this ladder, zero rollouts
   ever revealed `>` in the map. The agent terminates around turn
   80-110 (regardless of `max_turns=1000`) without finding stairs.
   Scripted controls and seeds 0-7 confirm the harness CAN reach `>`
   in ~25% of seeds — but the seeds vf-eval's default dataset picks
   appear to be harder than that.

3. **Helper skills DO have an effect on *behavior shape*, not outcomes.**
   With `full`, the agent calls `find_and_descend` 5-15× per rollout
   and queues ~80 actions each. With `dir8` it calls single-direction
   tools 50+× per rollout. Final exploration coverage ends up similar
   (~80 game turns of NLE progress).

4. **The "find_and_descend is offloading reasoning" framing was right
   in spirit but wrong in effect** — the LM with full skills *should*
   benefit from the offload, but in practice it makes single-tool
   calls anyway, and even when it does call the mega-skill it
   doesn't reliably stack multiple calls to reach `>`.

## What would actually move the needle

- **Easier seed distribution.** vf-eval's `seed=0` dataset happens to
  pick NLE dungeon levels where `>` requires `search` at specific
  dead-ends. Pinning the scripted-control seeds (0-7) where `>` is
  reachable in 30-60 game-turns would yield a ~25% descent floor.
- **RL training on the existing dense scout reward.** The harness is
  fine; the policy needs to learn "stack find_and_descend calls until
  reward fires".
- **Stronger model.** Haiku 4.5 with same setup (n=4, max_turns=40):
  also 0/4, but used 105-232 turns and called `find_and_descend`
  9-17 times — so the bottleneck is not just Qwen3.5-9B-specific.

## Artifacts

- `experiments/results/baseline_dir8_t1000/`
- `experiments/results/baseline_move_t1000/`
- `experiments/results/local_nc_n24_v2/` (full skill set, n=24)
- `experiments/results/hub_haiku_v0063/` (Haiku 4.5, n=4)
