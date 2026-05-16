# Format fixes — Haiku 4.5 before/after on v0.0.30

The user reviewed the 200-turn Haiku trace and flagged format confusion as
the blocker. After shipping the trace-driven fixes (UNDER PLAYER block,
GLYPH KEY in system prompt, ADJACENT stair labels, descend short-circuit),
re-ran the same model on the same tier.

## Headline

**scout_reward 0.077 → 0.163 (+112%)** same model, same tier, comparable
cost. The format fixes alone more than doubled exploration credit.

descent_reward is still 0 (Haiku didn't reach dlvl 2) but the dramatic
shift in tool-use behavior shows the model is no longer wasting turns on
the failed-descend loop.

## Numbers

| metric | v0.0.24 (broken format) | v0.0.30 (UNDER PLAYER + glyph key) | Δ |
|--------|------------------------:|------------------------------------:|--:|
| scout_reward | 0.077 | **0.163** | **+112%** |
| descent_reward | 0 | 0 | — |
| num_turns | 201 | 172 | -14% |
| total_tool_calls | 201 | 172 | -14% |
| **descend_calls** | (many wasted) | **1** | -99%-ish |
| autoexplore_calls | 17 | 10 | -7 |
| move_calls | (mid) | 160 | +many |
| menu_option_calls | 0 | 0 | — |
| input_tokens | 5.61M | 5.08M | -9% |
| output_tokens | 22K | 25K | +14% |
| estimated cost | $5.72 | $5.21 | -9% |

## Behavioral interpretation

- **`descend_calls = 1`** is the headline. Previously Haiku spent ~150
  turns trying to descend off non-stairs tiles, each attempt wasting an
  in-game turn AND triggering the wrong move logic. With `UNDER PLAYER`
  and the friendlier `descend` feedback, Haiku now respects the
  precondition and only calls descend when it thinks the conditions
  are right.
- **Many more move calls (160 vs ~middling)** mean Haiku is navigating
  with confidence — it knows what's adjacent and acts on it.
- **scout_reward went up despite fewer turns**. The model is making
  every turn count instead of bouncing off the descend-off-stairs trap.

## Why descent_reward still 0

Even with the fixes, 172 turns × Haiku4.5 isn't sufficient to actually
land on a `>` tile, verify, descend. NetHack levels are big and stairs
can be far from spawn. v0.0.31 adds an explicit worked example to the
system prompt walking through the descent loop step by step — next eval
will test whether that pushes descent_reward > 0.

## What's next

- Run **v0.0.32 eval with the worked-example prompt**.
- If still 0 descent: experiment with `mini_dungeon` tier (dlvl 3 cap)
  with more max_turns budget.
- Long-term: real fine-tuning will be required to actually descend
  consistently. The format work removes the "got stuck on UI ambiguity"
  failure mode; reaching dlvl 2 reliably still needs an RL loop.

## Cost summary

Total Haiku spend so far: ~$5.72 (v0.0.24) + $5.21 (v0.0.30) ≈ $10.93.
All Day-4 evals combined: ~$16. Still under $20 per-run cap.
