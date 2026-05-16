# Claude Haiku 4.5 vs Qwen3.5-9B on v0.0.24

Same env, same tier (corridor_explore), same wallclock cap, same prompt
(strategy primer + skill cheat-sheet). Different model, very different cost.

## Numbers

| metric | Qwen3.5-9B | Claude Haiku 4.5 | Δ |
|--------|-----------:|-----------------:|--:|
| scout_reward | **0.132** | 0.077 | -42% |
| descent_reward | 0 | 0 | — |
| num_turns | 183 | **201** | +10% |
| total_tool_calls | 183 | 201 | +10% |
| autoexplore_calls | **47** | 17 | -64% |
| move_calls | 77 | (no count surfaced) | — |
| recall_calls | 0 | 1 | +1 |
| wiki_search_calls | 0 | 1 | +1 |
| pin_objective_calls | 1 | 1 | — |
| input_tokens | 4.27M | 5.61M | +31% |
| output_tokens | 31K | 22K | -29% |
| **estimated cost** | **$0.79** | **$5.72** | **+624%** |

## Surprise: Haiku scored LOWER per dollar

Hypotheses for why:
1. **Haiku is more deliberate.** 17 autoexplore calls vs Qwen's 47 — Haiku
   spends more turns on "thinking" and less on raw movement. The
   `corridor_explore` tier rewards tile coverage; Haiku's strategy didn't
   maximize that.
2. **Haiku used the wiki + recall.** Qwen had 0 calls to either; Haiku had
   1 of each. Those are zero-reward turns on `corridor_explore` (the
   wiki content isn't on the critical path). Maybe useful on harder tiers.
3. **Pricing is the kicker.** Haiku at $1/Mtok input is 5.5× Qwen's $0.18.
   Even matching reward would be 5.5× worse $/reward. Haiku at lower
   reward + higher tokens is ~10× worse.

## What this means for the v0.1 training plan

For pure exploration/short-horizon tiers, **Qwen3.5-9B is the better
$/reward option** by an order of magnitude. Haiku may pull ahead on
longer-horizon tiers (`mines_to_minetown`, `quest_complete`, `dynamic_subgoal`)
where strategic reasoning beats raw turn count — but we'd need more
budget to test that hypothesis.

For Monday, the lesson is: **don't assume bigger/stronger = better on
NetHack**. The substrate is now a real testbed for that comparison.

## Total Day-4 eval spend

| eval | model | env | cost |
|------|-------|-----|-----:|
| 1 | Qwen3.5-9B v0.0.14, skill mode | v0.0.14 | $0.79 |
| 2 | Qwen3.5-9B v0.0.14, "code mode" (was actually skill — -x bug) | v0.0.14 | $0.79 |
| 3 | Qwen3.5-4B diagnostic | v0.0.14 | $0.05 |
| 4 | Qwen3.5-9B code+dynamic_subgoal (correct -a) | v0.0.14 | $0.59 |
| 5 | qwen3.5-35b-a3b | v0.0.14 | $1.46 |
| 6 | Qwen3.5-9B v0.0.16 reward-fix validation | v0.0.16 | $0.71 |
| 7 | Qwen3.5-9B v0.0.24 100-turn apples-to-apples | v0.0.24 | $0.79 |
| 8 | Claude Haiku 4.5 v0.0.24 | v0.0.24 | **$5.72** |
| **total** | | | **~$10.90** |

Well under the $20 per-run cap.
