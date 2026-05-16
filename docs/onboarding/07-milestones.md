# Milestones: Pokemon-route-style termination predicates

**Status:** Shipped in `nethack_core/milestones.py` as of Day 3. Tested in
`tests/test_milestones.py`.

## Why these aren't just MiniHack levels

The original design proposed two tiers — `corridor_explore` (3-room maze)
and `mini_dungeon` (3 floors) — that were synthetic MiniHack des-files. The
problem: synthetic MiniHack envs are *artificially* contained. They don't
have the intrinsic structure that makes NetHack a Pokemon-style game.

Pokemon's curriculum works because the milestones are *built into the
game*: Brock, Misty, Lt. Surge, ... Each one is a recognizable event with
unambiguous "I beat it" signal. NetHack has the same shape:

- **Mine Town** (Mines branch, ~dlvl 5–8) — first major shopping hub.
- **Sokoban** (~dlvl 6–9) — a side branch with 4 puzzle levels, capped by
  one of two artifact prizes.
- **The Oracle** (main dungeon, ~dlvl 5–9) — pay-to-consult hint system.
- **Castle / Quest / Vlad / Amulet** — late-game stuff, stretch.

A "tier" that ends when one of these milestones is reached is a curriculum
rung the agent can actually visualize. It also lets us compare progression
to BALROG's table directly.

## The API

```python
@dataclass
class Milestone:
    name: str                                # slug for curriculum lookup
    description: str                         # rubric / system-prompt text
    check: Callable[[obs, state], bool]      # called every step
```

`check(obs, state)` returns `True` once the milestone has fired (it's an
absorbing state — uses a `state["milestone_<name>"] = True` flag so a single
match is enough to terminate even if the message scrolls off-screen).

Three built-ins, plus a factory:

```python
mine_town_milestone              # Mines branch + "Welcome to Mine Town"
sokoban_complete_milestone       # Sokoban hero / cheating message
oracle_consult_milestone         # "Oracle proclaims" / "Oracle whispers"
reach_dlvl_milestone(n)          # main dungeon, dlvl >= n
```

And composition:

```python
any_of(m1, m2, ...)              # fires when ANY child fires
all_of(m1, m2, ...)              # fires when EVERY child has fired at least once
```

## Why conservative substring matching

A milestone that fires when it shouldn't ends the episode early — that's a
bug worse than a slow episode. So the detectors:

- **Anchor on specific game messages**, not heuristics. "Welcome to Mine
  Town" is a NetHack-printed string, not a fuzzy match.
- **Cross-check the dungeon branch** where applicable. `mine_town_milestone`
  requires `dungeon_number == DUNGEON_MINES`. A spurious "Mine Town"
  reference in a shop sign in the main dungeon won't fire it.
- **Are absorbing.** Once `state["milestone_<name>"] = True`, subsequent
  checks return True without rescanning. Cheap, and prevents oscillation
  if the message scrolls past.

False *negatives* (missing a real milestone) are tolerable: the curriculum
falls back to `max_episode_steps` and ends the episode anyway. The agent
loses some reward but no data is corrupted.

## What's NOT a milestone (and why)

- **Picking up the Amulet of Yendor.** That's already covered by
  `ascension_reward` (see `05-terminal-outcome-detection.md`). Don't
  duplicate.
- **Killing the quest leader.** No reliable message; the leader-kill messages
  are role-specific. Skip until we have per-role tuning.
- **Reaching dlvl N in the Mines.** The `reach_dlvl_milestone` factory only
  fires in the main dungeon (`DUNGEON_MAIN == 0`). The Mines have their own
  level numbering and you can be on "dlvl 5" in the Mines while being
  topologically very different from main dlvl 5.

## Where this plugs into curriculum

`curriculum.py` will (in a follow-up commit) use these to define the
real-NLE-with-stopping tiers:

```python
# pseudocode for the upcoming curriculum.py edit
TierSpec(
    name="mines_to_minetown",
    description="Reach Mine Town in the Gnomish Mines.",
    nle_task="NetHackScore-v0",
    success_milestone=get_milestone("mine_town"),
    max_episode_steps=8_000,
)
```

The verifiers wrapper's `env_response` will check
`spec.success_milestone.check(obs, state)` after each step and treat a True
result as a positive termination (currently `state["terminated"] = True`,
later extended with a `state["succeeded"]` flag for the rubric).

## How to verify

```bash
uv run pytest tests/test_milestones.py -v
```

16 tests cover each built-in milestone, the dungeon-branch cross-check, the
idempotency / absorbing property, the `reach_dlvl_milestone` factory, and the
`any_of` / `all_of` composition. All synthesized observations — no NLE.

## Future work

- **Dungeons-and-Data calibration.** Once we ingest the human-trajectory
  dataset (NLD-NAO), we can compute the *empirical* time-to-milestone
  distribution for each level. That gives us realistic `max_episode_steps`
  defaults per tier rather than the round-number guesses currently in code.
- **BALROG progression as a milestone.** The (DL, XL) → ascend-probability
  lookup is also a milestone-shaped predicate: "reach (DL, XL) such that the
  human ascend-prob exceeds 5%". Expose as `balrog_milestone(threshold)`.
- **Quest milestone.** Detecting quest completion needs per-role message
  matching. Worth doing once we control the character string and know which
  role we're playing.
- **Dynamic milestones from the LLM proposer** (the autoresearch axis in
  the project plan). Same `Milestone` interface, but the `check` is
  compiled from an LLM-proposed termination spec.
