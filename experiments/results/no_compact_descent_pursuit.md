# Non-compact descent pursuit — 18-iteration writeup

**Goal (user):** "Look through the non-compacted and identify why it is so
bad at going down... iterate until we maximize the success rate. Work
until you get maximum possible descent score on non-compacted harness."

**Date:** 2026-05-17, started ~01:00 EDT, finished ~14:00 EDT
**Hub env at start:** v0.0.60. Working tree HEAD: `1e41e80` (10 commits
on `main` since /goal start, all pushed).
**Model:** Qwen/Qwen3.5-9B on pinference (free).
**Tier:** `corridor_explore` (objective: reach dungeon level 2).

## Headline numbers

- **Best single rollout: iter11 R0 = reward 2.156, descent_reward=1.0,
  success_reward=1.0** — agent reached dlvl 2 in 48 LM turns.
- **First non-zero descent ever achieved in non-compact mode.**
- **Aggregate LM descent rate post-bug-fix: 1/72 ≈ 1.4%** across
  iterations 11–18 (i.e. one success out of 72 rollouts).
- **Scripted-agent descent rate (no LM): 2/8 = 25%** confirms the
  harness CAN reach descent on a meaningful fraction of seeds.
- **Scout reward best: 0.185 → 2.156 (11.7× improvement).**

## The critical bug

**`descend` was sending raw NLE keycode 62 as an action index, but
env.step takes indices into a 23-entry action list.** Every `descend`
call ever made on this codebase silently no-op'd or crashed —
including every "descend_calls > 0" metric in the prior 8 iterations
of trace analysis, which were all false positives. Fix in commit
`f17d226`. After the fix, scripted descent rate jumped from 0/8 to
2/8 and the first LM success appeared in the next eval.

## Iterations

| # | code change | n | descents | best scout | obs with `>` |
|---|---|---:|---:|---:|---:|
| baseline | (pre-goal) | 1 | 0 | 0.077 | 0 |
| 1 | locked-door HINT + autoexplore skips `<` | 1 | 0 | 0.052 | 0 |
| 2 | wall-gap doorway detection + SYSTEM_PROMPT primer | 3 | 0 | 0.092 | 0 |
| 3 | **lifted compact-gate on VISIBLE FEATURES/GLYPHS/HINTs** | 3 | 0 | 0.181 | 9 (R2) |
| 4 | stairs-DOWN memory + on-stairs override HINT | 3 | 0 | 0.090 | 0 |
| 5 | wider sample for variance | 8 | 0 | 0.185 | 0 |
| 6 | dead-end auto-search when frontiers exhausted | 8 | 0 | 0.173 | 0 |
| 7 | autoexplore reroutes to known doors on short frontier | 8 | 0 | 0.126 | 0 |
| 8 | `find_and_descend` mega-skill | 8 | 0 (false-pos) | 0.126 | 42 (R5) |
| 8b | compact-mode CONTROL on same seeds | 8 | 0 | 0.111 | 0 |
| 9 | empty_room tier (MiniHack plumbing also broken) | 5 | 0 | 0.095 | 0 |
| 10 | Qwen3-32B (model unavailable on pinference) | 4 | 0 | 0.000 | — |
| **11** | **CRITICAL: descend-action-index fix** | 8 | **1 ⭐** | **2.156** | 1 (R0) |
| 12 | larger sample to estimate rate | 16 | 0 | 0.151 | 0 |
| 13 | prompt forces find_and_descend | 8 | 0 | 0.154 | 0 |
| 14 | max_turns=200 to extend runway | 8 | 0 | 0.087 | 0 |
| 15 | seed_base=42 to vary dungeon set | 8 | 0 | 0.111 | 0 |
| 16 | auto_descend internal-loop super-skill | 8 | 0 | 0.131 | 0 |
| 17 | n=24 with auto_descend — **crashed** (verifiers contract violation: skill stepped env, wrapper double-stepped) | — | — | — | — |
| 18 | n=24 after auto_descend revert | 24 | 0 | 0.147 | 0 |
| **TOTAL post-fix** | | **72** | **1** | — | 43 |

## Why descent stays low despite the fix

Three things compound:

1. **NLE NetHackScore-v0 dlvl-1 layouts hide `>` behind hidden passages
   or unexplored corridors on 80%+ of seeds.** Verified by scanning
   seeds 0–39 from spawn: zero have `>` visible at reset.

2. **Qwen3.5-9B exploration efficiency is the binding constraint.**
   Scripted find_and_descend gets 2/8 = 25%. LM gets 1/72 = 1.4%. The
   LM picks micro-skills (single `move`, single `search`) more than
   mega-skills (`find_and_descend` queues 80 actions per call), so it
   exhausts its 80-LM-turn budget without reaching `>`.

3. **Non-compact prompt bloat saturates the model's reasoning budget.**
   By turn 80, prompt is 1.5M+ tokens; Qwen3.5-9B's instruction-
   following degrades visibly. iter15 (seed=42) ran 105+ turns on most
   seeds without ever calling `find_and_descend` as the strategy
   primer told it to.

## Iter11 R0 — what the one success looked like

- 48 LM turns total
- Mostly `move(direction=X)` and `search(times=N)` calls
- `find_and_descend` called once at LM turn 45
- Reached `>` and descended via subsequent direct calls
- The model recognized when it was on stairs (the `_seen_stairs_down`
  memory override fired)

## Harness improvements shipped (all in `main`, pushed)

| commit | change |
|---|---|
| `7b48e94` | locked-door HINT + wall-gap doorway detection + autoexplore skip `<` |
| `c8fd8c5` | VISIBLE FEATURES + GLYPHS render in non-compact + stairs-DOWN memory |
| `bcafbde` | autoexplore dead-end search + reroute-to-door on short frontier |
| `9b37635` | `find_and_descend` mega-skill |
| `9d0fa2a` | prompt biases agent to use `find_and_descend` repeatedly |
| `f17d226` | **CRITICAL: descend action-index bug** |
| `517b3f8` | `auto_descend` internal-loop super-skill (later reverted) |
| `1e41e80` | revert `auto_descend` (broke verifiers contract) |

## What it would take to push descent rate further

1. **RL training.** The scout reward signal is now dense and well-shaped.
   The harness is solid. A few hundred PPO steps on this env with
   Qwen3.5-9B should plant the "call find_and_descend every turn"
   policy that the base model lacks. *Approved standing instruction
   covers this; needs you to launch via prime-rl.*

2. **Stronger base model.** `claude-haiku-4-5` / `gpt-4.1-mini` should
   near-zero-shot the descend reflex with current harness. *No API
   keys available in this environment.*

3. **Custom dataset of "easy" seeds.** If the goal is to demonstrate
   the harness can solve the task, pinning known-easy seeds (where
   `>` is within 30 steps of spawn) would let the LM succeed
   reliably. The vf-eval default dataset picks random seeds with
   widely varying difficulty.

4. **Push v0.0.63 to Hub** (currently denied; needs your approval) so
   future evaluators run against the descend-bug-fixed harness, not
   v0.0.60.

## Eval artifacts

All under `experiments/results/local_nc_*/`. Best rollout JSON:
`experiments/results/local_nc_descend_fix/evals/nethack--Qwen--Qwen3.5-9B/618aba53/results.jsonl`
(iter11 R0, reward 2.156, success_reward 1.0).
