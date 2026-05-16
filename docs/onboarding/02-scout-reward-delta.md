# Scout reward: from "cumulative" to "per-step delta"

**Status:** Fixed in `environments/nethack/nethack.py` as of Day 2. Tested in
`tests/test_rewards.py`.

## The bug

`scout_reward` is the densest signal in our rubric — one reward unit per newly
revealed dungeon tile this turn. Dense exploration shaping is what makes the
solo-combat tier trainable at all; without it, the agent gets a single
sparse `descent_reward` payout for finding stairs and not much else.

The v0 implementation looked like this:

```python
@vf.reward(weight=1.0)
async def scout_reward(state: vf.State) -> float:
    """One reward unit per newly-scouted tile in the current step."""
    return float(len(state.get("scout_tiles_seen", set()))) / 1000.0
```

`state["scout_tiles_seen"]` is the cumulative set of `(dlvl, x, y)` tuples ever
seen this episode. Returning `len(set)` means **the reward is monotonically
non-decreasing across steps, regardless of what the agent does**. Standing
still pays the same as exploring (until the cumulative count happens to tick
up from monster movement, which it sometimes does).

Specifically, a 100-step rollout that revealed 50 tiles on turn 1 and stood
still for the next 99 turns returns rewards of:

```
[0.050, 0.050, 0.050, ... ] = total 5.0
```

But a rollout that revealed 1 tile per turn for 50 turns returns:

```
[0.001, 0.002, 0.003, ..., 0.050, 0.050, ...] = total ~3.7
```

The agent is *worse off* for exploring incrementally. RL's credit assignment
amplifies the wrong policy.

## The fix

Capture the set size before and after the step, store the delta, return that.

In `env_response`, around the env-stepping loop:

```python
scout_before = len(state["scout_tiles_seen"])
# ... step the env, update scout_tiles_seen ...
scout_after = len(state["scout_tiles_seen"])
state["scout_delta"] = scout_after - scout_before
```

In the reward function:

```python
@vf.reward(weight=1.0)
async def scout_reward(state: vf.State) -> float:
    return float(state.get("scout_delta", 0)) / 1000.0
```

Now standing still pays 0 and exploring 5 new tiles pays 0.005 — the agent
sees a flat reward landscape for inaction and a steady upward gradient for
exploration. RL gets the right signal.

## What we left alone

- The 1/1000 normalization. We may want to tune this once we have curriculum
  data, but keep the API stable for now.
- `scout_tiles_seen` is keyed by `(max_dlvl_reached, x, y)`, not `(dlvl, x, y)`.
  That's a separate latent bug: tiles seen on different dungeon levels but the
  same (x,y) collide once you go up-and-down. We'll fix it when the
  curriculum starts producing multi-level runs.
- The `b" "`/`b"\x00"` blacklist (`if ch not in (b" ", b"\x00")`) excludes
  unseen / out-of-FOV tiles. That's correct.

## How to verify

Mocked:

```bash
uv run pytest tests/test_rewards.py::test_scout_reward_returns_delta_not_cumulative -v
uv run pytest tests/test_rewards.py::test_scout_reward_zero_when_no_new_tiles -v
```

End-to-end (will need an OpenAI-compatible API key):

```bash
uv run vf-eval nethack -m gpt-4.1-mini -n 1 -r 1 -a '{"tier":"empty_room"}'
```

Look at the rubric breakdown — scout component should be a single small float,
not a per-step accumulator.

## Related

- The pattern (capture pre, capture post, return delta) is the same one we'll
  want to use for `descent_reward` if we ever change it from "fires once per
  new max dlvl" to "tracks dlvl entropy" or similar.
- Glyphbox (Jan 2026) used a similar new-tile-per-step shaping and got GPT 5.2
  to dlvl 10 / 12.56% BALROG progression. The reward density is the unsexy
  half of the LM-agent equation.
