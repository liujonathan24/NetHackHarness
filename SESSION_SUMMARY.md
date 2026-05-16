# Session summary — Day 3 + Day 4 push

What happened in the autonomous sessions on 2026-05-15.
Day 3 was ~01:30 → ~02:36 EDT; Day 4 was ~14:00 → ongoing the same day,
including overnight to ~14:00 EDT 2026-05-16.

The Day-4 narrative arc: pushed the env to the Hub, debugged a series of
verifiers contract changes that surfaced only at hosted-eval time, then
landed Track B (RLM-native code mode) wiring + a complete regression-
experiment harness.

## What was on the agenda

You'd authed `prime` and built the venv, then asked me to:

1. Verify Day 1 (layout reorg) by running tests, fix any breakage.
2. Begin Day 2 work (the foundation fixes).
3. For each task: write tests + an in-depth onboarding writeup.
4. Optimize and replan as I went.
5. Work autonomously for 12 hours.

## Headline numbers (end of Day 4)

```
175 tests across 17 files, all passing in ~33 seconds (incl. Hub-install reproduction test)
14 onboarding docs (~1900 lines) + EVAL_RECIPES.md + HUB_VERSIONS.md
13 source modules in nethack_core/ + 1 in environments/nethack/
6 dev tools (replay viewer, recorder, profiler, wiki scraper, bundler, demo runner)
8 regression experiments + baseline-agent sweep
1 sample trajectory recorded for the demo
1 Dockerfile for Prime Sandbox / Hosted Training
30-page wiki snapshot (30KB JSON, Mediawiki-API extracts)
7 regression experiments + baseline-agent sweep (all FIX CONFIRMED)
v0.0.15 published on the Hub (jonathanliu/nethack), 15 versions during Day 4 (each green)
21 registered skills (was 14): added eat / quaff / read / pray / engrave_elbereth / kick / throw
status-aware halt: multi-action skills auto-stop on HP-drop or hunger
```

## Headline outcome (Day 4)

The env is **live on the Prime Hub at v0.0.8** (`jonathanliu/nethack`),
all 4 Hub integration tests green. Default tier is `corridor_explore`
(no MiniHack dep needed). `prime eval` produces real rollouts.

Track B (RLM-native code mode) is wired:
`load_environment(interface='code')` swaps the 14 skill tools for one
`code(source=...)` tool that runs sandboxed Python against an `nh`
namespace, with `nh.move/autoexplore/wiki_lookup/summarize/plan/recall_lm`
all callable from the same source string. The sub-LM tools default to an
`OfflineSubLM` for tests; swap in a prime-rl client to go live.

## What's now shipped

### Foundation fixes (Day 2)

1. **`NetHackScore` substitution.** Day 1's seeding tests failed against
   `NetHackChallenge-v0` because the Challenge monkey-patches
   `set_initial_seeds` to refuse all seed changes. Wrapper now defaults to
   `NetHackScore-v0`; reproducibility tests pass.
