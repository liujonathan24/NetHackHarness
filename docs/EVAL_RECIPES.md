# vf-eval / prime-eval recipes

Quick-reference for running rollouts against the Hub-deployed env. Updated
for **v0.0.16+** (post reward-bugfix). Use **v0.0.16 or later** for real
reward numbers — earlier versions had a rubric-side bug that always
returned 0 for `scout_reward` and `descent_reward` at score time.
See `docs/HUB_VERSIONS.md` row v0.0.16 for the post-mortem.

Token cost can be punishing: a single 10-min rollout against Qwen3.5-9B
burned **4.3M input tokens** at $0.18/Mtok = ~$0.79. The dominant cost is
re-sending the full tty grid every turn. We have token-reduction strategies
mapped out in `docs/PROMPTING_SURVEY.md`; not yet implemented.

## TL;DR

```bash
# Local pytest sanity (no API keys needed)
pytest tests/ -q
python experiments/run_all.py

# Local LM eval (needs OPENAI_API_KEY or PI_API_KEY)
vf-eval nethack -m gpt-4.1-mini -n 1 -r 1 \
  --endpoints configs/endpoints.toml

# Local eval (DEFAULT — runs on your laptop, cheaper, faster wallclock cap)
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 1 -r 1 --timeout 600
# Results upload to https://app.primeintellect.ai/dashboard/evaluations/<id>
# (URL printed at end of eval). Individual entries; may not appear grouped
# under the env page unless you filter by env in the user's eval list.

# Hosted eval (Prime Cloud — appears in env's evaluations tab; ≥120min timeout
# floor; pricier because it runs server-side on Prime infra). Use only when
# you need the eval visible to others or as a build artifact.
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 5 -r 3 \
  --hosted --eval-name "my-run" --timeout-minutes 120

# Override env args (tier, interface, max_turns) — NOTE: use -a, NOT -x
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 1 -r 1 \
  -a '{"tier": "dynamic_subgoal", "interface": "code", "max_turns": 30}'
```

## Picking a model

| Model | Why | Cost order |
|-------|-----|-----------|
| gpt-4.1-mini | Smartest cheap option; OpenAI tool format works without compat shims | $$ |
| claude-haiku-4-5 | Fast, $0.25/$1.25 per Mtok, very good at tool use | $$ |
| Qwen/Qwen3-32B | Free on pinference, decent tool use | free |
| Qwen/Qwen3.5-2B | Free, but generates malformed tool calls; useful only as a smoke test | free |
| Qwen/Qwen3.5-0.8B | Don't bother — too small for the schema; used to verify the env doesn't crash | free |

Rule of thumb for the Monday demo: `gpt-4.1-mini` if you want a real
reward signal in 5 minutes; `Qwen/Qwen3-32B` if you want free; anything
≤ 2B is a substrate test, not a reward test.

## Useful args

`prime eval jonathanliu/nethack -m <model> [...]`

- `-n <int>` — number of distinct (tier, seed) examples. Default 5.
- `-r <int>` — rollouts per example (for variance estimation). Default 3.
- `-a '{"tier": "..."}'` — override env args (passes to `load_environment(...)`).
  Available tiers via `python -c "from nethack_core.curriculum import list_tiers; print(list_tiers())"`.
  Use this for `tier`, `interface`, `max_turns`, `n_examples`, `seed`.
  **Don't use `-x`** for these — `-x` is `--extra-env-kwargs` and goes to
  `env.set_kwargs()` AFTER construction, which can't change the tools list
  (so `interface="code"` won't actually swap to code mode).
- `--endpoints configs/endpoints.toml` — local-only flag for `vf-eval`;
  not needed for `prime eval` (Hub manages endpoints).
- `--max-turns <int>` — per-rollout LM-turn cap. Default 200.

## Tier picks

| Tier | NLE task | Termination | When to use |
|------|---------|------------|-------------|
| `corridor_explore` | NetHackScore-v0 | reach dlvl 2 | DEFAULT — fastest signal, no MiniHack |
| `mini_dungeon` | NetHackScore-v0 | reach dlvl 3 | Slightly harder; same model, longer rollouts |
| `mines_to_minetown` | NetHackScore-v0 | reach Mine Town | Long-horizon; needs 8k env steps |
| `dynamic_subgoal` | NetHackScore-v0 | LLM-proposed | The autoresearch axis. The objective gets pinned to the journal |
| `solo_combat` | MiniHack-Skill-Custom-v0 | descend | Requires `pip install nethack[minihack]` |
| `full_nle` | NetHackScore-v0 | ascend | Real game; expect 0 reward unless model is gpt-4.1+ |

## Common errors and fixes

### "AttributeError: 'ToolCall' object has no attribute 'function'"
Pre-v0.0.4 environments. Re-pull: `prime env pull jonathanliu/nethack@latest`
or update the local env package.

### "Environment 'MiniHack-Skill-Custom' doesn't exist"
You picked a MiniHack tier without installing minihack. Either:
```bash
pip install 'nethack[minihack]'  # adds samvelyan/minihack git dep
```
or change the tier to one of the NetHackScore-based tiers above.

### "Invalid env_response item type: list"
Pre-v0.0.6 environments. Same fix: re-pull.

### Worker hangs at "Active tasks: 5 (W0: 5)" forever
Slow LM responses, not a hang. Each turn is one LM round-trip; for a
0.8B model on free pinference, expect 100-300ms per turn × ~100 turns ×
15 rollouts = ~5-10 minutes total. The `Lag: ... median=Xms` line is the
real progress signal — it grows monotonically as more turns finish.

### "endpoints.toml not found"
Pass `--endpoints configs/endpoints.toml` (vf-eval only).

## Reading the output

Each rollout writes to `outputs/evals/<model>/<hash>/`:
- `env_worker_0.log` — server-side log including any tracebacks
- `env_server.log` — ZMQ broker log (rarely interesting)
- `metadata.json` — per-rollout reward + config (only on success)

For a failed rollout, the most useful thing is the worker log. Grep for
`ERROR` first:

```bash
grep -A 20 ERROR outputs/evals/*/*/env_worker_0.log | head -50
```

## Going from "eval works" to "training"

`vf-eval` is for evaluation. For training, the env is consumed by
`prime-rl`'s GRPO/PPO trainer. The verifiers env interface is the same;
just the consumer changes. See `prime-rl`'s docs for the recipe schema.

The env itself is the same artifact for both — there's no separate
training mode. That's the whole point of the verifiers contract.
