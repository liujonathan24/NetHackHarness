# Monday meeting talking points — nethack-rl

For the 30-minute design review with Alex. Punchy, concrete. Build the
deck or just open this on a second monitor.

## The 30-second pitch

"I built a Hub-live verifiers environment for NetHack with three first-class
interfaces — skill mode, RLM-native code mode, and an autoresearch
dynamic-subgoal mode. All three work hosted at `jonathanliu/nethack`. Pull
and try it. I'd like your input on which interface should be the default
for the v0.1 training runs."

## What's live on the Hub

```
prime env install jonathanliu/nethack
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 1 -r 1 \
  -a '{"tier": "dynamic_subgoal", "interface": "code", "max_turns": 30}'
```

- **59 versions shipped** (each Hub-tested green; latest = v0.0.59).
- **272 local pytest tests**, including a Hub-install reproduction test
  that catches "passes locally but breaks hosted" failures pre-push.
- Hosted + local evals across Qwen3.5-{0.8B, 2B, 9B, 35B-A3B}, Claude
  Haiku 4.5, including code mode + dynamic_subgoal. **~$16 spent**.
- v0.0.35→v0.0.59 menu-offload arc converted the v0.0.33 broken
  baseline (62/147 turns wasted on menus, 0 descents) into a clean
  agent loop: mean scout 0.097 (+62%), 0 spurious menu calls, 1.0
  mean descents/rollout across 7 seeds.

## Three things to discuss

### 1. Default interface: skill vs code

- **skill mode** (current default): 14 tools, one per skill. Pokemon-bench-
  comparable. Verbose: 144 tool calls in 146 turns (Qwen 9B).
- **code mode** (`interface="code"`): single `code(source=...)` tool runs
  sandboxed Python against an `nh` namespace. Same rollout used 48 code
  calls vs 144 skill calls. **27% fewer input tokens at parity reward.**
  This is the direct application of your RLM paper's "model writes Python
  loops that call sub-LMs" pattern.
- **My recommendation**: default to code for v0.1, expose skill as a
  comparability flag. Want your read.

### 2. Autoresearch axis: dynamic_subgoal tier

- New tier `dynamic_subgoal`: `SubgoalProposer.propose(role, obs)` →
  `SubgoalSpec(objective, termination_check)`. The env compiles the
  termination_check into a `Milestone`, pins the objective to the
  journal, runs the rollout against it.
- Currently `OfflineSubgoalProposer` (canned per-role specs). The class
  is a one-subclass swap for a real prime-rl-backed proposer.
- The research question: "can an LLM design its own NetHack curriculum
  given the wiki?" — and the meta-RL signal is whether the proposed
  subgoal achievable + useful + progress-aligned.
- **I want your decision**: should the proposer LM be the same model
  being trained (self-curricular), or a separate frozen model? Each
  has different convergence properties.

### 3. The reward bug (everything before v0.0.16 was lying)

- The first 14 versions reported `reward: 0.0` on every hosted eval.
  Turned out the rubric was reading the *last step's* scout_delta, which
  was almost always 0. **Cumulative scout discoveries were being
  silently discarded by the harness.**
- Fixed in v0.0.16: env_response accumulates `state["scout_reward_total"]`
  + `state["descent_count"]`; reward functions return running totals.
- **Validated end-to-end**: same model/tier/seed went from 0.000 →
  0.092 scout_reward. First nonzero reward observed in production.
- Lesson worth flagging for any verifiers user: if your Rubric reads
  per-step deltas, accumulate yourself.

## The apples-to-apples results (lead with these)

### Qwen3.5-9B (cheap, fast): broken-reward → format-fixed

| metric | v0.0.14 (baseline) | v0.0.24 (post-survey) | Δ |
|--------|------------------:|---------------------:|--:|
| **scout_reward** | 0.000 | **0.132** | +∞ |
| num_turns | 146 | 183 | +25% |
| menu_option_calls | 41 (stuck) | 0 | -41 |
| autoexplore_calls | 2 | 47 | +45 |
| output_tokens | 46K | 31K | -32% |
| estimated cost | $0.794 | $0.786 | -1% |