2. **`no_progress_timeout` gating.** Only passed to `gym.make` when the
   task name contains "Challenge" (Score doesn't accept it).
3. **`scout_reward` → per-step delta.** The v0 implementation returned a
   cumulative count, which paid the agent for standing still. Now captures
   pre/post set sizes and returns the delta; `state["scout_delta"]` is
   set by `env_response` each step.
4. **`_strip_right_menu` real implementation.** New
   `extract_menu_region()` returns options + leftmost column, the menu
   regex now searches anywhere on the row (not just from column 0), and
   `render_map_view` truncates rows at the menu column.
5. **`bootstrap_character` via the welcome message.** Parses
   `"You are a neutral male human Monk."` directly from
   `last_observation.message`; no `#attributes` command consumed, works on
   the restricted NetHackScore action set, lowercased + defensive.
6. **Ascension + death detection.** New `_detect_terminal_outcome` scans
   the tty for marker substrings; `state["ascended"]` and `state["died"]`
   are absorbing flags; `ascension_reward` now actually fires.

### Day-3 features

7. **Journal skill** (`add_note` / `recall` / `pin_objective`). Per-rollout
   structured note store. Pokemon-bench lesson. Rendered into the
   observation block whenever non-empty. No NLE turn consumed.
8. **Milestones** for Pokemon-route-style termination predicates. Built-
   ins: `mine_town`, `sokoban_complete`, `oracle_consult`,
   `reach_dlvl(n)`. `any_of` / `all_of` composition. Conservative
   substring matching (false negative > false positive).
9. **A\* pathfinding** + frontier-based **autoexplore**. 8-connected
   Chebyshev, doorway-corner blocking, action-index-vs-enum bridging.
   Single biggest LM-agent UX win.
10. **Curriculum integration with milestones.** Replaced stub tiers
    `corridor_explore` and `mini_dungeon` with milestone-driven real-NLE
    tiers. Added `mines_to_minetown`, `sokoban_complete`, `oracle_consult`.
    `success_reward` (weight=100) added to rubric.
11. **Replay viewer.** Single-file HTML (`tools/replay_viewer.html`)
    reading Trajectory JSON. tty + status + inventory + journal + skill
    calls + reward, scrubbable timeline, keyboard shortcuts, URL loading.
12. **Frame capture in `replay.py`.** `TrajectoryFrame` per step, ~2KB
    each. `record_demo.py` + a saved demo trajectory at
    `docs/onboarding/demo_trajectory.json`.
13. **Dockerfile.prime.** NLE preinstalled image (cmake + bison + flex
    + libbz2-dev). For Prime Hosted Training so pod start isn't
    rebuilding NLE every time.
14. **Profile harness** + microbench. NLE 1.3 at ~60k sps single-core
    (4× the published 14k baseline), `observations.shape()` is the layer-1
    bottleneck at 3.8k/sec. Two opts applied: `parse_inventory` skips
    empty slots (np.nonzero); `nearest_frontier` uses `deque` + on-the-fly
    frontier check (250µs → 85µs).
15. **PufferLib adapter.** Gymnasium-shaped wrapper without raylib dep
    (the "pufferlib constraint" you flagged). PufferLib installs separately
    once you have raylib.
16. **Wiki tool.** `WikiIndex` with substring + title-weighted ranking.
    `wiki_lookup` and `wiki_search` skills. Seeded with 6 high-value
    pages (cockatrice, mine town, sokoban, oracle, elbereth, altar).
    ChromaDB-swap-ready behind the existing extras dep.
17. **Code-mode skeleton.** Track B prep for the RLM-research angle: AST
    validator + sandboxed runtime + curated `nh` namespace. Env-stepping
    primitives still raise stub errors; wiring lands when Alex green-lights.

### Test suites (one per module)

- `test_seeding.py` (4) — reproducibility load-bearing.
- `test_observations.py` (12) — menu, inventory prompt, parsing, map masking.
- `test_rewards.py` (10) — scout delta, descent, success, ascension, terminal detection.
- `test_skills.py` (7) — registry, welcome parsing, live bootstrap.
- `test_journal.py` (10) — keyed notes, recall, objective, render.
- `test_milestones.py` (16) — each built-in, dungeon-branch gating, idempotency, composition.
- `test_pathfinding.py` (15) — walkability, A* edge cases, doorway corner, frontier discovery.
- `test_replay.py` (6) — Trajectory roundtrip, frame capture, audit.
- `test_curriculum.py` (8) — tier consistency, milestone wiring.
- `test_integration.py` (7) — load_environment + setup_state + env_response chain.
- `test_puffer_env.py` (5) — gym contract for the adapter.
- `test_wiki.py` (9) — lookup, search ranking, JSON roundtrip, hot-swap.
- `test_rollout_simulator.py` (6) — scripted full-rollout sims, offline `vf-eval` equivalent.
- `test_code_mode.py` (11) — AST validator, runtime, namespace, builtins denylist.

### Onboarding docs (one per shipped fix)

`docs/onboarding/01..13` plus index. Each follows the same structure:
problem → fix → edge cases handled → verification command → future work.
Read in order for new contributors. Cross-reference each from `[[name]]`
links and the failure-mode lookup table in the README.

## Day 4 additions (the "make hosted eval actually work" arc)

After v0.0.0 was published the Hub kept failing each `prime eval` for a
different reason. Each fix is now locked down by a regression test that
exercises the exact pydantic shape `verifiers 0.1.14` passes on the Hub:

1. **MiniHack-only default tier.** v0.0.3 default was `solo_combat` →
   `MiniHack-Skill-Custom-v0` which the Hub install lacks. Switched to
   `corridor_explore` (NLE-only, terminate on dlvl 2). MiniHack tiers
   now raise a friendly "install nethack[minihack]" error.
2. **`tc["function"]["name"]` → flat `ToolCall.name`.** verifiers passes
   its own pydantic ToolCall, not raw dicts. Dispatcher in `nethack.py`
   now handles both shapes.
3. **`return [{"role":"user", ...}]` → `vf.UserMessage(...)`.** The newer
   normalize_messages rejects raw dict messages.
4. **`return (messages, state)` → `return messages`.** verifiers' contract
   changed: state mutates in place, env_response returns just messages.
   Returning the tuple made normalize see a list-of-list.
5. **`search() got unexpected kwarg 'arguments'`.** Tiny models (Qwen 0.8B)
   produce malformed tool calls. SkillRegistry.call now filters kwargs
   to the function's signature and surfaces unknowns as feedback rather
   than crashing the worker.

All five caught by `tests/test_rollout_simulator.py::test_pydantic_*` +
`tests/test_code_mode.py::test_load_environment_code_interface_*`. The
"local pytest passes but Hub eval fails" failure mode is now eliminated.

## Day 4 substrate work

- **Track B / Code mode** wired end-to-end. `nh.move/autoexplore/etc`
  dispatch through `SkillRegistry`, queue actions in `nh._log`, the
  verifiers env applies them. `nh.summarize/plan/recall_lm` route through
  a swappable `SubLM` backend (default `OfflineSubLM` returns deterministic
  stubs). `interface="code"` flag in `load_environment`.
- **Dynamic-subgoal curriculum** (the autoresearch axis). New tier
  `dynamic_subgoal`. `OfflineSubgoalProposer` returns role-specific
  per-rollout objectives; the env compiles the structured `termination_check`
  into a `Milestone` and pins the objective to the journal. Real proposer
  is a one-class swap — see `docs/onboarding/14-dynamic-subgoals.md`.
- **Belief-state distillation**. At level transitions `env_response`
  auto-calls `SubLM.summarize(journal_notes, query=f"key events on dlvl X")`
  and stamps the result as `dlvl_<n>_summary` in the journal. Best-effort
  (silently skips on SubLM error) so it never breaks a rollout.
- **Regression experiment harness** (`experiments/`). 7 scripts, each
  reproduces the buggy v0 behavior inline + runs the fixed code on the
  same seed + emits JSON + (where applicable) a PNG plot. `run_all.py`
  produces a verdict table.
- **Baseline-agent reward distribution** (`experiments/baseline_agents.py`).
  `random_walk` / `always_search` / `autoexplore` × seeds, summary table.
- **Monday demo runner** (`tools/run_demo.py`). One command produces tests
  → experiments → baselines → recorded trajectory → optional live LM eval.
- **Wiki snapshot scraper** (`tools/build_wiki_index.py`). 30-page
  curated seed list using Mediawiki API extracts (cleaner than HTML scrape).
  Drop-in replacement for `WikiIndex.default()`.
- **Endpoint registry** (`configs/endpoints.toml`). vf-eval `-m gpt-4.1-mini`
  / `-m claude-haiku-4-5` / `-m Qwen/Qwen3-32B` now resolve to the right
  base URL + key env var without `-b/-k` flags.
- **EVAL_RECIPES doc** (`docs/EVAL_RECIPES.md`). Reference for which models
  to pick, tier list, common errors and their fixes.

## Day 4 evening (the "after the user went to sleep" arc)

User asked for three parallel subagents: rewrite docs, deep research on
game-prompting harnesses, bugfix rewards + improve baseline. All three
completed. Then 10 more versions shipped post-survey:

### Reward bug FIXED (v0.0.16)

Verifiers' `Rubric.score_rollout` runs ONCE at end-of-rollout. The old
`scout_reward` returned only the LAST step's `scout_delta` (almost always
0). Fix: env_response accumulates `scout_reward_total` and `descent_count`;
rewards return running totals. **Validated in hosted eval**: scout_reward
went from 0.000 (v0.0.14) to 0.092 (v0.0.16) on same model/tier/seed.

