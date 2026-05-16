# Trace-driven format fixes (v0.0.29 / v0.0.30)

User reviewed a 200-turn Claude Haiku 4.5 rollout at
`/Users/Fritz/Downloads/files/claude_haiku.log` and flagged: the model
kept failing to reach dlvl 2 from a fresh corridor_explore spawn — a task
that should be trivial. Three root causes surfaced.

## Root causes

### 1. `<` vs `>` glyph confusion

NetHack ASCII: `<` = stairs UP (to a previous dlvl), `>` = stairs DOWN
(to the next dlvl). Haiku repeatedly identified `<` as "stairs down":

> "ADJACENT section says E=< which means EAST=stairs down."

This is a learned-prior bug. Most non-roguelike contexts use `<` and `>`
as left/right or back/forward arrows — Haiku transferred that intuition.

### 2. The `@` overlays the tile beneath

NetHack draws the player sprite ON TOP of whatever tile they're on, so
the rendered map can't tell you "are you on stairs?" Haiku had to
remember the tile under `@` from the previous turn, but couldn't:

> "Perfect! I'm now standing on the stairs down (<)! Let me descend!"
> (in reality on a corridor next to the stairs)

### 3. Silent descend failure

When `descend` was called off a `>` tile, NLE silently no-op'd and the
old skill returned "Attempted to descend." — a success-shaped string.
Haiku spent ~150 turns convinced the descend was working but the game
was bugged.

## Fixes

### `=== UNDER PLAYER ===` block (v0.0.29)

Every obs now includes a line stating what tile `@` is on. Reads from
`obs.chars` (the raw 21×79 map, not the rendered tty) at the player's
position — `_TERRAIN_DESCRIPTIONS` maps the glyph to a human-friendly
label.

```
=== UNDER PLAYER === stairs DOWN (>) — call `descend` to go to next dungeon level
```

### Glyph key in SYSTEM_PROMPT (v0.0.29)

```
GLYPH KEY (memorize): `>` is stairs DOWN (call `descend` to go deeper).
`<` is stairs UP (does NOT take you to dlvl 2). `_` altar. `{` fountain.
The `@` is YOU and visually hides the tile you're standing on; check
the `=== UNDER PLAYER ===` line in each obs to know what's beneath you.
```

The strategy primer now walks the agent through the 3-step descent
loop explicitly.

### Adjacency stair labels (v0.0.30)

```
=== ADJACENT === N=. NE=. E=>(stairs DOWN) SE=. S=. SW=. W=. NW=.
```

Previously was `E=>`. Now spells out the meaning for the two highest-
load-bearing tiles (`>` and `<`). Same trick for altars/fountains.

### `descend` short-circuits with feedback (v0.0.30)

```python
if under and not under.startswith("stairs DOWN"):
    return SkillResult(
        [], f"Can't descend — you're standing on: {under}. "
            f"Find a '>' tile and step ON it first.",
        interrupted=True,
    )
```

Wastes 0 turns when called wrong. Tells the agent EXACTLY what to do.

## Verification

Tests:
- `tests/test_adjacent_hostiles.py::test_under_player_*` (6 tests for the
  new extractor including stairs UP / DOWN / floor / altar / no-player
  edge cases).

Expected hosted-eval outcome on v0.0.30:
- `descend_calls` should match the count of stairs found (no waste).
- `descent_reward > 0` on at least some rollouts — `corridor_explore`
  tier means dlvl 2 IS reachable; the only thing blocking it was the
  format ambiguity.

## Where to look

- `nethack_core/observations.py::extract_under_player`
- `nethack_core/observations.py::_TERRAIN_DESCRIPTIONS`
- `nethack_core/observations.py::_ADJACENT_LABEL_OVERRIDE`
- `environments/nethack/nethack.py::SYSTEM_PROMPT`
- `environments/nethack/nethack.py::format_observation_as_chat` (block
  order: UNDER PLAYER → ADJACENT → VISIBLE GLYPHS → MESSAGES)
- `nethack_core/skills.py::descend`
- `experiments/results/haiku_trace_analysis.md` for the full forensic
- `claude_haiku.log` for the original 200-turn trace
