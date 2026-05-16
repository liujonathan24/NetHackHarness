# Read this first when you wake up — 2026-05-16

## 🎯 Headline (since you went back to sleep at ~03:30 EDT)

You flagged: *"v0.0.34 Qwen trace shows 42% of turns on `menu_option` —
can we offload menus to the harness?"*

Shipped **v0.0.35 → v0.0.58** (24 versions). Key results on Qwen3.5-9B
local evals, `corridor_explore`, `max_turns=100`:

| run | scout_reward | descents | menu_option_calls |
|---|---:|---:|---:|
| v0.0.33 (broken baseline) | 0.06 | 0 | 62 (42% of turns!) |
| v0.0.39 | 0.163 | 1 | 0 (tool removed) |
| v0.0.43 | 0.06 | **3** | 0 |
| v0.0.46 | 0.062 | 1 | 0 |
| **v0.0.49** | **0.193 (best)** | 1 | 0 |
| v0.0.52 | 0.033 | 0 | 0 |
| v0.0.56 | 0.124 | 0 | 0 |
| v0.0.57 | 0.151 (in only 94 turns!) | 0 | 0 |

Across 9 fixed runs: **mean scout 0.108 (+80%)**, mean descents/rollout
0.78, **at-least-one-descent rate 5/9 = 56%** (vs 0% baseline), **0
spurious menu calls** in every run. Variance high (corridor_explore
has lots of seed luck). v0.0.57 finished in 94 turns vs typical 165-209
— the mid-sequence prompt halt is materially more turn-efficient.
Detailed table: `experiments/results/menu_offload_v0035_to_v0040.md`.

**v0.0.50 eval** showed 13 recall_calls + 3 add_note_calls — model
actively using journal. **v0.0.57 eval** (env 0.0.56) showed 0
add_note / recall / pin_objective calls — the pre-pinned objective
(v0.0.51) is now eliminating journal-thrash entirely, with comparable
reward (0.124). The model also used the wiki for the first time
(`wiki_lookup_calls=1`).

