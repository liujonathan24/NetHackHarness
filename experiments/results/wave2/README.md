# Wave-2 sweep: N (control) vs E1 (treatment)

**Date:** 2026-05-30 · **Model:** Qwen/Qwen3.5-9B · **Seeds:** 22-31 (n=9 each; seed 29 still RUNNING at collection time, excluded)

## Headline result

E1 — which surfaces frontiers, coverage, scout_delta, and a spatial-memory note,
backed by tighter frontier detection and a visited-frontier blacklist —
**did not improve descent over N** and trended worse on avg_score:

| variant | n | descended | rate | 95% Wilson CI | avg_score |
|---|---|---|---|---|---|
| N  | 9 | 1 | 11.1% | [ 2.0%, 43.5%] | 0.309 |
| E1 | 9 | 0 |  0.0% | [ 0.0%, 29.9%] | 0.059 |

CIs overlap heavily, but the direction is wrong on both descent and avg_score.

## What changed: dominant failure mode is not what we predicted

Brainstorming reports converged on **false-frontier oscillation** as the root
cause. The taxonomy says otherwise:

| mode | N | E1 |
|---|---|---|
| starved | 4 | 3 |
| killed_by_monster | 4 | 6 |
| **stuck_no_progress** | **0** | **0** |
| turn_budget | 0 | 0 |
| door_block | 0 | 0 |

**No rollout was classified as `stuck_no_progress` in either condition** at the
200-turn budget. The agent is *dying*, not looping. E1's extra obs blocks may
even be pushing it into more aggressive exploration: deaths-by-monster went
4 → 6.

## Files

- `compare_N_vs_E1.md` — the descent-table emitted by `tools/eval_instrument.py`.
- `N_combined.json`, `E1_combined.json` — combined sample dumps used as input.
- Per-seed raw dumps: `{variant}_seed{N}_{eval_id}.json`.

## Implications for wave-3

1. **The eval instrument worked.** Wilson CIs + failure taxonomy gave us an
   interpretable answer in one pass. We can trust future deltas.
2. **The brainstorming diagnosis was wrong (at this seed/budget/model).** The
   bottleneck is survival, not exploration coordination. Wave-3 should pivot to
   `pray` / `engrave_elbereth` skill usage, food economy, or extending the
   turn budget — not more obs blocks.
3. **E1 obs blocks remain a candidate for ablation at larger n** but they are
   not a free intervention: the +78-token-per-turn cost may be displacing
   attention from survival cues.
