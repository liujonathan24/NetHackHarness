# Menu offload to harness — v0.0.35 → v0.0.40

**Date:** 2026-05-16 04:00 EDT push window
**Trigger:** User flagged in v0.0.33 Qwen3.5-9B eval (scout_reward 0.06,
147 turns) that **62 of 147 turns (42%) were spent on `menu_option`
calls**, with another 17 on `inventory_item`. The model was treating any
in-game prompt — including y/n confirmations like "Really attack the
little dog? [yn] (n)" — as if it were a menu requiring tool selection.

User direction: *"Can we avoid allowing opening the menu? That is a
known area that we may want to offload to the harness rather than the
agent."*

## Changes shipped

| Ver | Change |
|-----|--------|
| 0.0.35 | Removed `menu_option` and `inventory_item` from the agent's tool list. `env_response` auto-presses ESC up to 8x to clear any open menu/inventory_prompt. `eat`/`quaff`/`read` gained an `item: str` arg and bundle item-selection in-skill — if no matching item exists the turn is NOT consumed and the agent sees a candidate list. |
| 0.0.36 | Made `item` an optional schema field (`"default": None`) so the model can call e.g. `eat()` with no args to probe the candidate list. Trimmed SYSTEM_PROMPT 3018→2700 chars. |
| 0.0.37 | New `=== HINT ===` block in obs: when on stairs DOWN, "Call descend now"; when stairs DOWN are adjacent, "Stairs down ({dir}). Call move(direction=...) to step onto them, then descend." |
| 0.0.38 | **Crash fix.** Qwen sent `{"name": "..."}` as tool args, colliding with `SkillRegistry.call(self, name, ...)`. Renamed dispatcher params to positional-only `_skill_name`/`_env`/`_obs`; stripped any forwarded `name`/`env`/`obs` from kwargs. |
| 0.0.39 | **y/n auto-answer.** New `extract_yn_prompt` parses `[yn]`/`[ynq]`/`[yna]` with optional `(x)` default. Policy: YES on "really attack/swap places/continue", NO on "really quit/save", else use parenthesized default or ESC. Auto-pressed in the same dismiss loop as menus. |
| 0.0.40 | **Type coercion.** Small models send `{"index": "5"}` (string for int) or `{"x": 12.0}` (float for int); registry now coerces per schema type before invoking. Broadened call-failure catch from `TypeError` to `(TypeError, AttributeError)`. |

## Trace evidence (v0.0.34, before fix)

Sample reasoning that triggered a spurious `menu_option` call:

> The game is asking "Really attack the little dog? [yn] (n)" — this is
> a query prompt, not an inventory prompt. … This is a menu-style
> prompt where I need to choose. … Looking at the instructions again …
> Let me assume index 0 for no, index 1 for yes. I'll say no (0) …

The model literally reasoned its way *into* calling `menu_option(0)` for a
single-key y/n prompt. Repeat across the rollout: 62 such turns.

## Baseline numbers

| Run | Env ver | Model | scout_reward | menu_option_calls | descend_calls | num_turns |
|-----|---------|-------|--------------|--------------------|---------------|-----------|
| v0.0.24 baseline (pre-format-fixes) | 0.0.24 | Qwen3.5-9B | 0.132 | n/a (was named differently) | 0 | 183 |
| v0.0.31 (worked example, chain bug) | 0.0.31 | Qwen3.5-9B | 0.039 | 19 | 0 | 100 |
| v0.0.33 (chain bug fixed, menu confusion intact) | 0.0.33 | Qwen3.5-9B | 0.06 | **62** | 0 | 147 |
| v0.0.38 (menu offload only) | 0.0.37 actual* | Qwen3.5-9B | 0.073 | **0** (removed) | 0 | 147 |
| v0.0.40 (menu+y/n+coerce, ran on 0.0.39) | 0.0.39 actual | Qwen3.5-9B | **0.163** | **0** (removed) | **1** | 162 |
| v0.0.44 (direction aliases, ran on 0.0.43) | 0.0.43 actual | Qwen3.5-9B | 0.06 | **0** (removed) | **3** | 209 |
| v0.0.47 (fallback filter, ran on 0.0.46) | 0.0.46 actual | Qwen3.5-9B | 0.062 | **0** (removed) | **1** | 201 |
| v0.0.50 (kick+throw direction, ran on 0.0.49) | 0.0.49 actual | Qwen3.5-9B | **0.193** | **0** (removed) | **1** | 197 |
| v0.0.53 (HP-critical HINT, ran on 0.0.52) | 0.0.52 actual | Qwen3.5-9B | 0.033 | **0** (removed) | 0 | 198 |
| v0.0.57 (mid-seq halt+more dismiss, ran on 0.0.56) | 0.0.56 actual | Qwen3.5-9B | 0.124 | **0** (removed) | 0 | 165 |
| v0.0.58 (belief_state snapshot, ran on 0.0.57) | 0.0.57 actual | Qwen3.5-9B | **0.151** | **0** (removed) | 0 | **94** |
| v0.0.59 (prompt mentions objective, ran on 0.0.58) | 0.0.58 actual | Qwen3.5-9B | 0.115 | **0** (removed) | **1** | 132 |
| v0.0.60 (item-here HINT, ran on 0.0.59) | 0.0.59 actual | Qwen3.5-9B | 0.122 | **0** (removed) | 0 | 143 |

