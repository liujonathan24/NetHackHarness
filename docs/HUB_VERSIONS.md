# Hub version history (jonathanliu/nethack)

Reference for what changed between Hub releases. Each row is a
`prime env push`. Fixes flow chronologically; each version tested on
the Hub before the next push.

## Index of the load-bearing versions

- **0.0.16** — Reward bugfix (scout/descent returned 0 before).
- **0.0.17–24** — Token compaction (obs run-length, history compaction,
  inventory diff, journal cap). Cumulative prompt 89.8% smaller.
- **0.0.30–34** — Trace-driven format fixes from Haiku trace
  (UNDER PLAYER, GLYPH KEY, ADJACENT stair labels, descend short-circuit,
  chain-accumulation fix).
- **0.0.35–58** — Menu offload + format harness work from Qwen trace
  (`menu_option`/`inventory_item` removed; auto-dismiss menus + y/n +
  `--More--`; `eat`/`quaff`/`read` take `item`; `kick`/`throw` take
  `direction`; HINT block with HP-critical override; type coercion;
  direction aliases; pre-pinned objective; recall finds objective;
  belief_state snapshots; mid-sequence prompt halt). **Validation**:
  Qwen3.5-9B scout 0.06→0.193 (best), 0→3 descents per rollout, 0
  spurious menu calls.

