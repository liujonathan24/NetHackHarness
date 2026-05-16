# Haiku trace analysis — why the model couldn't reach dlvl 2

User flagged: "How has nothing gone to second floor yet? ... seems like
the model may not understand the format - it seems confused."

Read the trace at `/Users/Fritz/Downloads/files/claude_haiku.log` (3540
lines, ~200 turns). Three confusion patterns surfaced.

## Bug 1: stairs-up vs stairs-down conflation

Repeated assertions like:
> "The ADJACENT section says E=< which means EAST=stairs down."
> "I see! There's a `<` to my east — that's the stairs down!"

`<` is **stairs UP** in NetHack ASCII (goes to a *previous* level). `>`
is stairs DOWN. The model was navigating to `<` tiles, calling `descend`
on/near them, and going nowhere (or going back to dlvl 1).

## Bug 2: @ overlays the tile it's on

The model couldn't tell when it WAS on a stairs tile because the `@`
sprite covers everything beneath it. Sequences like:
> "Perfect! I'm now standing on the stairs down (<)! Let me descend!"
> (descend fails — they were on a corridor, NOT stairs)

## Bug 3: silent descend failure

When `descend` was called off-tile, it returned "Attempted to descend."
— a non-informative success-shaped string. Model thought the descend
worked and was confused when the next obs showed the same level.

## Fixes shipped (local; needs `prime login` to push to Hub)

### v0.0.29 (on Hub)
- **`=== UNDER PLAYER ===` block** added to every obs. Always shows
  what tile the `@` is hiding ("stairs DOWN (>)", "stairs UP (<)",
  "floor (.)", "altar (_)", etc.). New `extract_under_player` in
  `nethack_core/observations.py`.
- **System-prompt GLYPH KEY** added explicitly stating `>` is down,
  `<` is up, `@` hides the tile beneath. Walks the agent through the
  3-step "find > → step on → descend" loop.
- 21 terrain glyphs mapped in `_TERRAIN_DESCRIPTIONS` (altar, fountain,
  weapon, scroll, etc.).

### v0.0.30 (local — push when auth restored)
- **`descend` short-circuits with friendly feedback** when `under_player`
  is not stairs-down. Message: `"Can't descend — you're standing on:
  floor (.). Find a '>' tile and step ON it first."`
- **`descend` schema** rewrites to point at `=== UNDER PLAYER ===` as
  the authoritative check.

## Expected improvement

The next eval should show:
1. **Zero wasted descend calls** (short-circuit on non-stairs).
2. **No more `<` vs `>` confusion** (glyph key + under_player).
3. **descent_reward > 0** on at least some rollouts — the actual blocker
   was UI ambiguity, not strategic capability.

## Where to look

- `nethack_core/observations.py::extract_under_player`
- `nethack_core/observations.py::_TERRAIN_DESCRIPTIONS`
- `environments/nethack/nethack.py::SYSTEM_PROMPT` (glyph key section)
- `environments/nethack/nethack.py::format_observation_as_chat` (block
  ordering: UNDER PLAYER → ADJACENT → VISIBLE GLYPHS)
- `nethack_core/skills.py::descend` (short-circuit + better schema desc)
