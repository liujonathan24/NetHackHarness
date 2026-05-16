# v0.0.16 reward fix validation — Qwen3.5-9B

Run 2026-05-15 23:18–23:28 EDT against env v0.0.16 (post reward-bugfix).

## Headline

**The reward bug is fixed.** `scout_reward: 0.092` (was 0.000 in v0.0.14
with identical model + tier). That's 92 normalized tile-discoveries
accumulated across 141 turns of exploration. Reward signal is now real.

## Numbers

| Field | v0.0.14 (broken) | v0.0.16 (fixed) |
|------|----------------:|----------------:|
| `scout_reward` | 0.000 | **0.092** |
| `descent_reward` | 0.000 | 0.000 (still didn't reach dlvl 2) |
| `success_reward` | 0.000 | 0.000 |
| `ascension_reward` | 0.000 | 0.000 |
| total reward | 0.000 | **0.092** |
| turns | 146 | 141 |
| autoexplore calls | 2 | 18 |
| add_note calls | 1 | 1 |
| recall calls | 0 | 6 |
| input tokens | 4.27M | 3.77M |
| cost | $0.79 | $0.71 |

## What the fix did

Old (broken) `scout_reward`:
```python
return float(state.get("scout_delta", 0)) / 1000.0
```
- `Rubric.score_rollout` runs ONCE at end of rollout.
- `scout_delta` reflects only the LAST step's exploration (almost always 0).
- All prior tile-discoveries silently discarded.

New (fixed):
```python
return float(state["scout_reward_total"])
```
- `env_response` accumulates `state["scout_reward_total"] += scout_delta / 1000.0`
  on every step.
- The rubric reads the running sum at end of rollout.

Same pattern applied to `descent_reward` (was comparing `depth > max_dlvl`
after env_response had already advanced max_dlvl; now reads `descent_count`).

## Interpretation

- The model is exploring effectively (18 autoexplore calls vs 2 in v0.0.14).
  The new system-prompt strategy primer is plausibly responsible.
- 6 `recall` calls is new behavior (was 0 in v0.0.14) — the strategy primer
  may be cuing the agent to consult its journal.
- Token use slightly DOWN (3.77M vs 4.27M) despite more substantive activity
  — likely because the model wastes fewer turns on menus (compare: 0 menu_option
  calls here vs 41 in v0.0.14).
- 9B is **still not capable enough** to reach dlvl 2 from a fresh spawn
  in 10 min. scout_reward of 0.092 = ~92 tiles seen over 141 turns =
  ~0.65 tiles per turn. Reasonable for "wandering around".

## Significance

This is the first hosted eval showing nonzero reward end-to-end. Every
Day-4 writeup before this one (4 evals across two models) reported 0
reward but was measuring a broken metric. **All those rollouts had real
exploration the rubric failed to credit.**

Going forward, hosted-eval reward numbers are trustworthy. The 0 → 0.092
transition on Qwen3.5-9B is a clean before/after demonstration of the bug
fix that's worth showing Alex Monday.
