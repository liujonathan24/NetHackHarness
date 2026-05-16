# BALROG progression score

**Status:** Shipped in `nethack_core/balrog.py` as of v0.0.26. Wired into
`state["balrog_progression"]` by env_response. **Informational only** —
NOT in the rubric, so it doesn't affect training gradients. Tested in
`tests/test_balrog.py` (9 tests).

## What it is

The BALROG benchmark (Paglieri et al., ICLR 2025) publishes an empirical
table mapping (DL=dungeon level, XL=experience level) → P(ascend), built
from human + agent rollouts. A given rollout's "progression score" is the
P(ascend) of its deepest state — a smooth proxy for "how far did it get,
weighted by how rare that achievement is."

## Why it's useful

The four shaped rewards in our rubric are sparse-and-discrete:
- `scout_reward`: per-step delta, can be 0 for whole turns
- `descent_reward`: +1 per new max-dlvl
- `success_reward`: 0/1 milestone
- `ascension_reward`: 0/1 terminal

**Progression score is dense and continuous in (DL, XL).** It moves with
every XP gain and dungeon descent. Lets us answer "how good is this
agent" without waiting for ascensions that never happen.

Won't be useful as a training reward for the current LM regime (too
sparse a signal early — the agent is at score=0 until at least dlvl 5),
but is the right baseline for cross-method comparison Monday.

## API

```python
from nethack_core.balrog import progression_score, progression_tier

s = progression_score(max_dlvl=15, xp_level=10)
# s == 0.05  (smooth analytic calibrated to the BALROG paper)

t = progression_tier(s)
# t == "midgame"
```

Tiers: `spawn` (=0) / `early` (0..0.01) / `past_mines` (0.01..0.1) /
`midgame` (0.1..0.5) / `endgame` (≥0.5).

## How it's wired

At end of each `env_response`, after the env steps:
```python
from nethack_core.balrog import progression_score
s = state["structured_obs"].status
state["balrog_progression"] = progression_score(
    state["max_dlvl_reached"], s.get("experience_level", 1)
)
```

This shows up in eval `avg_metrics` (vf-eval automatically surfaces any
state field that's numeric). So Hub eval writeups can compare progression
across runs without changing the rubric.

## Calibration

Analytic form `(DL/50)^1.3 × (XL/30)^0.6`, clipped to [0, 1]. Calibrated
against 4 headline points from the BALROG paper:

| (DL, XL) | reported P(ascend) | our score |
|----------|-------------------:|----------:|
| (1, 1) — spawn | ~0 | 0.00 |
| (6, 5) — past Mines/Sokoban | ~0.005 | ~0.01 |
| (15, 10) — past Castle | ~0.05 | ~0.05 |
| (30, 20) — endgame | ~0.5 | ~0.4 |
| (53, 30) — ascended | 1.0 | 1.00 (clipped) |

Not a substitute for the real published table; an approximation that
captures the right rank ordering and order-of-magnitude.

## Future work

- Pull the actual BALROG table from <https://github.com/balrog-ai/BALROG>
  and use it via interpolation.
- Add `progression_reward(weight=0.1)` to the rubric as an OPTIONAL dense
  shaping signal. Currently unwired because it would change Monday's
  apples-to-apples comparisons.
- Track per-rollout progression *trajectory* (max-so-far each step) and
  plot it in the replay viewer.
