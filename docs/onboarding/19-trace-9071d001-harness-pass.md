# Trace 9071d001: harness pass (2026-05-16 morning)

## Source trace

`environments/nethack/outputs/evals/nethack--Qwen--Qwen3.5-9B/9071d001/`
— Qwen3.5-9B on `corridor_explore`, scout=0.122, descend=0, num_turns=143,
max_turns=100. The agent never reached dlvl 2 despite 66 autoexplore calls.

## Issues found in the trace

Twelve distinct failure modes surfaced by reading the full chat history
plus reasoning_content for every assistant turn.

| # | Issue | Evidence | Fix | Test |
|---|---|---|---|---|
| 1 | After 2nd compaction pass, `[Moved S.]` / `[Picked up]` audit-log markers are stripped — model loses memory of which actions worked | Compacted msgs at distance 7+ contained only `[turn -X] HP: 14/14 ...`, no action verbs | `_one_line_summary` `looks_compacted` branch now re-extracts the bracketed feedback + HP from previously-compacted content | `test_action_feedback_survives_repeated_compaction` |
| 2 | 90 user msgs identical to `[turn -X] HP: 14/14 AC: 4 Dlvl: 1 Turn: T XP: 1 $: 0` — pure token noise | `_compacted_status_signature` analysis: same HP/AC/Dlvl across 90 turns | New `_dedupe_compacted_runs` collapses consecutive identical signatures to `[turn -Y] (unchanged)` | `test_consecutive_unchanged_status_runs_get_collapsed`, `test_status_change_breaks_unchanged_run` |
| 3 | 7-long autoexplore-spam runs ignoring in-skill "short trip" tail hint | `autoexplore` called 66 times, 5/7-long consecutive | `env_response` tracks `state["consecutive_short_autoexplore"]`; ≥3 short trips emits a stronger `[autoexplore-loop: N short trips in a row...]` HINT at the top of the obs | `test_autoexplore_loop_hint_fires_after_three_short_trips`, `test_autoexplore_counter_resets_on_non_autoexplore_call` |
| 4 | Model hallucinated `f = fireplace`, `f = fountain`, `f = floor` (none real); GLYPH KEY in prompt only covered terrain | Reasoning at msgs 52/96/204 | Expanded GLYPH KEY to enumerate terrain AND state "creatures are LETTERS, not furniture; no fireplace glyph"; added Elbereth back inline | `test_system_prompt_has_strategy_primer_and_cheat_sheet` |
| 5 | Model confused `<` (stairs UP) with `>` (stairs DOWN) and never found descent stairs | Reasoning at msg 196 explicitly claimed to see `>` in map; map only had `<` | `extract_visible_features()` scans tty for `>`/`<`/`_`/`{`/`\\`/`$` and emits `=== VISIBLE FEATURES === stairs DOWN at (x,y); ...` | `test_extract_visible_features_*` (3 tests) |
| 6 | Pinned objective hidden after turn 1 by diff-only journal; history compaction wiped turn 1 | `state["_journal_fingerprint"]` caused 2nd turn onward to emit `(unchanged since last turn)` only | Journal block now always emits `Objective: ...` from pin; only notes diff out | `test_pinned_objective_persists_when_journal_otherwise_unchanged` |
| 7 | `move_to(x,y)` available but agent didn't know its own (x,y) | STATUS line never included player position | Append `Pos: (x,y)` from blstats to the STATUS line | `test_status_line_includes_player_position_when_available` |
| 8 | `move` always reported `[Moved S.]` even when blocked by wall | `(40, 6)` "stuck at a wall" reasoning, no feedback distinguishing | `env_response` captures pre/post blstats `(x,y)` around single-step `move` calls; if unchanged, overrides feedback to `[Move blocked at (x,y): wall or obstacle in <dir>. Pick a different direction or search if you suspect a hidden door.]` | `test_move_into_wall_reports_blocked_not_moved` (smoke) |
| 9 | Bare letter glyphs in ADJACENT (`W=f`) gave no class hint | Trace evidence in (4) | `_MONSTER_CLASS_HINT` table for ~32 classes; `extract_adjacent` emits `f(cat/small feline)` | `test_extract_adjacent_labels_monster_letters_with_class_hint` |
| 10 | Autoexplore-no-frontier tip was too soft ("try search") | Only 4 search calls in 100 turns | Tip now reads "Call `search` 5-10 times at adjacent walls — especially dead-end corridors — to reveal them." | (covered by skill-level docstring + manual verification) |
| 11 | "Your kitten is in the way!" message looped for 16 turns; no harness response | Reasoning at msgs 100-116 | `format_observation_as_chat` scans recent messages for `is in the way`; overrides HINT to "A pet/peaceful is blocking your move. Walk a perpendicular direction first, or `move(direction='.')` to wait." | `test_pet_blocking_message_triggers_go_around_hint` |
| 12 | `attack` returned `Moved W.` regardless of hit/miss/kill | trace contained 35 attack calls; outcome invisible due to compaction-shaded feedback | `env_response` parses NLE message buffer for `you kill/hit/miss/no monster` patterns when `skill_name == "attack"`; overrides `SkillResult.feedback` to `Killed: X` / `Hit: X` / `Missed: X` / `No target: X` | (manual verification — feedback path is straight-line) |

## Compaction baseline justification (outstanding)

Per user direction 2026-05-16: *"Prior to using compacting, we have to
show that the non-compacted ones can do the task but are more expensive.
Then, we try to match the non-compacted baseline with a compacted version.
We always need this justification."*

A `compact_obs=False, history_keep_full=99999` eval is in flight under
`experiments/results/no_compact_short/`. Result writeup template at
`experiments/results/compaction_baseline_vs_v0060.md`.

## What didn't change

- The reward functions, the curriculum tier specs, the wiki snapshot, and
  the skill registry interfaces are all unchanged. Pure observation-layer
  + env_response feedback improvements.
- No tool was added or removed. The agent sees the same 18-tool list it
  did before.
- Token budget impact: net-positive. Fixes 1+2 SHRINK average compacted-
  turn payload; fixes 5+7+9+11+12 add ~40-60 tokens per turn for the new
  blocks/hints. Most rollouts spend >>100 turns in compacted state so
  the savings dominate.

## Tools

`tools/trace_analyze.py` — static failure-mode summary for any results.jsonl.
Usage: `python tools/trace_analyze.py path/to/results.jsonl`. Reports:

- Tool call distribution and consecutive-same-tool runs ≥ 5 (catches autoexplore-spam)
- Reasoning length percentiles (catches over-deliberation)
- Stuck-keyword hits in reasoning ("stuck", "looping", "no path", etc.)
- Glyph-name hallucinations ("fireplace", "fountain (f)", "floor (f)")
- Compacted-only vs action-bracketed user-message counts (compaction coverage)
- Counts of harness HINT firings: `Move blocked`, `autoexplore-loop`, `pet blocking`
  hint, `VISIBLE FEATURES` block appearances, `(unchanged)` status collapses

Useful as a per-trace triage and a regression diff across eval versions.

## Followups

- Re-run the A/B once the no-compact baseline lands.
- Push v0.0.61 to the Hub once locally verified.
- The model still used `wiki_lookup`/`wiki_search` 0 times in the trace.
  The wiki snapshot has 102 mostly-monster pages — no `search` or `stairs`
  page. Either add general-tactics pages or surface specific wiki calls
  from HINTs when a known monster glyph appears.
