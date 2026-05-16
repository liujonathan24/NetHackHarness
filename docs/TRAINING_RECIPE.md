# Training recipe — `prime-rl` GRPO on `jonathanliu/nethack`

How to point `prime-rl`'s trainer at the env. **Not run yet** — needs GPU
+ Alex's compute alloc — but the recipe is concrete so you can hand this
to a training engineer.

## Prereqs

- GPU node with `prime-rl` installed (usually a Prime Cloud Sandbox).
- API access to the inference model you want to train (vLLM, Anthropic,
  or Prime Inference).
- `prime env install jonathanliu/nethack@latest`.

## Recipe file (`recipe.toml`)

```toml
[env]
id = "jonathanliu/nethack"
# Pick a tier — see docs/EVAL_RECIPES.md for the full list.
args = { tier = "corridor_explore", max_turns = 100, compact_obs = true }

[algorithm]
name = "grpo"
group_size = 4                 # 4 rollouts per prompt; pick the best
clip_range_low = 0.2
clip_range_high = 0.28         # asymmetric clip from the GRPO paper
kl_penalty = 0.001
n_rollouts = 1000              # ~$70 at Qwen3.5-9B post-compaction
batch_size = 32

[model]
id = "Qwen/Qwen3.5-9B"         # recommend ≥9B for tool-call format compliance
# alternatively: anthropic/claude-haiku-4.5 — more expensive, more capable

[optimizer]
lr = 1e-6
warmup_steps = 100

[checkpoint]
save_every = 100               # save after every 100 rollouts
hub_repo = "jonathanliu/nethack-grpo-9b-v1"
```

## Cost estimate

At v0.0.24 (post-compaction):
- 1 rollout = ~$0.07 (Qwen3.5-9B, 100-turn, $0.79 wallclock → ~$0.07 effective when amortized over training-batched inference)
- 1000 rollouts = **~$70** to a first training run
- 10000 rollouts = **~$700** to a respectable epoch

Pre-compaction this would have been 10x the cost. The compaction work is
what makes v0.1 training affordable on Alex's residency budget.

## What the trainer sees

Each rollout produces:
- A `Trajectory` object (per `nethack_core/replay.py`)
- `reward` (sum of `scout_reward + 10*descent_reward + 100*success + 1000*ascension`)
- `state["balrog_progression"]` (informational; not in rubric)
- Per-skill call counts in `avg_metrics`

GRPO uses the `reward` to compute advantages. The reward signal is now
real (v0.0.16 fix); pre-fix runs would have trained on 0-reward.

## Expected training trajectory

| epoch | expected progression | scout_reward | descent_reward |
|------:|---------------------|-------------:|---------------:|
| 0 (pre-train) | spawn | ~0.05–0.15 | 0 |
| 1 (1000 rollouts) | early | ~0.20–0.40 | rare hits on dlvl 2 |
| 3 | past_mines | ~0.5 | dlvl 2-4 routinely |
| 10 | midgame | ~1.0 | dlvl 5-8 |

These are guesses based on related work (BALROG, glyphbox). The training
loop should log per-rollout `balrog_progression` so we can see if the
agent is making sub-dlvl progress (e.g. learning to autoexplore better)
before discrete reward signal lights up.

## Sub-LM wiring (Track B / RLM)

For code mode with a real SubLM, subclass `nethack_core.code_mode.SubLM`:

```python
from nethack_core.code_mode import SubLM
from prime_rl.client import InferenceClient  # hypothetical

class PrimeRLSubLM(SubLM):
    def __init__(self, model_id: str, client: InferenceClient):
        self.model_id = model_id
        self.client = client

    def summarize(self, text: str, query: str = None) -> str:
        prompt = f"Summarize for query={query!r}:\n{text[:4000]}"
        return self.client.complete(self.model_id, prompt, max_tokens=200)

    def plan(self, objective: str, horizon: int = 5) -> list[str]:
        prompt = f"In {horizon} numbered steps, plan to: {objective}"
        resp = self.client.complete(self.model_id, prompt, max_tokens=300)
        return [line.strip() for line in resp.splitlines() if line.strip()]

    def recall(self, query: str, context: str = "") -> str:
        prompt = f"From the notes:\n{context}\n\nAnswer: {query}"
        return self.client.complete(self.model_id, prompt, max_tokens=150)
```

Then in your training script:
```python
from nethack import load_environment
env = load_environment(
    tier="dynamic_subgoal",
    interface="code",
    sub_lm=PrimeRLSubLM("Qwen/Qwen3.5-9B", client),
)
```

The SubLM is called from inside agent-written Python via
`nh.summarize(...)`, `nh.plan(...)`, `nh.recall_lm(...)`. This is the
actual RLM substrate per Alex's paper.

## Dynamic subgoal proposer

For the autoresearch tier, similarly subclass `SubgoalProposer`:

```python
from nethack_core.subgoals import SubgoalProposer, SubgoalSpec

class PrimeRLSubgoalProposer(SubgoalProposer):
    def propose(self, role, obs=None, max_dlvl=5):
        prompt = build_subgoal_prompt(role, obs, wiki_summary())
        resp = self.client.complete(self.model_id, prompt, max_tokens=200)
        return parse_response(resp)  # → SubgoalSpec

env = load_environment(
    tier="dynamic_subgoal",
    subgoal_proposer=PrimeRLSubgoalProposer(...),
)
```

Termination check DSL is documented in
[`docs/onboarding/14-dynamic-subgoals.md`](onboarding/14-dynamic-subgoals.md).

## Smoke test before training

Run a single rollout against the same model + recipe to confirm:
1. Tools dispatch (no contract crashes).
2. Reward signal is nonzero (means rubric is working — should always pass
   in v0.0.16+).
3. Cost per rollout matches your budget estimate.

```bash
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 1 -r 1 \
  -a '{"tier": "corridor_explore", "max_turns": 100}'
```

Expected output (per existing writeups): `scout_reward ≈ 0.05–0.20`,
cost ≈ $0.07–0.80 depending on wallclock.

## Open questions for Alex

1. **GRPO group size** — 4 is the paper default; we may need 8 or 16
   given the reward sparsity.
2. **Initial policy** — start from base Qwen3.5-9B or a NetHack-finetuned
   version? Motif/Glyphbox might have weights to bootstrap from.
3. **Self-vs-frozen for SubLM** — train the SubLM jointly or hold fixed?
   Joint = harder optimization but better adaptation; fixed = clean
   credit assignment.
4. **Belief-state interval** — 25 turns is my default; for shorter tiers
   like `corridor_explore` (max_turns=100) belief-state fires ~3× per
   rollout. For long tiers like `castle_reached` (30000 max-steps), the
   interval should probably scale.