| Ver | Why pushed | Result | Time |
|-----|-----------|--------|------|
| 0.0.0 | Reset baseline (0.0.2/3/4 deleted) — clean version sequence | ✓ Hub tests green | 20:45 EDT |
| 0.0.1 | + verifiers compat shim for `message_from_response` | ✗ shim assumed attribute exists; failed import | 21:39 |
| 0.0.2 | Made shim defensive (no-op when attr missing) | ✓ green; vf-eval still failed (different bug) | 21:49 |
| 0.0.3 | Default tier `solo_combat`→`corridor_explore`, friendly MiniHack-missing error | ✓ green; vf-eval failed: `ToolCall.function` missing | 21:59 |
| 0.0.4 | Handle flat `ToolCall.name` (not `.function.name`) | ✓ green; vf-eval failed: raw-dict messages | 23:03 |
| 0.0.5 | Return `vf.UserMessage(...)` not `dict` | ✓ green; vf-eval failed: tuple-vs-list return | 23:06 |
| 0.0.6 | env_response returns just messages, not `(messages, state)` | ✓ green; vf-eval failed: 0.8B model malformed args | 23:21 |
| 0.0.7 | SkillRegistry filters unknown kwargs, surfaces feedback | ✓ green; **vf-eval ran successfully** (no errors, real rollouts) | 23:34 |
| 0.0.8 | Track B wired: `interface="code"`, `nh.move/autoexplore/etc` queue actions | ✓ green | 00:08 next-day |
| 0.0.9 | Sub-LM API (`nh.summarize/plan/recall_lm` + `OfflineSubLM` backend) | ✓ green | 21:13 |
| 0.0.10 | Dynamic-subgoal tier + `subgoals.py` + `OfflineSubgoalProposer` | ✓ green | 21:17 |
| 0.0.11 | Belief-state distillation hook (auto-summarize on level transition) | ✓ green | 21:21 |
| 0.0.12 | Dispatcher hardening: empty / non-JSON / list args coerce to `{}` | ✓ green | 21:28 |
| 0.0.13 | Pluggable `sub_lm` / `subgoal_proposer` via `load_environment` | ✓ green | 21:34 |
| 0.0.14 | 7 survival skills: eat/quaff/read/pray/engrave_elbereth/kick/throw | ✓ green; first end-to-end hosted eval successes | 21:44 |
| 0.0.15 | Status-aware halt for multi-action skills (HP-drop / hunger) | ✓ green | 21:56 |
| 0.0.16 | **Reward bugfix**: scout_reward / descent_reward return running totals (was: last-step delta — always 0 at score time). System-prompt strategy primer + skill cheat-sheet. | ✓ green | 23:00 |
| 0.0.17 | **Obs compaction**: strip blank tty rows + glyph-run encode `.{20}`/`#{N}` + inventory diff-only. Targets the 4M-input-token cost per rollout. SYSTEM_PROMPT now explains the glyph-run encoding. | ✓ green | 23:22 |
| 0.0.18 | **History compaction** via `get_prompt_messages` override: last 5 turns full, turns 6–100 one-line summaries, turns >100 dropped behind an elision marker. Survey rec #1; biggest expected token win. | (pending) | 23:31 |
| 0.0.19 | **Periodic belief state** every 25 turns via SubLM.summarize → journal note. Survey rec #3; lets history compaction drop old turns without losing semantic context. | (pending) | 23:37 |
| 0.0.20 | **Message run-length encoding**: `"You hit the kobold." (x10)`. Survey rec #5. Small win on combat-heavy turns. | (pending) | 23:40 |
| 0.0.21 | **Adjacency + visible-glyph blocks** in the obs. Saves the LM from scanning the full map for "what's next to me" and "are there monsters". | (pending) | 23:45 |
| 0.0.22 | **Journal render cap** (default 2KB). Objective + belief_state notes pinned; older arbitrary notes elided. Latent unbounded-growth bug fix. | ✓ green | 23:48 |
| 0.0.23 | **Compaction knobs** exposed via `load_environment` kwargs: `compact_obs`, `history_keep_full`, `history_drop_after`, `belief_state_interval`, `journal_render_max_chars`. A/B-testable. | (pending) | 00:00 |
| 0.0.24 | **Journal diff-only** render: emit `(unchanged since last turn)` when journal hash hasn't changed since last render. Survey rec #9. | (pending) | 00:02 |
| 0.0.25 | **bootstrap_character fallback** to tty status-line parsing when NLE preempts the welcome (calendar events e.g. new moon). Smaller-model-friendly schema descriptions for `menu_option`/`inventory_item`/`eat`. | (pending) | 00:08 |
| 0.0.26 | **BALROG progression score** wired as `state["balrog_progression"]` (informational, not in rubric). 2 new milestone-driven tiers: `quest_complete`, `castle_reached`. New `nethack_core/balrog.py` module. | (pending) | 02:05 |
| 0.0.27 | (intermediate; wiki snapshot added but wheel-include not yet updated) | (pending) | 02:11 |
| 0.0.28 | **Expanded wiki snapshot**: 30 → **102 pages** (88KB JSON). Auto-loaded by `nethack_core/wiki.py::_load_default_index()`. Hub install gets real lore by default. Wheel include + force-include for `wiki/snapshot.json`. | ✓ green | 02:13 |
| 0.0.29 | **Stair-glyph disambiguation** (from haiku trace analysis): new `=== UNDER PLAYER ===` block in every obs; SYSTEM_PROMPT GLYPH KEY callout; 21 terrain glyph descriptions. | ✓ green | 02:33 |
| 0.0.30 | **Friendlier `descend`**: short-circuits when not on `>` with "Can't descend — you're standing on: floor (.)". **Adjacency stair labels**: `=== ADJACENT === E=>(stairs DOWN)` instead of bare `E=>`. | ✓ green | 02:58 |
| 0.0.31 | **Descent worked example** in SYSTEM_PROMPT: explicit 4-step recipe for reaching dlvl 2 (autoexplore until > visible → move to adj > → verify UNDER PLAYER → descend). Targets the haiku rollout's 150 wasted descend attempts. | ✓ green | 03:07 |
| 0.0.32 | **Code-mode parity** for under_player + adjacent: `nh.under_player` and `nh.adjacent` properties exposed in the code-mode `nh` namespace, mirroring the skill-mode obs blocks. | ✓ green | 03:14 |
| 0.0.33 | **Chain-accumulation bugfix**: `_one_line_summary` was re-feeding `[turn -N]` labels as "feedback" each turn, accumulating useless chains like `[turn -92] [turn -91] ... [turn -7]`. Now idempotent: already-compacted messages get a single fresh label, preserving status line if present. Caught by user trace 2026-05-16. | (pending) | 03:27 |
| 0.0.34 | **Real `extract_under_player`**: previous implementation returned "unknown (@)" because `chars` always shows @ at the player position. Rewrote to parse NLE's message buffer for "There is a staircase X here." / "You see here Y" — fires reliably on stairs/altars/fountains/items, silent on plain floor. | (pending) | 03:35 |
| 0.0.35 | **Menus offloaded to the harness**. Removed `menu_option` and `inventory_item` from the agent's tool list (Qwen3.5-9B was spending 42% of turns on them — 62/147 turns spurious in the v0.0.33 eval). `env_response` now auto-presses ESC up to 8x to clear any open menu/inventory_prompt before yielding to the LM. `eat`/`quaff`/`read` gained an `item` arg (substring or letter) and bundle item-selection in-skill: if no matching item exists the turn is NOT consumed and the agent sees a candidate list. | (pending) | 03:58 |
| 0.0.36 | **`item` made optional in tool schema** for eat/quaff/read (`"default": None`) so the model can probe candidates by calling with no args. Also trimmed SYSTEM_PROMPT (3018→2700 chars) — consolidated menu/pitfall paragraphs to stay under the 2800-char budget. | (pending) | 04:06 |
| 0.0.37 | **`=== HINT ===` block** in the obs: if UNDER PLAYER shows stairs DOWN → "Call descend now"; else if adjacent has stairs DOWN → "Stairs down ({dir}). Call move(direction=\"{dir}\") then descend." Aims to convert "the info is there but the model didn't act" into "the action is named explicitly". | (pending) | 04:10 |
| 0.0.38 | **Dispatcher arg-collision fix**: Qwen3.5-9B crashed the v0.0.37 eval by passing `{"name": "..."}` as tool args, which collided with `SkillRegistry.call(self, name, ...)`. Renamed dispatcher params to positional-only `_skill_name`/`_env`/`_obs`, stripping any forwarded `name`/`env`/`obs` from kwargs. Regression test in `test_skills.py`. | (pending) | 04:14 |
| 0.0.39 | **y/n confirmation auto-answer.** Traces showed Qwen calling `menu_option` for "Really attack the little dog? [yn] (n)" — an in-game y/n prompt, not a real menu. New `extract_yn_prompt` parses `[yn]/[ynq]/[yna]` with optional `(x)` default; policy table auto-answers (YES on "really attack/swap places/continue"; NO on "really quit/save"; otherwise parenthesized default or ESC). env_response auto-presses y/n/ESC just like menu dismiss. 5 new tests. | (pending) | 04:22 |
| 0.0.40 | **Dispatcher type coercion + AttributeError catch.** Small models send `{"index": "5"}` (string for int) or `{"x": 12.0}` (float for int); registry now coerces per schema type before invoking the skill. Also broadened the call-failure catch from TypeError to (TypeError, AttributeError) so a malformed call surfaces friendly feedback instead of crashing the rollout. 2 new tests. | (pending) | 04:30 |
| 0.0.41 | **Autoexplore dead-end tip.** When `autoexplore` reports the level fully explored, feedback now hints next: if `>` is visible, "move_to it and descend"; otherwise "try `search` at a dead-end wall for hidden passages." Aims to break the loop where the model keeps calling autoexplore in a dead-end. | (pending) | 04:38 |
| 0.0.42 | **HINT extended to monsters.** Beyond stairs hints, the HINT block now fires when an adjacent letter glyph (monster) is detected: HP ≥ 50% → "Hostile adjacent ({dir}). Call attack(direction=...)"; HP < 50% → "low HP; consider engrave_elbereth or retreat with move." Targets the v0.0.37 trace which had 0 attack_calls — model didn't recognize hostiles as actionable. | (pending) | 04:42 |
| 0.0.43 | **HINT HP key fix**: status dict uses `max_hitpoints` (not `hitpoints_max`); HP-threshold check was always reading 1 by mistake. Trivial but mis-routed every monster hint to the "low HP" branch. | (pending) | 04:46 |
| 0.0.44 | **Direction aliasing in `move`/`attack`**: accept 'north', 'up', 'south'/'down', 'east'/'right', 'west'/'left', full lowercase compass forms ('se'), in addition to canonical 'N','NE',...,'.'. Small models reliably emit these alternatives — being strict cost a wasted turn for a cosmetic mismatch. 3 new tests. | (pending) | 04:50 |
| **VALIDATION** | **Qwen3.5-9B local eval against the v0.0.35→v0.0.40 changes**: scout_reward = **0.163** (+172% vs v0.0.33's 0.06), descend_calls = **1** (first non-zero!), autoexplore_calls = **107**, attack_calls = **1** (y/n auto-handler made attacks viable). 162 turns. See `experiments/results/menu_offload_v0035_to_v0040.md`. | n/a | 04:50 |
| 0.0.45 | **Expanded y/n policy table**: added YES on "pick up"/"see?" (auto-pickup, inventory display); NO on "abort"/"throw away" (don't destroy items). | (pending) | 04:56 |
| 0.0.46 | **autoexplore short-path tail-hint**: when path length ≤ 2 (level mostly explored), feedback now points the model at `search` / `move_to` (or `descend` if `>` visible). The v0.0.40 trace showed 50 consecutive autoexplore calls on dlvl 2 after the model descended — a loop on tiny frontiers. | (pending) | 05:00 |
| 0.0.47 | **Fallback tools-list filter**: when a model returns no tool calls, the "Available tools: ..." message now excludes `menu_option`/`inventory_item` so the model doesn't try to recover by calling a removed tool. Cosmetic; the schema already filters them. | (pending) | 05:08 |
| **VALIDATION-2** | **Qwen3.5-9B on v0.0.43 actual** (different seed): scout_reward 0.06, **descend_calls = 3**, engrave_elbereth_calls = 3, attack_calls = 61, kick_calls = 14, wiki_search = 1. Model engaged combat heavily and used Elbereth for defense — exactly the gameplay the y/n + HINT fixes targeted. 209 turns. | n/a | 05:08 |
| 0.0.48 | **STATUS line includes max-Dlvl-reached** when player is on a level shallower than their max (e.g. after going back up via `<`). Helps the model recognize "I've been deeper" so it doesn't lose track of progress. | (pending) | 05:14 |
| 0.0.49 | **y/n policy: "Really attack?" → NO**. NetHack only shows this prompt for peacefuls (e.g. pet dog). Old policy auto-answered YES (following the `attack` tool's intent), which killed pets and triggered alignment penalties. New policy preserves the parenthesized default `(n)` — safer for early-game. Sample reasoning from the v0.0.34 Qwen trace ("dog is small, 10/14 HP, I should say no") confirms this aligns with model intent. | (pending) | 05:18 |
| 0.0.50 | **`kick`/`throw` now bundle direction in-skill.** Previously they pressed the command key and left NetHack prompting "In what direction?" — the auto-dismiss handler then ESC-cancelled the action. v0.0.44 eval had 14 `kick` calls that all silently cancelled. Now `kick(direction=N)` sends `[^d, k]` (vi-style direction key). `throw(item=..., direction=...)` sends `[t, letter, k]`. | (pending) | 05:22 |
| 0.0.51 | **Pre-pin tier description as journal objective.** Previously the tier description appeared only in the system prompt; now it's also in `state["journal"].objective` so every obs shows it. The model no longer has to call `pin_objective` itself to keep the goal in context. | (pending) | 05:26 |
| 0.0.52 | **Auto-dismiss `--More--` prompts** in `env_response`. Previously these would consume the model's next keystroke (silently eating an intended action). Now CR (13) is auto-pressed when `"--More--"` appears in the message buffer, alongside the existing menu/inventory/yn dismiss. | (pending) | 05:30 |
| 0.0.53 | **HP-critical HINT override.** When HP < 30% of max, the HINT block fires "HP critical (x/y). Retreat / engrave_elbereth / pray" regardless of stairs/monsters. Helps small models notice they're about to die rather than continuing to autoexplore at 1 HP. | (pending) | 05:34 |
| **VALIDATION-3** | **Qwen3.5-9B on v0.0.49 actual**: **scout = 0.193 (new high, +220% vs baseline)**, 1 descend, 67 attacks, 4 kicks (direction-bundled = real), 13 recall_calls + 3 add_note (model using journal!). 197 turns. The y/n peaceful-safety fix in v0.0.49 plus the menu-offload accumulated wins are stacking. | n/a | 05:40 |
| 0.0.54 | **Better `recall` feedback when journal is empty/no-match.** v0.0.50 trace showed 13 recall_calls — many likely against an empty journal. Now: empty journal → "No notes recorded yet. Use add_note first."; no-match → "No notes matched 'X'. Existing keys: ..." Saves the model from looping on fruitless recalls. | (pending) | 05:45 |
| 0.0.55 | **`Journal.recall` includes the pinned objective** under pseudo-key 'objective'. Trace showed model querying `recall(objective)` and getting "no matches" because objective only rendered separately from notes. Now `recall(objective)` finds the pre-pinned tier goal. | (pending) | 05:50 |
| 0.0.56 | **More directive tier descriptions** for `corridor_explore`/`mini_dungeon`. Pre-pinned objective now includes the action recipe ("explore until you find stairs DOWN (`>`), step onto them, then call `descend`") rather than the abstract "terminate on reaching dungeon level 2". | (pending) | 05:53 |
| **VALIDATION-4** | **Qwen3.5-9B on v0.0.52 actual** (yet another seed): scout=0.033, 0 descents, 69 attacks, 32 pickups, 8 reads. This seed was rough — model picked up many items and read scrolls but never reached stairs. Cumulative across 6 runs since fix: mean scout = 0.085 (vs 0.06 baseline, +42%), mean descents = 1.0 (vs 0 baseline). | n/a | 05:58 |
| 0.0.57 | **Mid-sequence prompt halt.** When a multi-step skill (autoexplore, move_to) opens a y/n or --More-- prompt mid-sequence, remaining actions would otherwise be consumed as keystroke answers (e.g. autoexplore step 16 answers "Really attack?" as 'n' instead of moving NE). Now we halt the sequence and let the harness's auto-dismiss handle the prompt cleanly. | (pending) | 05:58 |
| 0.0.58 | **Useful belief_state snapshots.** When OfflineSubLM is the configured backend (the default), skip the stub summary call and record a concrete status snapshot instead (HP/AC/Dlvl/Turn/max_dlvl/descents). The stub's `"[offline-summary] ..."` output had no informational value; status snapshots at least give the model a real prior-moment reference. | (pending) | 06:00 |
| 0.0.59 | **SYSTEM_PROMPT mentions pre-pinned objective.** Replaced the generic "Your goal depends on the task you have been assigned" with explicit "Your top-level goal is pre-pinned in the JOURNAL block as `Objective: ...` — read once at start; don't re-pin unless strategy genuinely changes." Reinforces the v0.0.51 + v0.0.56 pre-pin flow so the model doesn't waste turns on pin_objective. | (pending) | 06:08 |
| **VALIDATION-5** | **Qwen3.5-9B on v0.0.57 actual**: scout=0.151 in only **94 turns** (vs typical 165-209) — mid-sequence prompt halt + dismissal made the per-skill turn-efficiency materially higher. 28 attacks (down from 60-80 in prior runs), 0 descends. | n/a | 06:14 |
| 0.0.60 | **HINT extends to items under player.** When `UNDER PLAYER` starts with `on tile:` (NLE's "You see here X"), HINT now suggests `pickup`. Targets evals where model walks over items without grabbing them. | (pending) | 06:15 |

## What each test version is gated on

The Hub runs four integration tests on every push (see `outputs/test_results/`):

1. **`test_pyproject_exists`** — file present in tarball.
2. **`test_pyproject_has_metadata`** — checks `[project]` has `name`, `description`,
   `tags`, `version`, `requires-python`. The trap:
   `tags` must be at `[project]` level, not under `[tool.verifiers]`.
3. **`test_readme_exists`** — file present.
4. **`test_install_and_import`** — `uv pip install <env_dir>` + `import <env_name>`.
   The trap: only the env directory ships, so the env's `pyproject.toml`
   cannot reference `nethack-core` as a workspace dep. We vendor it into
   the env via `tools/bundle_for_hub.py`.

## What each `vf-eval` failure mode looks like

Captured in `tests/test_rollout_simulator.py` so they're caught locally now:

| Symptom | Root cause | Test that catches it |
|---------|-----------|---------------------|
| `'ToolCall' object has no attribute 'function'` | `tc["function"]["name"]` access on flat ToolCall | `test_pydantic_tool_call_shape_is_accepted` |
| `Invalid env_response item type: list` | `return [{"role":...}]` (raw dict) OR `return (msgs, state)` (tuple) | `test_pydantic_no_tool_call_returns_vf_message` + `test_env_response_returns_messages_not_tuple` |
| `<skill>() got unexpected keyword argument 'arguments'` | Model passed malformed kwargs; dispatcher didn't filter | `test_malformed_tool_args_produce_feedback_not_crash` |
| `JSONDecodeError: Expecting value` | Non-JSON args string from the model | `test_dispatcher_handles_invalid_json_args` |
| `Environment 'MiniHack-Skill-Custom' doesn't exist` | Tier requires MiniHack but install lacks it | (not yet a test; manual env install) |

## How to reproduce Hub conditions locally

```bash
# 1. Vendor nethack_core into the env tarball
python tools/bundle_for_hub.py

# 2. Spin up a clean 3.12 venv (Hub uses 3.12.13)
rm -rf /tmp/hub_test && mkdir /tmp/hub_test
cp environments/nethack/{README.md,nethack.py,pyproject.toml} /tmp/hub_test/
cp -r environments/nethack/nethack_core /tmp/hub_test/
uv venv /tmp/hub_test/.venv --python 3.12

# 3. Install + import (this is what the Hub test does)
uv pip install --python /tmp/hub_test/.venv/bin/python /tmp/hub_test/
/tmp/hub_test/.venv/bin/python -c "import nethack; nethack.load_environment()"
```

If those three commands work, the Hub install test will pass. If `vf-eval`
also works against your local install (with `--endpoints configs/endpoints.toml`),
hosted eval should work too.
