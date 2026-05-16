# First successful hosted eval — Qwen3.5-9B vs v0.0.14

Run on 2026-05-15 22:06–22:17 EDT. Local eval (not `--hosted`) via Prime Inference.

## Headline

**End-to-end success.** No verifier-contract crashes. Model executed 144
tool calls across 146 turns, hit the 10min wallclock cap, achieved 0 reward.

This is the first eval since v0.0.0 that completes against the latest env
without throwing. Validates all the bug-fix work from Day 4.

## Numbers

| Field | Value |
|------|------|
| env version | 0.0.14 |
| model | Qwen/Qwen3.5-9B (pinference) |
| n × r | 1 × 1 |
| max_turns (cap) | 30 (passed via -x) |
| actual turns | 146 (cap not reached — wallclock timeout instead) |
| total tool calls | 144 |
| stop reason | timeout_reached (10min wallclock) |
| reward | 0.0 |
| input tokens | 4,274,253 |
| output tokens | 46,037 |
| cost | ~$0.79 |
| eval URL | https://app.primeintellect.ai/dashboard/evaluations/y3qmhrsriqtjb15bo35ytfj9 |

## Tool-call distribution

| skill | count | notes |
|------|-------|------|
| move_to | 42 | most-used; model preferred A* navigation |
| menu_option | 41 | suggests model is dealing with --More-- prompts a lot |
| move | 35 | single-step movement |
| attack | 10 | engaged combat |
| search | 6 | hunted for hidden passages |
| descend | 4 | tried to descend stairs |
| kick | 2 | broke locks/doors |
| autoexplore | 2 | tried automated exploration |
| inventory_item | 1 | one inventory selection |
| add_note | 1 | wrote one journal note |
| eat / quaff / read / pray / engrave / throw / pickup / recall / wiki_* | 0 | unused this rollout |

## Read

- The `max_turns=30` arg passed via `-x` was ignored — env default of 200
  was used. Worth investigating why `-x` didn't bind the env-side `max_turns`.
- 146 turns / 10min = ~4s/turn, dominated by Qwen3.5-9B inference latency
  on pinference.
- Cost is ~$0.79 per rollout at 9B. For a 5×3 sweep that's ~$12 — under
  the $20 budget but worth knowing.
- `menu_option_calls: 41` is suspiciously high. Likely the model hit lots
  of "--More--" prompts and wasted turns on menus instead of progress. A
  smaller model would do this even more.
- All my new survival skills (eat/pray/etc) appear in the tool schema but
  the agent didn't use them in 146 turns. Future improvement: give the
  agent a hunger / HP nudge in the system prompt.

## What this proves

1. Pydantic ToolCall shape, vf.UserMessage returns, return-just-messages
   contract — all working in production.
2. Defensive arg parsing handled whatever malformed calls Qwen emitted
   (no worker crash).
3. The new survival-skill schemas don't break tool-call generation.
4. `prime eval` correctly resolves `jonathanliu/nethack@latest` from the
   Hub and uploads results.

## Next eval ideas

1. **Bigger model** (qwen3.5-35b-a3b for tool-call quality at 3B active
   compute, ~$0.31/$1.80 per Mtok).
2. **Bigger sweep**: `-n 3 -r 3 --timeout 600` — 9 rollouts ≈ $7 at 9B.
3. **Try `--hosted`**: runs on Prime Cloud rather than local inference
   roundtrip, possibly faster.
4. **Try interface=code**: `-x '{"interface": "code"}'` to validate code
   mode in the wild.
5. **Try dynamic_subgoal tier**: `-x '{"tier": "dynamic_subgoal"}'`.
