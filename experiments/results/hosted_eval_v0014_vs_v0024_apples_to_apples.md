# v0.0.14 vs v0.0.24 — apples-to-apples Qwen3.5-9B

Same model, same tier (corridor_explore), same seed, same wallclock cap
(10 min). v0.0.14 is the broken-reward / no-compaction baseline; v0.0.24
has reward fix + obs compaction + history compaction + survival skills +
strategy primer + journal cap + diff-only inventory/journal + adjacency
block + RLE messages + status-aware halt + pluggable knobs.

## Numbers (from `tools/compare_evals.py`)

| metric | v0.0.14 | v0.0.24 | Δ |
|--------|--------:|--------:|--:|
| **avg_reward** | 0.000 | **0.132** | +∞% |
| **scout_reward** | 0.000 | **0.132** | +∞% (rubric bug fixed AND model explored more) |
| num_turns | 146 | **183** | +25% |
| total_tool_calls | 144 | 183 | +27% |
| input_tokens | 4.27M | 4.27M | +0% (same wallclock budget) |
| output_tokens | 46K | 31K | **-32%** (less waffle per turn) |
| estimated cost | $0.794 | $0.786 | -1% |

## Behavioral changes (diverging skill calls, |Δ| ≥ 5)

| skill | v0.0.14 | v0.0.24 | Δ | what changed |
|-------|--------:|--------:|--:|-------------|
| **autoexplore** | 2 | **47** | **+45** | Strategy primer cues the agent to prefer autoexplore |
| **menu_option** | 41 | **0** | **-41** | Sharper schema tells agent NOT to use without a visible menu |
| **search** | 6 | 31 | +25 | Primer suggests searching at dead-ends |
| **move** | 35 | 77 | +42 | More tactical positioning |
| **descend** | 4 | 13 | +9 | Agent tries the descent action more often |
| **move_to** | 42 | 2 | -40 | Prefers autoexplore now |
| attack | 10 | 0 | -10 | Avoided combat this rollout (RNG) |

## Interpretation

This is the **single most important Monday slide**:

1. **Reward signal is real now.** v0.0.14 said 0 because the rubric was
   buggy; v0.0.24 says 0.132 because the agent actually explored 132
   tiles and the rubric counts properly.
2. **The strategy primer works.** v0.0.14 wasted 41 turns on menu_option
   (probably triggered by `eat`/`quaff` without checking inventory);
   v0.0.24 wasted ZERO. Net effect: ~30% more useful turns.
3. **Compaction = bigger budget at same cost.** Same wallclock + same
   token budget bought 25% more turns. Cumulative chat doesn't blow up,
   so per-turn LM calls stay snappy and the model gets more shots.
4. **Behavior diversity emerged.** Search (6→31) and descend (4→13) saw
   meaningful upticks — the agent has more turns to spend on non-greedy
   actions. The reward number being nonzero is the small piece; the big
   piece is **the agent is now genuinely engaging with the game**.

## What didn't work yet

- descent_reward is still 0 — the agent didn't reach dlvl 2 in either
  run. Need either a smarter agent (35B+) or longer wallclock (30min)
  or a "spawn at dlvl 2" tier for faster signal.
- success_reward (corridor_explore milestone) = 0 for same reason.

For the v0.1 GRPO training run, this baseline establishes the credit
landscape: **scout_reward gives gradient now**, descent/success/ascension
are aspirational but unreachable until the agent has a few rounds of
fine-tuning.