### Prompting survey shipped + 10 of its recommendations implemented

`docs/PROMPTING_SURVEY.md` covers 12 game-agent harnesses (Claude/Gemini
Plays Pokemon, Glyphbox, BALROG, Cicero, SWE-agent, OpenHands, Voyager, ...)
with 10 ranked token-reduction recipes. **8 of 10 now implemented:**

| ver | what shipped |
|-----|-------------|
| v0.0.17 | Obs compaction: strip blank tty rows, glyph-run encode `.{20}`, inventory diff |
| v0.0.18 | History compaction: keep 5 recent, summarize 6–100, drop >100 |
| v0.0.19 | Periodic SubLM belief-state every 25 turns |
| v0.0.20 | Message run-length encoding |
| v0.0.21 | Adjacency + visible-glyph blocks |
| v0.0.22 | Journal render cap |
| v0.0.23 | All knobs exposed via `load_environment` kwargs (A/B-testable) |
| v0.0.24 | Journal diff-only rendering |
| v0.0.25 | bootstrap_character fallback to tty status line (calendar-event-proof) + sharper schema descriptions for `menu_option`/`inventory_item`/`eat` |

**Measured savings** (`experiments/exp15_token_savings.py`, 60-turn rollout):
- Per-turn obs: **26.1% smaller**
- **Cumulative prompt: 89.8% smaller** (1925 tok at turn 60 vs 18840 baseline)

