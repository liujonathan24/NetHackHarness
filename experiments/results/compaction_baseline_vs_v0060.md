# History compaction: baseline justification

**Question:** Does the agent need history compaction? Can the *uncompacted*
harness do the task at all, and does the compacted version match it on
reward while cutting cost?

**User direction (2026-05-16):** "Prior to using compacting, we have to
show that the non-compacted ones can do the task but are more expensive.
Then, we try to match the non-compacted baseline with a compacted version.
We always need this justification."

## Setup

| | A: no compaction | B: current (v0.0.60, defaults) |
|---|---|---|
| `compact_obs` | False | True |
| `history_keep_full` | 99999 | 5 |
| `history_drop_after` | 99999 | 100 |
| Model | Qwen/Qwen3.5-9B | Qwen/Qwen3.5-9B |
| Tier | corridor_explore | corridor_explore |
| Seed | 0 (n_examples=1) | 0 (n_examples=1) |
| max_turns | 100 | 100 |
| Temp / max_tokens | 0.6 / 2048 | 0.6 / 2048 |

Note: configuration A is `compact_obs=False` with `history_keep_full` and
`history_drop_after` set so high that no compaction OR drops ever fire.
Per-turn obs gets the full untrimmed tty grid; every prior turn keeps
its full content in chat history.

## Numbers

| metric | A (uncompacted) | B (compacted, v0.0.60 9071d001) |
|---|---|---|
| scout_reward | TBD | 0.122 |
| descend_calls | TBD | 0 |
| num_turns | TBD | 143 |
| input_tokens (cumulative) | TBD | 1.30M |
| output_tokens | TBD | 25.9K |
| wallclock | TBD | 10 min |
| autoexplore_calls | TBD | 66 |
| menu_option_calls | 0 (tool removed) | 0 |

## Interpretation

(populated once the A run completes)

## What this justifies

If A reaches the same scout/descend numbers as B but pays >2× input tokens,
compaction is justified as a pure cost-saver with no quality loss. If A
beats B, we know the compaction is over-aggressive — and the per-turn
fixes already shipped (action-feedback preservation, status-run dedupe,
identical-status collapse) are the right direction. If A loses to B, that
also justifies compaction — a leaner context window helps small models.

## Followups regardless of result

- The compaction fixes shipped 2026-05-16 (commits ce0a464..1699cfb)
  shrink per-compacted-turn payload by ~50% AND preserve the action
  audit-log. We need to re-run A vs B-current to give compaction a fair
  apples-to-apples test.
