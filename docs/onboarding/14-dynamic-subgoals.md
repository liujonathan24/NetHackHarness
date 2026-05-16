# Dynamic subgoal curriculum

**Status:** Wired end-to-end as of 2026-05-15. The autoresearch axis from
the project plan: *can an LLM design its own NetHack curriculum given the
wiki?*

## What it is

A new tier `dynamic_subgoal` plus the substrate to support it:
`nethack_core/subgoals.py` (proposer + predicate compiler). Instead of
hard-coding a `success_milestone` for the tier, `setup_state` runs an
`SubgoalProposer.propose(role, obs)` call at episode start, gets back a
`SubgoalSpec`, compiles its `termination_check` into a `Milestone`, and
swaps it into the spec.

## The DSL

A subgoal is two parts:
- `objective` — natural-language description (pinned to journal as the
  agent's pinned objective).
- `termination_check` — a small structured dict:

```python
{"kind": "message_substring", "text": "Welcome to Mine Town"}
{"kind": "tty_substring",     "text": "altar"}
{"kind": "dlvl_at_least",     "n": 3}
{"kind": "any_glyph_visible", "glyphs": [42, 100, 1234]}
```

Add a new `kind` by extending `_PREDICATE_BUILDERS` in `subgoals.py`. Keep
the DSL deliberately narrow — the proposer LLM only needs to learn this
small vocabulary.

## How to plug in a real LM proposer

Subclass `SubgoalProposer` and pass it via state:

```python
class PrimeRLSubgoalProposer(SubgoalProposer):
    def __init__(self, client):
        self.client = client
    def propose(self, role, obs=None, max_dlvl=5):
        prompt = build_prompt(role, obs, wiki_summary())
        response = self.client.complete(prompt)
        return parse_response(response)  # → SubgoalSpec

# Then before env.setup_state runs:
state["subgoal_proposer"] = PrimeRLSubgoalProposer(prime_rl_client)
```

The default `OfflineSubgoalProposer` is deterministic (role → canned
spec). Tests use it; production swaps in the LM-backed version.

## Why this is the autoresearch axis

Three properties no other PI residency project hits:
1. **The curriculum itself is learned.** The proposer's quality (was the
   subgoal achievable, useful, progress-aligned?) becomes a meta-RL
   signal back to the proposer.
2. **It generalizes.** Any procedurally-generated game with a wiki can
   plug in: replace the wiki snapshot, keep the proposer architecture.
3. **It composes with Track B (code mode).** The proposer is itself a
   sub-LM call (one of the `nh.summarize/plan/recall_lm` family). Same
   substrate as the in-rollout sub-LMs.

## Verification

```bash
pytest tests/test_subgoals.py -v   # 10 tests
```

Smoke an actual rollout:
```python
from nethack import load_environment
env = load_environment(tier="dynamic_subgoal")
# At episode start, state["dynamic_subgoal"]["objective"] is a real string,
# state["spec"].success_milestone is a callable that fires when the
# objective is achieved.
```

## Future work

- **Real proposer.** Wire `PrimeRLSubgoalProposer` to the inference server.
- **Quality signal.** Track proposed-subgoal achievement rate per proposer
  version; use as a reward for proposer fine-tuning.
- **Curriculum mixing.** Sample tier ∈ {static milestones, dynamic_subgoal}
  with a learned weighting based on which produces faster training progress.