### Survival skill expansion + safety (v0.0.14, v0.0.15)

7 new skills: `eat`, `quaff`, `read`, `pray`, `engrave_elbereth`, `kick`,
`throw`. Multi-action skills (autoexplore, move_to) now auto-halt on
HP-drop / low-HP / hunger. Survival baseline.

### NLE calendar-event flake captured (v0.0.25)

`bootstrap_character` was failing on 2026-05-16 because today is a new
moon, so NLE's "Be careful! New moon tonight." overwrites the welcome
message buffer. Added a fallback that scrapes the tty status line for
the level-1 rank title ("Candidate" → monk) + alignment word. Saved as
[[nle-calendar-event-preempts-welcome]] memory.

### Hosted-eval validation summary

Eight hosted evals across Qwen3.5-{0.8B, 2B, 9B, 35B-A3B} and Claude
Haiku 4.5. Headline:
- **No crashes** in any v0.0.7+ rollout despite contract churn.
- v0.0.16 produced **first nonzero reward in production** (scout 0.092).
- v0.0.24 vs v0.0.14 apples-to-apples on Qwen3.5-9B at same cost ($0.79):
  - reward 0 → **0.132** (rubric bug fix surfacing real exploration)
  - turns 146 → **183** (+25% within same wallclock)
  - menu_option misuse 41 → **0** (system-prompt strategy primer)
  - autoexplore calls 2 → **47** (primer redirected agent to A* skill)
