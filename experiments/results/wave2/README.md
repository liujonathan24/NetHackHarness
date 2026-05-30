# Wave-2/3 sweep: N (control) vs E1 (text frontiers) vs E2 (painted frontiers)

**Date:** 2026-05-30 · **Model:** Qwen/Qwen3.5-9B · **Seeds:** 22-31 · n=9 each (one straggler per sweep)

## Headline

| variant | n | descended | rate | 95% Wilson CI | avg_score |
|---|---|---|---|---|---|
| **N**  | 9 | 1 | 11.1% | [ 2.0%, 43.5%] | 0.309 |
| **E1** | 9 | 0 |  0.0% | [ 0.0%, 29.9%] | 0.059 |
| **E2** | 9 | 0 |  0.0% | [ 0.0%, 29.9%] | 0.074 |

**Neither E1 nor E2 improved over N.** Both collapsed avg_score. CIs overlap so descent isn't conclusive at n=9, but the direction is consistent across two independent interventions on the same hypothesis.

## Failure-mode breakdown

| mode | N | E1 | E2 |
|---|---|---|---|
| starved | 4 | 3 | 1 |
| killed_by_monster | 4 | 6 | **8** |
| **stuck_no_progress** | **0** | **0** | **0** |
| turn_budget | 0 | 0 | 0 |
| door_block | 0 | 0 | 0 |

Two takeaways:

1. **`stuck_no_progress` is 0/27.** The wave-3 brainstorming reports converged on false-frontier oscillation as the dominant failure. The instrument says otherwise — agents die long before they have time to loop. *The diagnosis was wrong at this seed/budget/model.*

2. **Surfacing frontiers monotonically increases deaths-by-monster** (4 → 6 → 8 from N → E1 → E2). Both variants explicitly point the agent at frontier coordinates / frontier tiles, and the agent walks into more monster encounters as a result. The wedge isn't "where to explore" — it's "what to do when you get there." E2 lost N's only descent (seed 24) to a monster.

## Implications for wave-3

- The eval instrument (Wilson CIs + rule-based failure taxonomy) is working — interpretable answers in one pass.
- The brainstorming diagnosis (frontier wedge) should be deprioritized until we see `stuck_no_progress > 0` on a different model/budget.
- The real target is **survival**: `pray` / `engrave_elbereth` triggering, food economy, monster-avoidance routing. Worth examining whether the NetPlay skill set even surfaces a "retreat when low HP" path the model takes.
- The E2 paint mechanic remains a candidate for the *long-horizon* setting (deeper dungeons, where coordination matters), but at dlvl-1 with this model it's pure pressure on the wrong axis.

## Files

- `compare_N_vs_E1.md`, `compare_N_vs_E2.md` — instrument outputs.
- `N_combined.json`, `E1_combined.json`, `E2_combined.json` — combined sample dumps.
- Per-seed raw dumps: `{variant}_seed{N}_{eval_id}.json`.
