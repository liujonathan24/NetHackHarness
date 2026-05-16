# Terminal outcome detection: death vs ascension from the tty

**Status:** Wired up in `environments/nethack/nethack.py` as of Day 2. Tested
in `tests/test_rewards.py`.

## The need

The `ascension_reward` (weight 1000) is the headline signal: +1 if the agent
wins NetHack, 0 otherwise. It's the literal definition of success.

But NLE's gym `terminated=True` flag fires for many reasons:
- Death (killed by, starved, petrified, drowned, ...)
- Ascension (offered the Amulet to the appropriate altar)
- Max steps reached
- `no_progress_timeout` (Challenge only)
- Quit

We need to disambiguate. Specifically: **is `terminated=True` a win or a
loss?** Without that distinction, `ascension_reward` can't pay out, and
post-mortem analytics ("which deaths happened on dlvl 4?") have nothing to
key on.

## What v0 had

```python
@vf.reward(weight=1000.0)
async def ascension_reward(state: vf.State) -> float:
    # TODO: proper ascension detection from game messages / blstats. For now,
    # terminate-with-positive-final-message proxy.
    return 0.0
```

It always returned 0. So even if an agent ascended, the rubric paid out the
scout + descent components and nothing else. The big-reward signal was dead.

## The fix

A new `_detect_terminal_outcome(obs, state)` runs after every step. It scans
the full tty rendering for one of two marker sets:

```python
_ASCENSION_MARKERS = (
    "ascended to demigod",
    "ascended to demigoddess",
    "with the Amulet",
    "offered the Amulet",
)
_DEATH_MARKERS = (
    "killed by",
    "starved to death",
    "petrified by",
    "drowned",
    "quit the game",
    "Do you want your possessions identified",  # the inventory dump on death
)
```

If any ascension marker appears, `state["ascended"] = True` and
`state["terminated"] = True`. Symmetric for death. The detection is
**absorbing**: once we've decided an episode outcome, subsequent calls don't
overwrite it.

`ascension_reward` then becomes:

```python
@vf.reward(weight=1000.0)
async def ascension_reward(state: vf.State) -> float:
    return 1.0 if state.get("ascended") else 0.0
```

`descent_reward` and `scout_reward` are unchanged — they fire on intermediate
state, not terminal.

## Why scan the tty instead of `blstats`?

NetHack's `blstats[25]` is a packed condition flag (`STONED | SLIMED | ...`).
There's no `IS_ASCENDED` bit. The unambiguous signal is the game's printed
end-screen, which is always rendered to tty before the env terminates.

A more efficient alternative is parsing `obs.message` (just the last message,
160 bytes) instead of the full tty. We use the full tty because:

1. The death/ascension banner is multi-line. The single-message buffer
   sometimes contains "Do you want your possessions identified? [yn]"
   without the cause-of-death line.
2. tty scanning costs ~20µs per step (24*80 = 1920 bytes of `chr()` + 10
   substring searches). The model inference is 1000x more expensive. The
   throughput overhead is invisible.

If we ever go env-bound (e.g., PufferLib vec backend), we'd switch to
message-only scanning and skip the full tty render.

## Edge cases

- **YASD ("Yet Another Stupid Death") messages.** Standard NetHack uses
  "killed by" for ~all death paths. Slime → "Turned to slime by". We catch the
  ones the tournament protocol recognizes and miss the long tail. Add as
  needed.
- **Identifications screen.** After death, NetHack asks "Do you want your
  possessions identified? [yn]". We treat the question itself as a death
  marker so the rollout terminates even if the player declines to answer.
- **Demigoddess vs Demigod.** Some role/race combos render gender-specific
  ascension banners. Both forms are in `_ASCENSION_MARKERS`.
- **Idempotency.** `_detect_terminal_outcome` early-returns if `ascended` or
  `died` is already set. NetHack will sometimes redraw the death screen
  multiple times as the player presses keys to dismiss prompts; we don't
  want a single ascension to oscillate.

## How to verify

```bash
uv run pytest tests/test_rewards.py -v
```

Four tests cover the death-from-tty, ascension-from-tty, idempotency, and
live-game (no markers) paths. The fixtures are synthetic tty arrays, so the
tests run without NLE.

End-to-end you'd need an actual long-running rollout, which we don't have a
fast probe for yet. Once we have the replay viewer (Day 5), an ascension
trajectory becomes a debuggable artifact.

## Future work

- **Death-cause taxonomy.** Pull the killer-monster name out of the "killed
  by" message and stash it in `state["death_cause"]`. Powers a post-mortem
  reward signal ("avoid newts on dlvl 1") and BALROG-style analytics.
- **Quit detection.** Currently lumped into "death" via `quit the game`.
  Might want to separate; quitting voluntarily is a bug, not a death.
- **`balrog_progression` reward.** Once we have the Dungeons-and-Data
  empirical (DL, XL) → ascend-probability table, expose it as an
  alternate reward function in the rubric.