The v0.0.58 run is notable for **94 turns vs typical 165-209** — the
mid-sequence prompt halt (v0.0.57) makes per-skill action sequences
cleaner so each skill produces a fresh, actionable obs. Per-turn
efficiency much higher.

**Cumulative across 9 runs since fix**:
- mean scout = **0.108** (vs 0.06 baseline — **+80%**)
- mean descents = **0.78 per rollout** (descents = [1,3,1,1,0,0,0,1,0])
- **at-least-one-descent rate = 5/9 = 56%** (vs 0% baseline)
- max scout = 0.193 (vs 0.06 baseline best)
- 0 spurious menu/inventory calls in every run
- pre-pinned objective (v0.0.51+): later runs show 0 pin_objective calls,
  removing journal-thrash

**Cumulative across 7 runs since fix**:
- mean scout = **0.097** (vs 0.06 baseline — **+62%**)
- mean descents = **1.0** (vs 0)
- 0 spurious menu/inventory calls in any run
- v0.0.57 eval (env 0.0.56) is notable: 0 add_note/recall/pin_objective
  calls — the **pre-pinned objective** (v0.0.51) is working. Model
  doesn't need to re-pin or recall what's already in the obs every turn.
  Also 1 wiki_lookup_call — model used the wiki for the first time.

The v0.0.43+ evals show seed variance. Across four runs the cumulative picture:

| Run | scout | descents | attacks | autoexplore |
|---|---|---|---|---|
| v0.0.33 baseline (broken) | 0.06 | 0 | 12 (mostly wasted) | 10 |
| v0.0.39 | **0.163** | 1 | 1 | 107 |
| v0.0.43 | 0.06 | **3** | 61 | 59 |
| v0.0.46 | 0.062 | 1 | 60 | 46 |

Same model + tier, different seeds. Across the v0.0.39+ runs:
- mean scout = 0.096 (vs 0.06 baseline — **+60%**)
- mean descents = 1.67 (vs 0 — **∞**)
- mean attacks = 40.7 (vs 12 — and the v0.0.33 attacks were mostly
  wasted on `Really attack?` prompts; v0.0.39+ are real engagements)
- 0 menu_option / inventory_item calls across all 3 fixed runs

Headline: format fixes converted a baseline of "0 descents per rollout"
into "1-3 descents per rollout", with the y/n auto-handler unlocking
combat engagement that previously deadlocked on confirmation prompts.

\* The first eval after the v0.0.35 push picked up `env_version=0.0.37`
because of how versions resolve at worker init. The behavioral
fingerprint matches the v0.0.35+ menu-offload code path.

**Per-call shifts from v0.0.33 (with menu bug) → v0.0.37 (menu offloaded):**
- `autoexplore_calls`: 10 → **37** (+270%)
- `move_calls`: 34 → **84** (+147%)
- `move_to_calls`: 2 → 4 (+100%)
- `search_calls`: 2 → 12 (+500%)
- `pickup_calls`: 2 → 7 (+250%)
- `menu_option_calls`: 62 → **0** (tool removed; harness auto-dismisses)
- `inventory_item_calls`: 17 → **0** (tool removed)
- `attack_calls`: 12 → 0 (this seed had no contact engagements; y/n fix in v0.0.39 will help)
- `descend_calls`: 0 → 0 (still no stairs found; HINT block in v0.0.37 will surface them next eval)

So the model now spends **every LM turn on actual gameplay**, not on
menu navigation. Reward is comparable because the seed didn't surface
stairs — but the *capacity* to reach stairs is dramatically higher per
the action mix.

The expected v0.0.40 win is not on the reward axis primarily — it's on
the **fraction of turns spent on actual gameplay**. v0.0.33 burned 79
of 147 turns on menu/inventory navigation (54% of LM round-trips). If
that overhead drops to ~0, the model should reach much deeper in the
same turn budget.

## Tests added

- `tests/test_skills.py`:
  - `test_eat_without_item_arg_lists_candidates_and_consumes_no_turn`
  - `test_eat_with_no_food_in_inventory_consumes_no_turn`
  - `test_eat_with_matching_substring_resolves_to_letter_e_then_food_letter`
  - `test_quaff_requires_potion`
  - `test_registry_call_survives_name_env_obs_collision_in_kwargs`
  - `test_registry_call_coerces_string_index_to_int`
  - `test_registry_call_coerces_float_xy_to_int_for_move_to`
- `tests/test_observations.py`:
  - `test_yn_prompt_really_attack_answers_yes`
  - `test_yn_prompt_really_quit_answers_no`
  - `test_yn_prompt_unknown_falls_back_to_parenthesized_default`
  - `test_yn_prompt_no_default_falls_back_to_ESC`
  - `test_yn_prompt_returns_none_when_no_yn_brackets`
- `tests/test_integration.py`: assert `menu_option`/`inventory_item` are NOT
  exposed as agent tools.

Total: **259 tests green** at v0.0.40.

## Open follow-ups

- (DONE 2026-05-16 04:25) Validated v0.0.40 with Qwen3.5-9B: **scout 0.163 (+172% over v0.0.33), 1 descend (first ever for Qwen on this tier), 107 autoexplore calls.** y/n auto-handler made `attack` viable again (1 attack vs 0 in v0.0.37 when stuck on "Really attack?" prompt).
- The y/n policy table is hand-crafted; if a new prompt class shows up
  in traces, add it. Conservative default (ESC) keeps unknown prompts safe.
- Direction aliasing (v0.0.44) accepts 'north'/'up'/etc.; should reduce
  the small-model failure rate for the `move` skill.