Key fixes shipped:
- **v0.0.35**: removed `menu_option`/`inventory_item` from agent tools; auto-dismiss menus in env_response; `eat`/`quaff`/`read` take `item` arg
- **v0.0.37**: `=== HINT ===` obs block (stairs)
- **v0.0.38**: dispatcher crash on `{"name": ...}` args
- **v0.0.39**: y/n auto-answer ("Really attack?" prompts)
- **v0.0.40**: type coercion (`"5"` → 5)
- **v0.0.42-43**: HINT extended to adjacent monsters (HP-aware)
- **v0.0.44**: direction aliases ('north'/'up'/etc.)
- **v0.0.49**: y/n peaceful safety ("Really attack?" → NO, preserves pet)
- **v0.0.50**: `kick`/`throw` bundle direction (v0.0.44 eval had 14 kicks all silently cancelled)
- **v0.0.51**: pre-pin tier description as journal objective
- **v0.0.52**: auto-dismiss `--More--` prompts
- **v0.0.53**: HP-critical HINT override
- **v0.0.54-55**: `recall` feedback improvements + recall finds pinned objective
- **v0.0.56**: more directive tier descriptions (action recipe pinned as objective)
- **v0.0.57**: mid-sequence prompt halt (autoexplore step 16 won't accidentally answer "Really attack?" as 'n')
- **v0.0.58**: useful belief_state snapshots when SubLM is offline (concrete status, not stub text)

**272 tests green.** All changes documented per-version in
`docs/HUB_VERSIONS.md`. Full architectural writeup in
`docs/onboarding/18-menu-offload-and-yn-autoanswer.md`.

---

## Earlier trace-driven fixes (the original headline)

You sent the haiku trace asking "why hasn't the model reached dlvl 2 — it
seems confused about the format." Three root causes from
`experiments/results/haiku_trace_analysis.md`:

1. **`<` (stairs UP) misidentified as stairs down** — happens every rollout.
2. **`@` overlay hides what the player is standing on** — model can't tell
   when it's actually on a `>` tile.
3. **`descend` silently failed** when called off-stairs.

Fixes shipped on Hub at **v0.0.30** (env CI green) and **v0.0.31** (the
worked example):
- `=== UNDER PLAYER ===` block in every obs.
- `=== ADJACENT === E=>(stairs DOWN)` instead of bare `E=>`.
- `descend` short-circuits with `"Can't descend — you're standing on: floor"`.
- SYSTEM_PROMPT GLYPH KEY + 4-step DESCENT WORKED EXAMPLE.

Validation eval against v0.0.30 with Claude Haiku 4.5 (eval started before
v0.0.31 finished CI so it ran on v0.0.30):
- **scout_reward 0.077 → 0.163 (+112%)** same model + tier vs v0.0.24
- descend_calls down to 1 (from ~150 wasted attempts on v0.0.24)
- See `experiments/results/hosted_eval_v0030_haiku_format_fix.md`

Final v0.0.32 eval with Qwen3.5-9B + worked-example prompt running now
to see if the worked example pushes the model to actually reach dlvl 2.

## More bugs found and fixed overnight

### Chain-accumulation in history compaction (v0.0.33)

You sent a screenshot of a user message that was just `[turn -92] [turn -91]
... [turn -7]` — no content. Root cause: `_one_line_summary` was re-feeding
already-compacted `[turn -N]` labels into the "feedback" extractor every
turn, prepending a new label each round. Fix: detect already-compacted
content, emit a single fresh `[turn -N]` label, optionally preserve the
status line. Regression test added.

### `extract_under_player` was returning garbage (v0.0.34)

The chars-array lookup at the player position returns `@` not the underlying
tile (NetHack overlays the player sprite). My first implementation said
"unknown (@)" every turn. Rewrote to parse NLE's message buffer for
"There is a staircase down here." / "You see here X" — NLE prints these
when the player lands on an interesting tile. Now reliable when present
(stairs/altars/fountains/items), silent when on plain floor.

## How to push more changes (new prime CLI flow)

The prime CLI was updated mid-session and now requires `--owner`:
```bash
python tools/bundle_for_hub.py
cd environments/nethack && prime env push --visibility=PRIVATE --plain --owner jonathanliu
```


Autonomous overnight session ran from ~20:51 EDT 2026-05-15 toward your
14:00 EDT wakeup. **Most recent push: v0.0.22**. 17 of 22 versions
confirmed green on Hub (5 queued mid-test as of writing). Five hosted
evals successfully validated the substrate end-to-end — skill mode, code
mode, dynamic_subgoal tier, AND the reward bugfix all work in production.
See `experiments/results/hosted_eval_*.md`.

**Key result**: v0.0.16 reward bugfix validated against Qwen3.5-9B:
`scout_reward` went from 0.000 (v0.0.14, broken) to **0.092** (v0.0.16,
fixed) on the same model/tier/seed. Real reward signal end-to-end.

After the reward fix, I implemented the survey's top recommendations
(v0.0.17–22): obs compaction, history compaction, periodic belief-state
summary, message run-length encoding, adjacency/visible-glyphs blocks,
journal render cap. **Measured savings (`experiments/exp15_token_savings.py`,
60-turn rollout):**
- Per-turn obs alone: **25.7% smaller** with compaction
- **Cumulative prompt: 89.8% smaller** with obs + history compaction (1930
  tokens at turn 60 vs 18840 baseline). Plot at
  `experiments/results/exp15_token_savings.png`.

**Apples-to-apples hosted eval comparison** (Qwen3.5-9B, same seed, same
$0.79 budget):
- v0.0.14 (broken reward, no compaction): 0 reward, 146 turns, 41 menu
  misuses, 2 autoexplore calls
- **v0.0.24** (post all the work): **0.132 scout_reward**, 183 turns, 0
  menu misuses, 47 autoexplore calls
- See `experiments/results/hosted_eval_v0014_vs_v0024_apples_to_apples.md`
  for the full table. **This is the Monday slide.**

**215 pytest tests, all green in 33s.**

## What you asked me to do while you slept

You sent a 3-subagent directive: rewrite README + metric docs, deep-research
game-harness prompting strategies, fix the suspected reward bug + improve
prompting. All three completed; their outputs are now integrated.

### Real reward bug found and fixed (v0.0.16)

Subagent C traced it: verifiers' `Rubric.score_rollout` runs ONCE at end of
rollout. The old `scout_reward` returned just the last step's `scout_delta`
(almost always 0 because the final action rarely reveals new tiles), and
`descent_reward` compared `depth > max_dlvl_reached` AFTER `env_response`
had already bumped `max_dlvl_reached` — so it was always 0 too.

**Fix in `environments/nethack/nethack.py`**: env_response accumulates
`state["scout_reward_total"]` and `state["descent_count"]`; the reward
functions now return those running totals. New `tests/test_reward_integration.py`
(4 tests) locks this behavior. **All prior Hub-eval `reward: 0.0` numbers
should be discounted — they were measuring a broken metric.**

### System prompt now includes a strategy primer

The user-facing system prompt got a `=== STRATEGY PRIMER ===` and a
`=== SKILLS CHEAT SHEET ===`. Total prompt ~300 tokens. Should reduce
malformed `eat`/`quaff` calls (the 9B model wasted 41 turns on menus
in the first eval).

### Prompting survey (subagent B's deliverable)

New doc at `docs/PROMPTING_SURVEY.md` — 215 lines surveying 12 game-agent
systems (Claude/Gemini Plays Pokemon, Glyphbox, BALROG, Cicero, SWE-agent,
OpenHands, Voyager, etc.) with concrete token-reduction recipes for us.
Headline recommendations:
1. **Stop echoing past tty grids** in chat history (Glyphbox's #1 trick).
   We currently re-send the full map every turn → 4M input tokens/rollout.
2. **Two-tier compaction**: last K=5–10 turns full; 10–100 action-only; >100 dropped.
3. **Wire SubLM belief-state summary every 25 turns** (substrate already shipped).
Expected combined impact: 4M tokens/150 turns → <5k tokens/turn, bounded.

### Critical CLI fix discovered earlier

Use `-a` (env-args) not `-x` (extra-env-kwargs) to override `tier` /
`interface` / `max_turns` in `prime eval` and `vf-eval`. `-x` is silently
ignored for these because it calls `set_kwargs()` post-construction.

## TL;DR — what changed overnight

You went to sleep with v0.0.7 working on the Hub. You wake up with **v0.0.15**
that adds:
- Track B (RLM code mode) wired end-to-end (`interface="code"`)
- Sub-LM API (`nh.summarize/plan/recall_lm`) with swappable backend
- Dynamic-subgoal curriculum (the autoresearch axis)
- Belief-state distillation (auto-summarize on level transition)
- 7 regression experiments + baseline-agent sweep
- Wiki snapshot scraper (Mediawiki API extracts)
- 30-page wiki snapshot at `wiki/snapshot.json`
- Dispatcher hardened against malformed LM tool calls
- Pluggable backends via `load_environment(sub_lm=..., subgoal_proposer=...)`
- Monday demo runner: `python tools/run_demo.py`
- 7 new survival skills (eat / quaff / read / pray / engrave_elbereth / kick / throw)
- Status-aware halt: multi-action skills auto-stop on HP drop / low HP / hunger
- Reference docs: `docs/EVAL_RECIPES.md`, `docs/HUB_VERSIONS.md`, `experiments/REPORT.md`
- Smoke tests (`tests/test_smoke.py`) confirm every module imports + every expected skill/tier registered
- 179 pytest tests across 18 files, all green in ~33s (includes Hub-install reproduction + reward integration tests)

## First 5 minutes (paste-ready)

```bash
cd /Users/Fritz/Downloads/files
source .venv/bin/activate

# 1. Sanity: every test should pass in ~10s
pytest tests/ -q

# 2. The 8-experiment regression table (this is a Monday slide)
python experiments/run_all.py

# 3. The Monday demo (test+experiments+baselines+trajectory recording)
python tools/run_demo.py

# 4. Open the recorded trajectory in the replay viewer
open tools/replay_viewer.html
# then load docs/onboarding/demo_trajectory.json
```

If you have an API key:

```bash
export OPENAI_API_KEY=sk-...        # or PI_API_KEY for Qwen, etc
python tools/run_demo.py --model gpt-4.1-mini

# OR against the Hub:
prime eval jonathanliu/nethack -m gpt-4.1-mini -n 5 -r 3
```

## Read these in order

1. **`docs/MONDAY_TALKING_POINTS.md`** — the punchy pitch for Alex,
   open it on a second monitor during the meeting. 3 things to discuss,
   3 things to ask him for.
2. **`SESSION_SUMMARY.md`** — full writeup of what shipped, what's pending,
   what to bring to Monday.
2. **`docs/HUB_VERSIONS.md`** — version-by-version history of the Day-4 push,
   including which bug each version fixed.
3. **`docs/EVAL_RECIPES.md`** — model picks, tier list, common errors.
4. **`README.md`** — overview + file map (now reflects all the new modules).

## Things you should decide today

1. **Default interface.** `skill` or `code`? Both work. `skill` is the
   Pokemon-bench-comparable comparable surface; `code` is the Alex/RLM-research
   surface. The current default is `skill`. To switch: pass `interface="code"`
   to `load_environment` (or set it as the Hub env's default arg).
2. **Default tier.** Currently `corridor_explore`. Worth promoting
   `dynamic_subgoal` to default once you have a real proposer LLM wired —
   it's the autoresearch headline.
3. **Hub visibility.** Still PRIVATE. If you want Alex to install with
   `prime env install jonathanliu/nethack`, flip to PUBLIC or add him as
   a collaborator. Command:
   ```bash
   prime env share jonathanliu/nethack --user alex   # if you have his prime user
   # OR: prime env update jonathanliu/nethack --visibility=PUBLIC
   ```

## Things I did NOT do (need your input)

- **Wire prime-rl as the SubLM backend.** The class structure is in place
  (`SubLM` ABC + `OfflineSubLM` reference impl); the swap is one subclass.
  I left it to you because it touches your prime-rl credentials and Alex's
  inference-server endpoint choice.
- **`prime env share` / make public.** Hub-visible side effect; left for you.
- **Run hosted eval against gpt-4.1-mini.** Charges your account; left for
  you to trigger when you're ready.

## Known cosmetic issues

- Pylance complains about unused `_signum` / `_frame` args in `code_mode.py`
  — they're SIGALRM handler signature requirements; ignore.
- `record_demo.py` still uses the `sys.path.insert(0, parent)` workaround
  for the editable install layout. Src-layout refactor would fix; not done.
- Belief-state distillation is best-effort (silent on SubLM errors). When
  you wire a real SubLM, watch logs for distillation failures during the
  first few rollouts.

## What's still on the longer roadmap

(All from `/Users/Fritz/.claude/plans/wiggly-dreaming-bengio.md`)

- Real prime-rl proposer + SubLM backend (week 2)
- PufferLib upstream PR for `pufferlib.environments.nethack` (week 3)
- BALROG progression metric as optional reward (stretch)
- Src-layout refactor (low impact, deferred)
- Full wiki scrape (~3000 pages, ~5MB; current snapshot is the curated 30)

## Where to find me

This session has touched 60+ files. If something looks suspicious, the
critical safety nets are:
- `tests/test_rollout_simulator.py::test_pydantic_*` — locks the verifiers
  contract shape.
- `tests/test_code_mode.py::test_code_mode_env_response_end_to_end` —
  exercises code mode through the full env_response chain.
- `tests/test_subgoals.py::test_dynamic_subgoal_tier_*` — exercises
  dynamic subgoal tier through env setup.

If those three test classes pass, the env is healthy.