Same Qwen3.5-9B, same seed, same wallclock cap, essentially same $ cost.
Bug fix + compaction converted "0 reward, 41 wasted menu turns" into
"0.132 reward, focused exploration".

### Qwen3.5-9B (v0.0.33 menu confusion → v0.0.40 menu-offloaded)

| metric | v0.0.33 (menu bug) | v0.0.40 (menu offloaded) | Δ |
|--------|--------------------:|--------------------------:|--:|
| **scout_reward** | 0.06 | **0.163** | **+172%** |
| **descend_calls** | 0 | **1** | first non-zero! |
| menu_option_calls | 62 (42% of turns!) | 0 (removed) | -∞ |
| inventory_item_calls | 17 | 0 (removed) | -∞ |
| autoexplore_calls | 10 | 107 | **+970%** |
| attack_calls | 12 (mostly wasted) | 1 (effective) | quality up |
| num_turns | 147 | 162 | +10% |

User flagged a v0.0.34 trace: "Really attack the little dog? [yn] (n)"
prompts looked superficially like menus, so the model called
`menu_option(0)` for them — 62 times per rollout. Fixes shipped
v0.0.35–45: removed `menu_option`/`inventory_item` from agent tools,
auto-dismissed menus + y/n prompts in `env_response`, added `=== HINT
===` block, type-coerced str/int args, accepted 'north'/'up' direction
aliases. Same Qwen3.5-9B, same seed. See
`experiments/results/menu_offload_v0035_to_v0040.md`.

### Claude Haiku 4.5: trace-driven format fixes

| metric | v0.0.24 (pre-format) | v0.0.30 (post-format) | Δ |
|--------|---------------------:|----------------------:|--:|
| **scout_reward** | 0.077 | **0.163** | **+112%** |
| descend_calls (wasted) | ~150 | **1** | -99% |
| num_turns | 201 | 172 | -14% |
| estimated cost | $5.72 | $5.21 | -9% |

After user reviewed `claude_haiku.log` and flagged "model seems confused
by format", I shipped UNDER PLAYER + GLYPH KEY + descend short-circuit.
Same Haiku 4.5, more than doubled exploration credit. See:
- `experiments/results/hosted_eval_v0014_vs_v0024_apples_to_apples.md`
- `experiments/results/hosted_eval_v0030_haiku_format_fix.md`
- `experiments/results/haiku_trace_analysis.md` (root-cause forensic)

## Token-cost story (the survey)

- A 150-turn Qwen 9B rollout was burning **4.3M input tokens = $0.79/run**.
  The bill is dominated by re-sending the tty grid every turn.
- I did a deep survey of 12 LM-agent harnesses (`docs/PROMPTING_SURVEY.md`)
  — Pokemon, Glyphbox, SWE-agent, OpenHands, Voyager, Cicero.
- Implemented 8 of 10 ranked recommendations (v0.0.17–24):
  obs compaction, history compaction, periodic SubLM belief-state,
  message RLE, adjacency block, journal diff, glyph-run encoding.
- **Measured savings (`experiments/exp15_token_savings.py`):**
  - per-turn obs: **25.7% smaller**
  - **cumulative prompt at turn 60: 89.8% smaller** (1925 vs 18840 tokens)
- Plot at `experiments/results/exp15_token_savings.png` — drop in for the
  slide.

## What I'd want from you

1. **Interface call** for v0.1: code-mode default or skill-mode default?
2. **Proposer architecture**: self-curricular vs frozen separate model?
3. **prime-rl SubLM wiring**: a 30-min walkthrough on how to point our
   `SubLM` ABC at your hosted inference endpoint.
4. **Compute alloc**: who pays for the first 1000-rollout training run?
   Estimate: 1000 rollouts × $0.07 (post-compaction) ≈ **$70**.

## Where to look

- Hub: <https://app.primeintellect.ai/dashboard/environments/jonathanliu/nethack>
- Replay viewer: open `tools/replay_viewer.html`, load
  `docs/onboarding/demo_trajectory.json`
- Onboarding: `docs/onboarding/` — 15 numbered docs, one per shipped fix
- Survey: `docs/PROMPTING_SURVEY.md`
- Hosted eval writeups: `experiments/results/hosted_eval_*.md`
- Version history with what each fixed: `docs/HUB_VERSIONS.md`