- Claude Haiku 4.5 on v0.0.24 cost **$5.72** but scored LOWER on
  corridor_explore (0.077 vs Qwen's 0.132) — strategic models don't
  necessarily win short-horizon tile-coverage tiers. See
  `experiments/results/hosted_eval_haiku_vs_qwen.md`.
- Code mode used 48 `code` tool calls in one rollout, replacing what
  would have been ~150 skill calls.
- **Total spent on hosted evals: ~$10.90 of the $20 per-run budget.**

### Substrate additions post-comparison

- **BALROG progression score** (`nethack_core/balrog.py`): empirical-ish
  P(ascend | DL, XL) calibrated against 4 BALROG paper datapoints.
  Wired as `state["balrog_progression"]` (info-only, not in rubric).
- **2 new milestone-driven tiers**: `quest_complete`, `castle_reached`.
  Both deep-NLE; substrate ready when an agent can actually reach them.
- **Tunable compaction knobs**: `compact_obs`, `history_keep_full`,
  `history_drop_after`, `belief_state_interval`, `journal_render_max_chars`
  all exposed via `load_environment(...)` kwargs (v0.0.23+).

### Trace-driven format fixes (v0.0.29-34)

User reviewed the 200-turn claude_haiku.log and flagged: model couldn't
reach dlvl 2 because of **format confusion**. Root cause analysis at
`experiments/results/haiku_trace_analysis.md`. Five bugs total surfaced:

1. **`<` vs `>` glyph confusion** → System-prompt GLYPH KEY callout +
   adjacency labels (`E=>(stairs DOWN)`).
2. **`@` overlays the tile beneath** → New `=== UNDER PLAYER ===` obs
   block. First impl tried to read from `chars[player_pos]` but that
   shows `@` too. **v0.0.34 fix**: parse the NLE message buffer for
   "There is a staircase X here." — NLE prints these when the player
   lands on stairs/altar/fountain.
3. **Silent `descend` failure** → `descend` short-circuits with
   "Can't descend — you're standing on: {tile}".
4. **Descent confusion at the strategy level** → System-prompt 4-step
   WORKED EXAMPLE (autoexplore → see `>` in ADJACENT → move to it →
   verify UNDER PLAYER → descend).
5. **History-compaction chain-accumulation** (v0.0.33). User flagged
   a chat-history snapshot where every old user message was just
   `[turn -92] [turn -91] ... [turn -7]` — no content. Root cause:
   `_one_line_summary` was re-feeding the `[turn -N]` label as
   "feedback" each compaction round, prepending a new label without
   replacing the old. Fix: detect already-compacted messages and
   emit a fresh single label. Idempotent. Regression test added.

**Haiku 4.5 result after fixes 1-3** (v0.0.30): scout_reward **0.077 → 0.163**
(+112%), descend_calls dropped to 1 from ~150 wasted attempts. Full writeup:
`experiments/results/hosted_eval_v0030_haiku_format_fix.md`. Detailed
onboarding doc: `docs/onboarding/17-trace-driven-format-fixes.md`.

## What's NOT shipped (and why)

- **`prime env push --visibility=PRIVATE`** — Hub-visible side effect; I
  paused for your confirmation. Run when ready:
  ```bash
  cd environments/nethack && prime env push --visibility=PRIVATE --auto-bump
  ```
  Alex can then `prime env install <your-owner>/nethack`.
- **`vf-eval` against a real LM** — needs an API key. The offline scripted-
  rollout simulator (`test_rollout_simulator.py`) covers the contract.
- **Src-layout refactor.** The editable install puts `nethack_core` contents
  on sys.path top-level (works for pytest, breaks `python tools/foo.py`
  scripts that need the package itself). Worked around in `tools/record_demo.py`
  with a `sys.path.insert(0, parent)`; long-term should restructure.
- **Real wiki snapshot.** The 6-page seeded index is dev-time only.
  Wiring a full scrape is its own task (~1 day).
- **Track B (RLM code mode) full wiring.** Skeleton ships; env-step wiring +
  sub-LM tools land in Week 2 after Alex agrees the headline.

## How to verify the whole thing

```bash
source .venv/bin/activate
pytest tests/ -v   # 128 passed
python tools/profile_env.py
python tools/record_demo.py
open tools/replay_viewer.html
```

## Where to look next

- Start: this file + `README.md` + `docs/onboarding/README.md`.
- For the full plan with two-week schedule + tracks A/B + dynamic-subgoal
  axis: `/Users/Fritz/.claude/plans/wiggly-dreaming-bengio.md`.
- For the original design doc: `docs/design.md`.

## Five things to bring up Monday (updated for Day 4)

1. **Hub env is live and passing.** Walk in with a working `prime eval
   jonathanliu/nethack -m gpt-4.1-mini -n 5 -r 3` from your laptop.
2. **Track A (replay viewer + journal) is done; Track B (RLM code mode)
   is wired.** Both demoable. Ask Alex to pick the headline interface for
   Monday's writeup, or run a small head-to-head.
3. **The dynamic-subgoal axis** (curriculum proposed by an LLM given the
   wiki) is the unique research direction. Substrate is in place; the
   proposer LLM call slots into the existing `OfflineSubLM` interface.
4. **The 7 regression experiments table** (`python experiments/run_all.py`)
   is the slide that shows every fix is real, not just claimed. All 7
   FIX-CONFIRMED.
5. **PufferLib adapter** + the gymnasium pin conflict story — this is a
   real teaching moment about the "training-grade env" claim: NLE 1.3 and
   PufferLib 2.x can't share a venv. The adapter ships; the install is
   separate. Honest framing for the talk.

## How to verify everything (smoke test)

```bash
source .venv/bin/activate
pytest tests/ -q                       # 135 passed
python experiments/run_all.py          # 7 FIX CONFIRMED
python tools/profile_env.py            # env throughput numbers
python tools/record_demo.py            # generates a Trajectory JSON
open tools/replay_viewer.html          # load demo_trajectory.json
prime env status jonathanliu/nethack   # Hub status
```

The eval-against-real-LM is one command; needs an API key:

```bash
export OPENAI_API_KEY=sk-...
vf-eval nethack -m gpt-4.1-mini -n 1 -r 1 \
  --endpoints configs/endpoints.toml
```


## 2026-05-16 04:00–05:00 EDT — Format-confusion fixes (Days 35-45)

User flagged that the v0.0.34 Qwen3.5-9B trace showed 42% of turns
(62/147) on `menu_option` calls — the model was treating every in-game
prompt as a menu requiring tool selection. User direction: *"Can we
avoid allowing opening the menu? That is a known area that we may want
to offload to the harness rather than the agent."*

Shipped v0.0.35 → v0.0.45 implementing:

- v0.0.35: removed `menu_option`/`inventory_item` from agent tools;
  `env_response` auto-presses ESC to dismiss any open menu/inv-prompt;
  `eat`/`quaff`/`read` take `item` arg (substring or letter), bundle
  selection in-skill.
- v0.0.36: made `item` optional in schema.
- v0.0.37: new `=== HINT ===` obs block — directive next-action callout
  for stairs.
- v0.0.38: fixed crash on `{"name": "..."}` tool args (positional-only
  dispatcher params).
- v0.0.39: y/n prompt auto-answer ("Really attack? [yn] (n)" was the
  #1 menu_option trigger — model literally reasoned its way into
  selecting `menu_option(0)` for a single-keystroke prompt).
- v0.0.40: dispatcher type coercion (`"5"` → 5) + broader call-failure
  catch.
- v0.0.41: autoexplore dead-end tip → `search` for hidden passages.
- v0.0.42–43: HINT extended to adjacent monsters (with HP-aware branch).
- v0.0.44: direction aliases ('north'/'up'/'east'/etc).
- v0.0.45: expanded y/n policy table (pick up, throw away, etc).

**Validation eval (Qwen3.5-9B, corridor_explore, 100 max_turns):**

| Metric | v0.0.33 (broken) | v0.0.40 (fixed) | Δ |
|---|---|---|---|
| scout_reward | 0.06 | **0.163** | +172% |
| descend_calls | 0 | **1** | first non-zero! |
| autoexplore_calls | 10 | **107** | +970% |
| attack_calls | 12 (mostly wasted on prompts) | 1 (effective) | quality up |
| menu_option_calls | 62 (42% of turns) | 0 (removed) | -∞ |
| inventory_item_calls | 17 | 0 (removed) | -∞ |

The model now spends every LM turn on actual gameplay. **262 tests
green**. See `experiments/results/menu_offload_v0035_to_v0040.md` and
`docs/HUB_VERSIONS.md` rows v0.0.35–45.

A second eval (v0.0.44, different seed) showed **3 descents**, 61
attacks, 3 Elbereth engravings, 14 kicks. Descent trajectory across
iterations: **0 → 1 → 3**. The y/n auto-handler unlocked combat
engagement; the HINT block helped the model recognize stairs.

Subsequent versions (v0.0.46–48): autoexplore short-path tail-hint,
fallback tools-list filter, STATUS line max-Dlvl-reached. See
`docs/onboarding/18-menu-offload-and-yn-autoanswer.md` for the full
write-up.
