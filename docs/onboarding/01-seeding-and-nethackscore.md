# Why we wrap `NetHackScore-v0`, not `NetHackChallenge-v0`

**Status:** Wired up in `nethack_core/env.py` as of Day 2. Tested in `tests/test_seeding.py`.

## The problem

Our whole pitch — *"reproducible NetHack episodes for LM agent training"* — only
works if we can seed the underlying NLE deterministically. The verifiers env
relies on `(core_seed, disp_seed)` plus a recorded action sequence being enough
to replay any rollout byte-identically.

NLE 1.3 ships several gym-registered tasks (run `gymnasium.envs.registry` to
see them all):

```
NetHack-v0
NetHackChallenge-v0   <-- the famous one, the original 2021 Challenge wrapper
NetHackEat-v0
NetHackGold-v0
NetHackOracle-v0
NetHackScore-v0       <-- our substrate
NetHackScout-v0
NetHackStaircase-v0
NetHackStaircasePet-v0
```

`NetHackScore` is the parent class of nearly all of them
(`nle/env/tasks.py:18`). It implements the score-based reward, exposes a
restricted 23-action set, and leaves seeding alone.

`NetHackChallenge` (in the same file at line 287) inherits from `NetHackScore`
and adds three deliberate hardenings:

1. Random role/race/alignment at episode start.
2. A `no_progress_timeout` (default 10,000 steps) that terminates rollouts
   stuck without making progress.
3. **An anti-tool-assisted-speedrun seed lock.** In `__init__` it monkey-patches
   `self.nethack.set_initial_seeds` to a function that raises:

   ```python
   def f(*args, **kwargs):
       raise RuntimeError("Should not try changing seeds")
   self.nethack.set_initial_seeds = f
   ```

   It also overrides the gym `seed()` method to raise. There is no way to
   seed a `NetHackChallenge` instance.

The first version of our wrapper defaulted to `NetHackChallenge-v0`, which
killed reproducibility (every `seed()` call raised `RuntimeError("Should not
try changing seeds")`).

## The fix

`nethack_core/env.py` defaults to `task_name="NetHackScore-v0"`. The change is
one line plus a kwarg gate: `no_progress_timeout` is a NetHackChallenge-only
constructor argument, so we only pass it through when the task name contains
`"Challenge"`:

```python
make_kwargs: dict[str, Any] = {
    "observation_keys": self._observation_keys,
    "max_episode_steps": max_episode_steps,
}
if "Challenge" in task_name:
    make_kwargs["no_progress_timeout"] = no_progress_timeout
self._env = gym.make(task_name, **make_kwargs)
```

## What we give up

`NetHackScore` does *not* randomize role/race/alignment. The default character
is whatever NetHack picks from the player-name heuristic — in practice you'll
see `Agent the Monk (neutral male human)` over and over.

That's fine for training: the curriculum will eventually want explicit control
over the character anyway (Valkyrie for the easy ascensions, Wizard for
harder), and we can pass `character=` kwarg through to NLE once we wire that
up (`env.py::reset` already has a TODO marker).

If you need NetHackChallenge specifically — e.g., to run a BALROG eval against
their exact protocol — pass `task_name="NetHackChallenge-v0"` explicitly. You
won't get reproducible seeding, which is correct because the Challenge defines
the no-seed policy.

## How to verify

```bash
uv run pytest tests/test_seeding.py -v
```

The four tests:

- `test_seed_before_reset_enforced` — sanity check; `reset()` without `seed()`
  raises a clear `RuntimeError`.
- `test_seed_then_reset_works` — `seed(42,42)` then `reset()` returns
  `meta.seeds == (42, 42)` and a 24x80 tty.
- `test_reproducibility_with_same_seed` — **the load-bearing one.** Two envs
  with the same seed and the same action sequence produce byte-identical
  rewards and tty hashes.
- `test_different_seeds_produce_different_episodes` — two different seeds
  diverge.

If the reproducibility test ever fails on main, that's an entropy leak — you
have a regression. Look for: a new random call without a passed seed, a
non-deterministic ordering (set iteration), or a clock-based default
somewhere.

## References

- NLE source: `nle/env/tasks.py:287` (NetHackChallenge) and `:18` (NetHackScore)
- Sartak, "Predicting and controlling NetHack's randomness" (2009) —
  background on the core/disp RNG split
- pellsson, SWAGGINZZZ (2018) — the 7m15s ascension TAS that motivates the
  Challenge's anti-seeding hardening
