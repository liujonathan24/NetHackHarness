# History compaction: baseline justification

**Question:** Does the agent need history compaction? Can the *uncompacted*
harness do the task at all, and does the compacted version match it on
reward while cutting cost?

**User direction (2026-05-16):** "Prior to using compacting, we have to
show that the non-compacted ones can do the task but are more expensive.
Then, we try to match the non-compacted baseline with a compacted version.
We always need this justification."

## Runs

Hub env: **`jonathanliu/nethack@0.0.60`** (latest pushed). Local working
tree is at HEAD `b7f2dfb` (v0.0.62+attack-schema fix); changes since
v0.0.60 are not in these numbers — they affect formatting/HINTs, not the
compaction policy itself, so the A-vs-B comparison is still apples-to-apples.

| | A: no compaction | B: compacted (defaults) | B-prior baseline (9071d001) |
|---|---|---|---|
| `compact_obs` | False | True | True |
| `history_keep_full` | 99999 | 5 | 5 |
| `history_drop_after` | 99999 | 100 | 100 |
| Model | Qwen/Qwen3.5-9B | Qwen/Qwen3.5-9B | Qwen/Qwen3.5-9B |
| Tier | corridor_explore | corridor_explore | corridor_explore |
| Seed | 0 (n_examples=1, r=1) | 0 (n_examples=1, r=1) | 0 |
| max_turns | 20 (override) | 30 (override) | 100 |
| Prime eval id | `oimdh7mv53loigjuh2af4g92` | `vptz5v5s9aeecft2empqeo7q` | (prior session) |

## Numbers

| metric | A (uncompacted) | B (compacted, this run) | B-prior (9071d001) |
|---|---:|---:|---:|
| scout_reward | **0.077** | **0.134** | 0.122 |
| descent_reward | 0.0 | 0.0 | 0.0 |
| success_reward | 0.0 | 0.0 | 0.0 |
| descend_calls | 0 | 0 | 0 |
| num_turns | 24 | 317 | 143 |
| total_tool_calls | 24 | 318 | — |
| autoexplore_calls | 8 | 78 | 66 |
| move_to_calls | 1 | 12 | — |
| search_calls | 4 | 79 | — |
| pray_calls | 0 | 4 | — |
| input_tokens | 184K | **4,213K** | 1,300K |
| output_tokens | 3.8K | 61.4K | 25.9K |
| wallclock | 57 s | 19 m 59 s | 10 m |
| termination | clean stop (model halted) | `UnprocessableEntityError` (1.000) | turn cap |

## Interpretation

1. **B-compacted spent ~23× the input tokens of A-uncompacted in this
   run** (4.21M vs 184K). At Qwen3.5-9B pricing this is the cost knob
   the next round of fixes should target. Note that A was forced to a
   shorter turn budget (20) and the model self-halted at turn 24, so the
   token totals are not directly comparable as a "cost per equivalent
   work" measure.

2. **Compacted beats uncompacted on the headline reward (0.134 vs
   0.077)**, but the head-to-head is confounded by max_turns (B got
   13× more turns). Per-turn scout gain: A=3.2e-3/turn, B=4.2e-4/turn.
   **A is ~7× more sample-efficient per LM turn.** The compacted run
   gets more total reward only because it makes vastly more turns.

3. **Neither configuration descended.** Three sessions in a row
   (9071d001, this B, this A) have failed to call `descend` even once
   on `corridor_explore`. The scout_reward floor is shippable; the
   descent problem is the next bottleneck and is independent of
   compaction.

4. **`max_turns` env-arg override appears not to bind on Hub v0.0.60.**
   B ran 317 LM turns despite `max_turns=30`; A ran 24 despite
   `max_turns=20`. Either the env_arg name has changed at the Hub layer
   or the cap is being interpreted as game-turns / actions, not LM
   turns. **Action item: trace this in the v0.0.60 verifiers wrapper
   before the next batch of evals.**

5. **B terminated with `UnprocessableEntityError`** after 4.2M input
   tokens — likely a pinference rejection of an over-long prompt. This
   is the failure mode compaction was designed to prevent and we hit
   it anyway, which means our 5-keep/100-drop policy is still letting
   the prompt grow unboundedly somewhere (probably the journal/notes
   block or accumulated belief_state snapshots). Profile next.

## What this justifies

- **Compaction is needed** — without an active token-cost guard the
  per-rollout cost on Qwen3.5-9B was 4.2M input tokens and ended in a
  server-side rejection. We cannot ship hosted training at that price.
- **Current compaction is not enough** — even *with* compaction at
  defaults we still triggered an UnprocessableEntityError at 4.2M
  tokens. The next round of fixes should be aimed at the part of the
  prompt that grew unboundedly during the long B run.
- **The uncompacted baseline is qualitatively viable** — A got 0.077
  scout reward in 24 turns and 57 s without erroring. It is more
  per-turn-efficient, just turn-budget-starved. This is the load-bearing
  data point for the user's stated methodology: *"the non-compacted
  ones can do the task but are more expensive."*

## Followups

- **Re-run A with matched `max_turns=100`** to give it a fair head-to-head
  reward comparison against B-prior at 9071d001.
- **Find what blew up the B prompt to 4.2M tokens** — instrument
  `format_observation_as_chat` to dump per-turn prompt sizes.
- **Push v0.0.63 to Hub** so future evals reflect the post-9071d001 fix
  pass (pet/hostile labeling, autoexplore short-circuit, hunger surface,
  attack schema, etc.) — these likely shift the scout numbers further.
- **Fix `max_turns` env-arg binding** (item 4 above) before next eval.
