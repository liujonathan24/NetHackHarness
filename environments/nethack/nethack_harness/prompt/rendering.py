"""Prompt rendering: SYSTEM_PROMPT, per-variant observation formatters, the
descent/E1/E2 observation blocks, and the canonical per-turn chat formatter.

Extracted verbatim from nethack.py (no logic change). The single most-edited
surface of the harness lives here.
"""
from __future__ import annotations

import re
from typing import Optional

from nethack_harness.memory.journal import Journal

SYSTEM_PROMPT = """You are playing NetHack, a procedurally-generated dungeon-crawling roguelike.

Each turn shows: map (ASCII, runs `.{20}` = 20 dots), stats, inventory
(skipped on "unchanged"), messages, any menu. Act by calling one tool.

=== STRATEGY PRIMER ===
GLYPH KEY:
Terrain: `>` stairs DOWN, `<` stairs UP (NOT down), `_` altar, `{` fountain,
`}` pool, `#` corridor, `.` floor, `|`/`-` walls, `+` door, `\\` throne,
`$` gold, `%` food/corpse, `[`/`)`/`(`/`*`/`?` items. Creatures are LETTERS
(a-z, A-Z): `d` canine, `f` feline/lichen, `r` rat, `x` grid bug, `B` bat,
`k` kobold, `o` orc, `@` humans (and YOU). No "fireplace" glyph — adjacent
`f` is a creature. `@` hides the tile under you — read UNDER PLAYER.

VISIBLE FEATURES lists every stairs/altar/fountain/door on the visible map
with (x,y). If `stairs DOWN` isn't listed, no `>` is visible — don't
pattern-match the grid; explore or `search`. To descend: (1) find `>`,
(2) walk ON it, (3) call `descend`. If descend fails, recheck UNDER PLAYER.

DOORWAYS & WALL GAPS: a single non-wall tile inside a wall row is a
doorway you can walk through. Examples:
  `--.---` (horizontal wall with `.`) → walk through the `.`.
  `|.....|` with `-` in the middle → that `-` is broken wall; walk it.
  `-----+-----` → `+` is a closed door; step adjacent + try `move` (or
  `kick` if locked).
  `-----|-----` (`|` inside a horizontal wall row) → OPEN DOOR; just walk.
When stuck in a room, scan every wall row for a tile that doesn't match
`-` or `|`. That's your exit. Use `move_to(x,y)` if you can see the gap.

Pitfalls: `eat`/`quaff`/`read` need an `item` arg. At HP <30% retreat or
`search` to rest. `engrave_elbereth` when cornered (Elbereth scares most
monsters). Menus auto-dismiss; never call menu/inventory tools.

=== STRATEGY: DESCEND ASAP ===
**Default action every turn: `explore_and_descend`.** It auto-explores the
whole level (opening doors, searching for hidden passages), walks to the down
`>` and descends ONE floor, then hands control back to you. Just call it again
to keep diving. If it returns WITHOUT descending (no `>` found yet), call it
AGAIN — it resumes the complete search; do NOT hand-search tile-by-tile. It
returns early if your HP drops or you're fainting — then heal/eat and call it
again. This single tool does ~all the navigation.
If HP critical: `engrave_elbereth` or `pray`. Hostile adjacent + healthy
HP: `attack(direction=...)`. Hungry: `eat(item=...)`. Locked door: `kick`.

=== STAY ALIVE (death is what stops you, not the clock) ===
Most runs end in DEATH, not time — usually one of:
- **Starvation.** Don't let Hunger reach Weak/Fainting. `pickup` every food item
  and corpse you pass; `eat(item=...)` BEFORE you get Weak (fresh corpses of
  non-poisonous monsters are food). Never keep exploring while Hungry.
- **Melee swarm at low HP.** A fox/jackal/newt chips you to death. Don't melee at
  low HP — `engrave_elbereth` (scares most monsters) then `search(times=20)` to
  rest, or `pray` (once, when HP is critical), or flee toward stairs.
- **Ranged / approaching threats.** Kill dangerous monsters from a distance with
  `throw(item=..., direction=...)` (daggers, darts, rocks, spears) instead of
  letting them reach you. Hit it before it hits you.

=== SKILLS CHEAT SHEET ===
- **PRIMARY — dive**: `explore_and_descend` — explore the level + descend a
  floor, then returns to you. Call it every turn to go deeper.
- Reach a specific visible tile: `move_to(x, y)`
- Step: `move(direction=N|NE|E|...)`
- Pickup: `pickup`; Descend: `descend` (must be on `>`)
- Notes: `add_note` / `recall(query=...)` / `pin_objective`
- Search/rest: `search(times=10)` for hidden doors, `search(times=20)` to heal
- Wiki: `wiki_lookup(page="kobold")` / `wiki_search(query="cockatrice")`
- Combat: `attack(direction=N|...)` melee; `throw(item=..., direction=...)` ranged
  — never on `[PET — don't attack]`
- Survive: `eat(item=...)` before Weak; `pray`/`engrave_elbereth` at low HP

Your top-level goal is pre-pinned as `Objective:` in JOURNAL."""


# ---------- observation formatting for chat ----------
#
# Per-turn observation cost is the dominant line item in our token bill
# (~27k tok/turn at v0.0.15, ~4M tok per 150-turn rollout). Three cheap
# token-savers per docs/PROMPTING_SURVEY.md, with state-tracking so we don't
# re-send static content:
#
#   1. Strip blank tty rows from the map view.
#   2. Glyph-run encode long runs of `.` and `#` in the map view.
#   3. Inventory diff-only: emit "(unchanged)" when the inventory letter set
#      hasn't changed since last render (only meaningful if `state` is
#      threaded through; the helper still works with state=None).
#
# Combined target: ~30-40% token reduction on map-heavy turns.
# Toggle off by passing compact=False (e.g. for debugging / replay viewer).


def _strip_blank_rows(map_view: str) -> str:
    """Drop fully-blank rows; trim trailing whitespace per row."""
    out = []
    for row in map_view.splitlines():
        r = row.rstrip()
        if r:
            out.append(r)
    return "\n".join(out)


def _glyph_run_encode(map_view: str, min_run: int = 5) -> str:
    """Replace runs of `.` (floor) or `#` (corridor) of length >= min_run
    with `<ch>{N}`. Lossless; reversible. Saves ~15-25% on dungeon-row
    length once corridors are visible.
    """
    import re
    def _sub(m):
        ch = m.group(0)[0]
        return f"{ch}{{{len(m.group(0))}}}"
    pattern = re.compile(r"\.{" + str(min_run) + r",}|#{" + str(min_run) + r",}")
    return "\n".join(pattern.sub(_sub, row) for row in map_view.splitlines())


def _inventory_fingerprint(inventory) -> tuple:
    """Cheap hashable signature so we can diff inventories across turns."""
    return tuple((it.letter, it.description) for it in inventory)


def _run_length_encode_messages(messages) -> list:
    """Collapse consecutive identical messages into `text (xN)`. Saves tokens
    on combat spam ("You hit the kobold. You hit the kobold. ..."). Order-
    preserving; only consecutive duplicates collapse.
    """
    if not messages:
        return []
    out = []
    last = None
    run = 0
    for m in messages:
        if m == last:
            run += 1
        else:
            if last is not None:
                out.append(f"{last} (x{run})" if run > 1 else last)
            last = m
            run = 1
    if last is not None:
        out.append(f"{last} (x{run})" if run > 1 else last)
    return out


# ---------- variant-specific renderers (wave-1 baselines) ----------


def _glyph_to_words(ch: str) -> str:
    """Tiny vocab mapper from ASCII glyph -> natural-language token. Used by
    variant B (BALROG NLE text wrapper)."""
    _TBL = {
        ".": "floor", "#": "corridor", "|": "wall", "-": "wall", "+": "door",
        ">": "stairs-down", "<": "stairs-up", "_": "altar", "{": "fountain",
        "}": "pool", "\\": "throne", "$": "gold", "%": "food",
        "[": "armor", ")": "weapon", "(": "tool", "*": "rock", "?": "scroll",
        "!": "potion", "=": "ring", "/": "wand", "@": "you", " ": "void",
    }
    if ch in _TBL:
        return _TBL[ch]
    if ch.isalpha():
        return f"creature({ch})"
    return f"glyph({ch})"


def _format_obs_balrog(structured, journal, state, journal_max_chars: int) -> str:
    """Variant B: BALROG / NLE language wrapper. No ASCII grid; render a
    natural-language description of the scene, status, inventory, messages.
    Tests the hypothesis that the ASCII map adds little for small LLMs."""
    lines: list[str] = []
    if journal is not None and not journal.is_empty():
        lines.append("=== JOURNAL ===")
        lines.append(journal.render(max_chars=journal_max_chars))
        lines.append("")
    s = structured.status or {}
    lines.append("=== STATUS ===")
    lines.append(
        f"HP {s.get('hitpoints','?')}/{s.get('max_hitpoints','?')}  "
        f"AC {s.get('armor_class','?')}  "
        f"Dlvl {s.get('depth','?')}  "
        f"Turn {s.get('time','?')}  "
        f"XP {s.get('experience_level','?')}"
    )
    if "x" in s and "y" in s:
        lines.append(f"Position: ({s['x']},{s['y']})")
    c = structured.character or {}
    if c:
        lines.append(f"Character: {c.get('role','?')} ({c.get('race','?')}, {c.get('alignment','?')})")
    lines.append("")
    if structured.inventory:
        lines.append("=== INVENTORY ===")
        for item in structured.inventory:
            lines.append(f"  {item.letter}: {item.description}")
        lines.append("")
    under = getattr(structured, "under_player", None)
    if under:
        lines.append(f"=== UNDER PLAYER === {under}")
        lines.append("")
    adj = getattr(structured, "adjacent", None) or {}
    if adj:
        order = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        bits = []
        for d in order:
            tile = adj.get(d, " ")
            bits.append(f"{d}={_glyph_to_words(tile[0] if tile else ' ')}")
        lines.append("=== ADJACENT ===")
        lines.append("  " + ", ".join(bits))
        lines.append("")
    # Visible features (parsed from the grid) — the "what's around me" block
    # without forcing the model to read ASCII.
    if state is not None and "raw_obs" in state:
        try:
            from nethack_core.observations import (
                extract_visible_features, extract_hostiles_in_sight,
            )
            # The VISIBLE FEATURES list enumerates every stair/altar/door WITH
            # coordinates — it locates things for the agent. In the primitives
            # curriculum that's the crutch we're removing: the agent must read
            # the map and find features itself. (Hostiles-in-sight stays — that's
            # threat awareness, not the navigation goal.)
            if not state.get("_primitives_curriculum"):
                features = extract_visible_features(state["raw_obs"].tty_chars)
                if features:
                    lines.append("=== VISIBLE FEATURES ===")
                    for f in features:
                        lines.append(f"  - {f}")
                    lines.append("")
            hostiles = extract_hostiles_in_sight(
                state["raw_obs"].tty_chars,
                getattr(state["raw_obs"], "glyphs", None),
            )
            if hostiles:
                lines.append("=== HOSTILES IN SIGHT ===")
                for h in hostiles:
                    lines.append(f"  - {h}")
                lines.append("")
        except Exception:
            pass
    if structured.messages:
        lines.append("=== MESSAGES ===")
        for m in _run_length_encode_messages(structured.messages):
            lines.append(f"  {m}")
        lines.append("")
    return "\n".join(lines)


def _format_obs_glyphbox(structured, journal, state, journal_max_chars: int) -> str:
    """Variant G: Glyphbox-style obs. ASCII map + explicit player coords +
    adjacent-tile descriptions + visible-hostile list + inventory + messages.
    Closest analog to Ken Wang's Glyphbox harness."""
    # Reuse the canonical formatter (it already emits ADJACENT and VISIBLE
    # GLYPHS/FEATURES blocks). The Glyphbox delta is the *intent* to pair
    # this obs with the code-mode tool — toggled via interface="code"
    # in load_environment, not here.
    return format_observation_as_chat(
        structured, journal, state=state, compact=True,
        journal_max_chars=journal_max_chars,
    )


def _format_obs_summarize_reset(structured, journal, state, journal_max_chars: int) -> str:
    """Variant R: CPP/GPP summarize-and-reset. Same per-turn formatter as
    B1; the difference lives in get_prompt_messages — see _compact_chat_history
    behavior under summarize_and_reset=True, which hard-drops everything
    before the most recent belief-state checkpoint."""
    return format_observation_as_chat(
        structured, journal, state=state, compact=True,
        journal_max_chars=journal_max_chars,
    )


def _descent_status_block(structured, state) -> list[str]:
    """Wave-2 descent-salience block. Diagnosis (see experiment_log.md Wave-2):
    in EVERY failing rollout the down-stairs `>` never appeared in VISIBLE
    FEATURES — the agent wandered/oscillated around the starting room for
    300-1900 game-turns and DIED (usually starvation while Fainting). Runs
    that descended did so in <65 game-turns. So the dominant failure is
    "never reveal/reach `>`, then starve."

    This block makes the descent objective and the time-pressure impossible
    to miss, every turn. It is gated on state["_descent_salient"] (set for
    variants ND/FD) so the baselines are unaffected.

    Emits one of:
      DOWNSTAIRS: VISIBLE at (x,y) — call find_and_descend NOW to path there
                  and descend in one action.
      DOWNSTAIRS: not found yet — call find_and_descend to explore toward
                  unrevealed territory (it auto-paths to `>` the moment it is
                  seen). Avoid repeated search/pickup; they burn game-turns.
    Plus a level-clock warning once the in-game turn count on the current
    level grows large (starvation territory).
    """
    if not state or not state.get("_descent_salient"):
        return []
    out: list[str] = []
    stairs_xy = None
    try:
        from nethack_core.observations import extract_visible_features
        feats = extract_visible_features(state["raw_obs"].tty_chars)
        for f in feats:
            if f.startswith("stairs DOWN at "):
                m = re.search(r"\((\d+),(\d+)\)", f)
                if m:
                    stairs_xy = (int(m.group(1)), int(m.group(2)))
                break
    except Exception:
        pass
    # Memoized stairs (player may be standing on them, hiding the glyph).
    if stairs_xy is None and state.get("_seen_stairs_down"):
        try:
            px = int(structured.status.get("x", -1))
            py = int(structured.status.get("y", -1))
            if (px, py) in state["_seen_stairs_down"]:
                stairs_xy = (px, py)
        except Exception:
            pass
        if stairs_xy is None:
            stairs_xy = next(iter(state["_seen_stairs_down"]))
    out.append("=== DESCENT STATUS ===")
    _prim = bool(state.get("_primitives_curriculum")) if state is not None else False
    if stairs_xy is not None:
        if _prim:
            out.append(
                f"DOWNSTAIRS: VISIBLE at {stairs_xy}. Call "
                f"`move_to(x={stairs_xy[0]}, y={stairs_xy[1]})` NOW — it paths "
                f"onto the `>` and descends you automatically in ONE tool call. "
                f"There is no `descend`/`find_and_descend` tool; `move_to` onto "
                f"the down-stairs is how you descend. Do it immediately."
            )
        else:
            out.append(
                f"DOWNSTAIRS: VISIBLE at {stairs_xy}. Your goal is to descend. "
                f"Call `find_and_descend` NOW — it paths to `>` and descends in "
                f"one action. (Or `descend` if you are already standing on it.)"
            )
    else:
        if _prim:
            out.append(
                "DOWNSTAIRS: not visible yet. Call `autoexplore` to reveal more "
                "of the level, then `move_to` the 'stairs DOWN at (x,y)' the "
                "instant they appear (move_to onto `>` descends automatically). "
                "Do NOT loop on `search`/`pickup` — wasted turns risk starvation."
            )
        else:
            out.append(
                "DOWNSTAIRS: not found yet on this level. Call `find_and_descend` "
                "to push exploration into unrevealed territory; it auto-walks to "
                "`>` and descends the instant the stairs are seen. Do NOT "
                "loop on `search`/`pickup` — every wasted turn risks starvation."
            )
    # Level clock: NLE in-game turn counter. Starvation deaths in the failing
    # runs clustered at T:600-1900. Warn early so the agent prioritizes descent.
    try:
        t = int(structured.status.get("time", 0))
        if t >= 250:
            out.append(
                f"CLOCK: {t} in-game turns elapsed and still on Dlvl "
                f"{structured.status.get('depth','?')}. You are taking too "
                f"long — descend before hunger kills you."
            )
    except Exception:
        pass
    out.append("")
    return out


# ---------- Wave-3 / E1: frontier-surface obs blocks ----------

# 8-compass bearings shared across the E1 blocks.
_E1_BEARINGS = [
    ("N",  0, -1),
    ("NE", 1, -1),
    ("E",  1,  0),
    ("SE", 1,  1),
    ("S",  0,  1),
    ("SW", -1, 1),
    ("W", -1,  0),
    ("NW", -1, -1),
]


def _e1_bearing(dx: int, dy: int) -> str:
    """Quantize (dx, dy) to one of 8 compass bearings. Uses atan2-style
    bucketing — cheap and deterministic. Returns "@" when dx == dy == 0."""
    if dx == 0 and dy == 0:
        return "@"
    # Choose the bearing whose unit vector has the highest dot product with
    # the (dx, dy) heading. Equivalent to nearest-octant in 22.5° buckets.
    import math
    best = None
    best_dot = -1e9
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm, dy / norm
    for name, bx, by in _E1_BEARINGS:
        bnorm = math.hypot(bx, by) or 1.0
        dot = (ux * (bx / bnorm)) + (uy * (by / bnorm))
        if dot > best_dot:
            best_dot = dot
            best = name
    return best or "?"


def _e1_classify_frontier(chars, x: int, y: int) -> str:
    """One-word frontier-tile classifier. Reads the rendered glyph; falls
    back to 'tile' on anything exotic."""
    try:
        ch = chr(int(chars[y, x]))
    except Exception:
        return "tile"
    if ch == "#":
        return "corridor"
    if ch == ".":
        return "room edge"
    if ch == "<":
        return "stairs up"
    if ch == ">":
        return "stairs down"
    if ch in "+'":
        return "doorway"
    return "tile"


def _e1_frontiers_block(state) -> list[str]:
    """Render the 3-5 nearest unexplored frontiers (Wave-3 Track C).

    Surfaces the output of nethack_harness.navigation.pathfinding.find_frontiers — which
    the harness already computes for autoexplore — to the model. The
    "(no frontiers ...)" fallback directly cues the search skill, which
    is the documented out for sealed-room rollouts.
    """
    if not state or "raw_obs" not in state:
        return []
    try:
        from nethack_harness.navigation.pathfinding import find_frontiers
        raw = state["raw_obs"]
        chars = getattr(raw, "chars", None)
        if chars is None:
            return []
        blstats = getattr(raw, "blstats", None)
        if blstats is None:
            return []
        px, py = int(blstats[0]), int(blstats[1])
        frontiers = find_frontiers(chars)
    except Exception:
        return []

    out: list[str] = ["=== FRONTIERS ==="]
    if not frontiers:
        out.append("(no frontiers — try `search` for hidden passages)")
        out.append("")
        return out

    # Sort by Chebyshev distance from the agent (matches the A* heuristic
    # used by autoexplore). Cap at 5; cap line length at ~60 chars.
    scored = []
    for (fx, fy) in frontiers:
        d = max(abs(fx - px), abs(fy - py))
        scored.append((d, fx, fy))
    scored.sort(key=lambda t: t[0])
    for (d, fx, fy) in scored[:5]:
        bearing = _e1_bearing(fx - px, fy - py)
        kind = _e1_classify_frontier(chars, fx, fy)
        line = f"({fx}, {fy})  ~{d} steps {bearing}  — {kind}"
        if len(line) > 60:
            line = line[:57] + "..."
        out.append(line)
    out.append("")
    return out


def _e1_exploration_block(state, structured) -> list[str]:
    """Coverage + progress-delta indicator (Wave-3 Track C).

    Surfaces scout_tiles_seen (cumulative tiles revealed on the current
    dlvl) and scout_delta (newly revealed this turn). Persistent 0-delta
    is the oscillation signature we want the model to recognize and
    correct (by switching skills / picking a different frontier).
    """
    if not state:
        return []
    out: list[str] = []
    try:
        dlvl = state.get("max_dlvl_reached", 1)
        # scout_tiles_seen is keyed by (dlvl, x, y); filter to current dlvl.
        tiles = state.get("scout_tiles_seen") or set()
        cur_tiles = sum(1 for k in tiles if isinstance(k, tuple) and len(k) == 3 and k[0] == dlvl)
    except Exception:
        cur_tiles = 0
    # Count frontiers cheaply (re-uses the find_frontiers call cost; if
    # this becomes a hotspot we can memoize). On most maps len(frontiers)
    # is tiny (<20) so the extra walk is fine.
    n_frontiers = 0
    try:
        if "raw_obs" in state:
            from nethack_harness.navigation.pathfinding import find_frontiers
            chars = getattr(state["raw_obs"], "chars", None)
            if chars is not None:
                n_frontiers = len(find_frontiers(chars))
    except Exception:
        pass
    line = f"Explored: {cur_tiles} tiles, {n_frontiers} frontiers open"
    delta = state.get("scout_delta")
    if delta is None:
        line += " — turn 0 (no delta yet)"
    elif delta > 0:
        line += f" — revealed {int(delta)} new tiles"
    else:
        line += " — revealed 0 — retreading"
    out.append("=== EXPLORATION ===")
    out.append(line)
    out.append("")
    return out


def _e1_spatial_belief_block(state, structured) -> list[str]:
    """Replacement for the legacy descent-salience block (Wave-3 Track C).

    Instead of exhorting "descend now!", emit a compact spatial belief:
    bearings to the nearest 3 unexplored frontiers + any known
    stairs-down coordinates. Pure information — no nagging.
    """
    if not state:
        return []
    out: list[str] = ["=== SPATIAL BELIEF ==="]
    try:
        from nethack_harness.navigation.pathfinding import find_frontiers
        raw = state.get("raw_obs")
        chars = getattr(raw, "chars", None) if raw is not None else None
        blstats = getattr(raw, "blstats", None) if raw is not None else None
        if chars is not None and blstats is not None:
            px, py = int(blstats[0]), int(blstats[1])
            frontiers = find_frontiers(chars)
            if frontiers:
                scored = sorted(
                    ((max(abs(fx - px), abs(fy - py)), fx, fy) for (fx, fy) in frontiers),
                    key=lambda t: t[0],
                )[:3]
                bearings = ", ".join(f"{_e1_bearing(fx - px, fy - py)}~{d}" for d, fx, fy in scored)
                out.append(f"Unexplored bearings: {bearings}")
            else:
                out.append("Unexplored bearings: none (level fully revealed)")
    except Exception:
        pass
    seen = state.get("_seen_stairs_down") or set()
    if seen:
        # Cap at 3 coords to keep the line short.
        coords = ", ".join(f"({x},{y})" for (x, y) in list(seen)[:3])
        out.append(f"Known stairs DOWN: {coords}")
    else:
        out.append("Known stairs DOWN: none yet")
    out.append("")
    return out


_VARIANT_FORMATTERS = {
    # variant code -> formatter callable, or None to use the canonical formatter
    "B1": None,
    "B0": None,        # same formatter as B1; B0 just turns compact_obs off via kwargs
    "G": _format_obs_glyphbox,
    "B": _format_obs_balrog,
    "N": None,         # NetPlay differs only in skill_set, not in obs formatter
    "R": _format_obs_summarize_reset,
    "P": None,         # Continual Harness uses canonical formatter + refinement directive
    "CH": None,        # Full Continual Harness — same formatter; addendum/macros injected in get_prompt_messages
    # Wave-2 descent variants share the canonical formatter; the descent-salience
    # block is injected via state["_descent_salient"] (set in setup_state).
    "ND": None,        # NetPlay skill set + descent-salience block + clock warning
    "FD": None,        # find_and_descend autopilot: minimal skill set + salience block
    # Wave-3 Track C: frontier-surface obs. Canonical formatter; the four
    # new blocks (FRONTIERS, EXPLORATION, SPATIAL BELIEF, status delta) are
    # gated on state["_e1_obs"] (set in setup_state when variant == "E1").
    "E1": None,
    # Wave-3 Track C v2: paint frontier-adjacent unexplored tiles with '?'
    # directly on the map. No text blocks — the spatial cue lives in the
    # glyph grid the model already parses. Gated on state["_e2_obs"].
    "E2": None,
}


def _paint_frontiers_on_map(map_view: str, chars, frontiers, cap: int = 40) -> str:
    """Overlay '?' on truly-unseen tiles adjacent to each frontier.

    Frontiers are walkable tiles bordering unexplored space; the adjacent
    unseen tiles are where unrevealed content sits. Painting them as '?'
    gives the model a visual cue in the spatial layout it already reads,
    so the FRONTIERS/EXPLORATION/SPATIAL BELIEF text blocks become
    redundant.

    Only paints where the existing glyph is ' ' (space) — never overwrites
    walls, floor, items, or the agent. Caps the total paint count so a
    pathological map can't blow up the obs.
    """
    if not frontiers or chars is None:
        return map_view
    try:
        from nethack_harness.navigation.pathfinding import is_truly_unseen
    except Exception:
        return map_view
    rows = map_view.split("\n")
    grid = [list(r) for r in rows]
    h = len(grid)
    painted = 0
    seen: set[tuple[int, int]] = set()
    for (fx, fy) in frontiers:
        if painted >= cap:
            break
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = fx + dx, fy + dy
                if (nx, ny) in seen:
                    continue
                if not (0 <= ny < h):
                    continue
                row = grid[ny]
                if not (0 <= nx < len(row)):
                    continue
                if row[nx] != " ":
                    continue
                try:
                    if not is_truly_unseen(chars, nx, ny):
                        continue
                except Exception:
                    continue
                row[nx] = "?"
                seen.add((nx, ny))
                painted += 1
                if painted >= cap:
                    break
            if painted >= cap:
                break
    return "\n".join("".join(r) for r in grid)


def format_observation_as_chat(
    structured,
    journal: Optional[Journal] = None,
    state: Optional[dict] = None,
    compact: bool = True,
    journal_max_chars: int = 2000,
    include_map: bool = True,
    include_local: bool = True,
) -> str:
    """Render a StructuredObservation as a text block for the user message.

    When `state` is threaded through, we deduplicate static content
    across turns. `compact=False` disables all token-savers (used by tests
    and the replay viewer to inspect raw content).
    """
    lines: list[str] = []
    if journal is not None and not journal.is_empty():
        # Diff-only journal: when state is threaded through and the journal
        # hasn't changed since last render, emit "(unchanged)" instead of the
        # full block. Saves ~journal_max_chars/turn on stretches with no
        # journal writes. Belief-state ticks every 25 turns will refresh.
        cur_keys = tuple(sorted(journal.notes.keys()))
        cur_fp = (journal.objective, cur_keys)
        prev_fp = state.get("_journal_fingerprint") if state is not None else None
        lines.append("=== JOURNAL ===")
        if compact and prev_fp == cur_fp:
            # Diff-only: omit notes, but ALWAYS surface the pinned objective.
            # After history compaction strips turn 1, the agent has no way to
            # recall its goal from context — and the 9071d001 trace showed
            # zero `recall` calls, so the model wasn't retrieving it either.
            if journal.objective:
                lines.append(f"Objective: {journal.objective}")
                lines.append("(notes unchanged since last turn)")
            else:
                lines.append("(unchanged since last turn)")
        else:
            lines.append(journal.render(max_chars=journal_max_chars))
        if state is not None:
            state["_journal_fingerprint"] = cur_fp
        lines.append("")
    # Wave-2: descent-salience block (variants ND/FD). Placed immediately after
    # the journal/objective so it's the first concrete thing the model reads.
    lines.extend(_descent_status_block(structured, state))
    # Invocation-level domain knowledge (always on, every variant). The Gehennom
    # maze directly above Moloch's Sanctum has NO down-staircase BY DESIGN —
    # NetHack's maze builder skips the down-stair on the Invocation level, whose
    # descent is the invocation ritual, not a stair. Without this the agent burns
    # turns hunting a `>` that can never appear. This is game knowledge, not a
    # locating crutch, so it is surfaced regardless of curriculum/variant.
    if state is not None and state.get("_on_invocation_level"):
        lines.append(
            "=== INVOCATION LEVEL ===\n"
            "There is NO down-staircase on this level and none can appear — do "
            "NOT `search`/`autoexplore` for a `>`. This is the maze directly "
            "above Moloch's Sanctum (the dungeon's bottom). The ONLY way down is "
            "the invocation ritual: stand on the vibrating square and ring the "
            "Bell of Opening while carrying the lit Candelabrum of Invocation (7 "
            "candles attached) and the Book of the Dead. Without all three "
            "artifacts the Sanctum cannot be reached, so this Invocation level is "
            "the deepest a hero can navigate to on foot."
        )
        lines.append("")
    # Wave-3 Track C (variant E1): frontier + coverage + spatial-belief
    # blocks. Gated on state["_e1_obs"] so the legacy variants stay
    # bit-identical. The SPATIAL BELIEF block REPLACES (does not augment)
    # the legacy descent-salience block — but E1 sets _descent_salient=False
    # in setup_state, so the call above is a no-op for E1.
    if state is not None and state.get("_e1_obs"):
        lines.extend(_e1_frontiers_block(state))
        lines.extend(_e1_exploration_block(state, structured))
        lines.extend(_e1_spatial_belief_block(state, structured))
    if include_map:
        lines.append("=== MAP ===")
        map_view = structured.map_view
        # Wave-3 Track C v2 (variant E2): paint '?' over truly-unseen tiles
        # adjacent to each frontier, directly on the map. Done BEFORE compaction
        # so glyph-RLE still applies to floor/corridor runs.
        if state is not None and state.get("_e2_obs"):
            try:
                from nethack_harness.navigation.pathfinding import find_frontiers
                raw = state.get("raw_obs")
                chars = getattr(raw, "chars", None) if raw is not None else None
                if chars is not None:
                    frontiers = find_frontiers(chars)
                    map_view = _paint_frontiers_on_map(map_view, chars, frontiers)
            except Exception:
                pass
        if compact:
            map_view = _strip_blank_rows(map_view)
            map_view = _glyph_run_encode(map_view)
        lines.append(map_view)
        lines.append("")
    lines.append("=== STATUS ===")
    s = structured.status
    # Include max-dlvl-reached when state is threaded so the model can see
    # progression at a glance (e.g. on a return-to-prev-level via stairs up).
    max_dlvl = state.get("max_dlvl_reached") if state else None
    dlvl_part = f"Dlvl: {s.get('depth', '?')}"
    if max_dlvl is not None and max_dlvl > s.get("depth", 0):
        dlvl_part = f"Dlvl: {s.get('depth', '?')} (max reached: {max_dlvl})"
    pos_part = ""
    if "x" in s and "y" in s:
        pos_part = f"  Pos: ({s['x']},{s['y']})"
    # NLE hunger_state: 0=Satiated, 1=Normal, 2=Hungry, 3=Weak, 4=Fainting, 5=Starving.
    # Only surface when non-normal so the status line stays compact.
    _HUNGER_LABEL = {0: "Satiated", 2: "Hungry", 3: "Weak", 4: "Fainting", 5: "Starving"}
    hunger_part = ""
    h = s.get("hunger_state")
    if h is not None and h in _HUNGER_LABEL:
        hunger_part = f"  Hunger: {_HUNGER_LABEL[h]}"
    lines.append(f"HP: {s.get('hitpoints', '?')}/{s.get('max_hitpoints', '?')}  "
                 f"AC: {s.get('armor_class', '?')}  "
                 f"{dlvl_part}  "
                 f"Turn: {s.get('time', '?')}  "
                 f"XP: {s.get('experience_level', '?')}  "
                 f"$: {s.get('gold', 0)}{pos_part}{hunger_part}")
    c = structured.character
    if c:
        lines.append(f"Character: {c.get('role', '?')} ({c.get('race', '?')}, {c.get('alignment', '?')})")
    lines.append("")
    if structured.inventory:
        prev_fp = state.get("_inv_fingerprint") if state is not None else None
        cur_fp = _inventory_fingerprint(structured.inventory)
        if compact and prev_fp == cur_fp:
            lines.append("=== INVENTORY (unchanged) ===")
        else:
            lines.append("=== INVENTORY ===")
            for item in structured.inventory:
                lines.append(f"  {item.letter}: {item.description}")
        if state is not None:
            state["_inv_fingerprint"] = cur_fp
        lines.append("")
    if include_local:
        # UNDER PLAYER: critically tells the agent what tile @ is hiding.
        # Especially important for stairs (`>` down vs `<` up).
        under = getattr(structured, "under_player", None)
        if under:
            lines.append(f"=== UNDER PLAYER === {under}")
            lines.append("")
        adj = getattr(structured, "adjacent", None) or {}
        if adj:
            # Cheap "what's around me" block; saves the model from parsing the
            # map for adjacent tiles. Always emitted (even compact=False) — it's
            # a strictly additive signal worth ~30 tokens.
            order = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
            adj_line = " ".join(f"{d}={adj.get(d, '?')}" for d in order)
            lines.append(f"=== ADJACENT === {adj_line}")
            lines.append("")
        # NEXT-ACTION HINT: the model kept missing the moment to descend or
        # attack adjacent hostiles. If on stairs down, say so. Else if stairs
        # down adjacent, say which direction. Else if a letter glyph (monster)
        # is adjacent and HP is healthy, suggest attack. Strictly directive;
        # the model still has to call the tool.
        hint = None
        # Stairs-memory override: if the player is currently standing on a tile
        # we've previously observed as `>`, suggest descend. Fires above all
        # other hints (including HP-critical retreat) because (a) descending is
        # cheap, (b) the alternative is the oscillation loop.
        if state is not None and "_seen_stairs_down" in state and structured.status:
            try:
                px = int(structured.status.get("x", -1))
                py = int(structured.status.get("y", -1))
                if (px, py) in state["_seen_stairs_down"]:
                    _dcmd = ("`press_down`" if state.get("_primitives_curriculum")
                             else "`descend`")
                    hint = (
                        f"You are standing on stairs DOWN at ({px},{py}) — call "
                        f"{_dcmd} now. The `>` glyph is hidden under your `@`."
                    )
            except Exception:
                pass
        # HP-critical override — fires regardless of stairs / monsters.
        if structured.status:
            hp = structured.status.get("hitpoints", 0)
            hp_max = structured.status.get("max_hitpoints", 1) or 1
            if hp / hp_max < 0.3 and hp > 0:
                hint = (
                    f"HP critical ({hp}/{hp_max}). Options in order: `engrave_elbereth` "
                    f"(scares most monsters) → `search(times=20)` in a safe corner to rest "
                    f"and regenerate HP → `pray` if not on cooldown. Avoid melee until "
                    f"HP is back above 70%."
                )
            else:
                h = structured.status.get("hunger_state")
                if h is not None and h >= 3:
                    # Weak (3) or worse — agent will start losing HP unless they eat.
                    hint = (
                        f"Hunger is at {('Weak','Fainting','Starving')[min(h-3,2)]}. "
                        "Call `eat(item=<food letter>)` now; if no food in inventory, "
                        "`pray` (once) for divine aid."
                    )
        _prim = bool(state.get("_primitives_curriculum")) if state is not None else False
        if hint is None and under and "stairs DOWN" in under:
            hint = ("You are on stairs down. Call `press_down` to go down a level."
                    if _prim else "You are on stairs down. Call `descend` now.")
        elif hint is None and under and under.startswith("on tile:"):
            # Item under the player — suggest pickup.
            hint = f"Item here ({under}). Call `pickup` to grab it before moving on."
        else:
            for d, tile in adj.items():
                if "stairs DOWN" in tile:
                    hint = (f"Stairs down ({d}). Call `move(direction=\"{d}\")` to "
                            "step onto them — this descends you automatically.")
                    break
            if hint is None:
                # Adjacent letter glyph == hostile (the obs renderer labels
                # monsters as their letter). HP-aware: only suggest engagement
                # when above 50% HP; otherwise suggest retreat.
                mon_dir = None
                for d, tile in adj.items():
                    if len(tile) >= 1 and tile[0].isalpha() and tile not in ("@",):
                        # Skip pets — extract_adjacent now flags them when glyphs
                        # are available. Recommending `attack` on a pet would
                        # trigger the "really attack" peaceful prompt and damage
                        # alignment if confirmed.
                        if "PET" in tile:
                            continue
                        mon_dir = d
                        break
                if mon_dir is not None and structured.status:
                    hp = structured.status.get("hitpoints", 0)
                    hp_max = structured.status.get("max_hitpoints", 1) or 1
                    if _prim:
                        # Primitives curriculum: advise on the situation, not the
                        # destination. Combat is the main early-death cause, so
                        # discourage fighting — but do NOT hand a place to go.
                        hint = (f"Hostile adjacent ({mon_dir}) (HP {hp}/{hp_max}). "
                                "Fighting is risky — consider moving away from it; "
                                "if HP is very low, `pray` once.")
                    elif hp / hp_max >= 0.5:
                        hint = f"Hostile adjacent ({mon_dir}). Call `attack(direction=\"{mon_dir}\")` — your HP is healthy."
                    else:
                        hint = f"Hostile adjacent ({mon_dir}) and HP is low ({hp}/{hp_max}). Consider `engrave_elbereth` or retreat with `move`."
                # Stairs visible (but not adjacent): proactively suggest move_to.
                # Trace 9071d001 had stairs visible for many turns without the
                # agent navigating to them — it kept autoexploring.
                # NOT in the primitives curriculum: handing the agent the stairs
                # coordinate + "move_to there" does its navigation for it and
                # collapses play into a find->go->descend bot. There the agent
                # must read the map and choose the target itself.
                if hint is None and not _prim and state is not None and "raw_obs" in state:
                    try:
                        from nethack_core.observations import extract_visible_features
                        feats = extract_visible_features(state["raw_obs"].tty_chars)
                        for f in feats:
                            if f.startswith("stairs DOWN at "):
                                # f looks like "stairs DOWN at (38,11)" — pull
                                # the first coord pair.
                                import re as _re
                                m = _re.search(r"\((\d+),(\d+)\)", f)
                                if m:
                                    tx, ty = m.group(1), m.group(2)
                                    hint = (
                                        f"Stairs DOWN visible at ({tx},{ty}). "
                                        f"Call `move_to(x={tx}, y={ty})` NOW — it "
                                        "paths onto the down-stairs and descends "
                                        "you automatically (one tool call). Do this "
                                        "immediately to descend before monsters "
                                        "reach you."
                                    )
                                break
                    except Exception:
                        pass
        # Don't let secondary overrides clobber the standing-on-stairs hint.
        _on_stairs_override = bool(hint and "standing on stairs DOWN" in hint)
        # Pet-blocking detection: when the message buffer says "X is in the way!"
        # the move failed because the pet/peaceful occupies the tile. Trace
        # 9071d001 had the model stuck in long pet-blocking loops. Override any
        # weaker hint with a clear "go around" directive.
        if structured.messages and not _on_stairs_override:
            for msg in structured.messages[-4:]:
                if "is in the way" in msg:
                    hint = (
                        "A pet/peaceful is blocking your move. Walk a perpendicular "
                        "direction first to let it pass, or call `move(direction=\".\")` "
                        "to wait one turn."
                    )
                    break
        # Locked-door detection: NLE prints "This door is locked." when the
        # agent tries to move INTO a closed-locked `+`. Find the adjacent `+`
        # direction and tell the model to kick. Without this hint, traces show
        # the model giving up on the door and wandering / eating randomly.
        if structured.messages and not _on_stairs_override:
            for msg in structured.messages[-4:]:
                if "door is locked" in msg or "The door is locked." in msg:
                    door_dir = None
                    for d, tile in adj.items():
                        if tile.startswith("+") or tile == "+":
                            door_dir = d
                            break
                    if door_dir is not None:
                        hint = (
                            f"Door to {door_dir} is LOCKED. Call `kick(direction=\"{door_dir}\")` "
                            f"(may take 2-5 tries) to break it open, then walk through."
                        )
                    else:
                        hint = (
                            "A door is locked. Step adjacent to it, then "
                            "`kick(direction=...)` (2-5 tries) to break it open."
                        )
                    break
        # No-exit + visible-locked-door detection: when no stairs DOWN visible
        # and the agent is stuck in a small starting room with only a `+` exit,
        # surface the door coords and route to kick. This is the failure mode
        # the no-compact trace exposed: the agent autoexplores forever inside
        # the room because the BFS frontier resolves to `<` (stairs up).
        if (hint is None and not _on_stairs_override and state is not None
                and not state.get("_on_invocation_level") and "raw_obs" in state):
            try:
                from nethack_core.observations import extract_visible_features
                feats = extract_visible_features(state["raw_obs"].tty_chars)
                has_down = any(f.startswith("stairs DOWN") for f in feats)
                doors = [f for f in feats if f.startswith("door ")]
                if not has_down and doors and structured.status:
                    # Only fire if no other route is obvious. Pick the closest
                    # door by Chebyshev distance from the player.
                    px = structured.status.get("x", 0)
                    py = structured.status.get("y", 0)
                    import re as _re
                    best = None
                    best_d = 1 << 30
                    for f in doors:
                        m = _re.search(r"\((\d+),(\d+)\)", f)
                        if not m:
                            continue
                        dx, dy = int(m.group(1)), int(m.group(2))
                        cheb = max(abs(dx - px), abs(dy - py))
                        if cheb < best_d:
                            best_d = cheb
                            best = (dx, dy)
                    if best is not None:
                        hint = (
                            f"No `>` visible; only exit is a door at {best}. "
                            f"`move_to(x={best[0]}, y={best[1]})` to reach it; "
                            f"if it says \"locked\", `kick` toward it."
                        )
            except Exception:
                pass
        if hint:
            lines.append(f"=== HINT === {hint}")
            lines.append("")
    # Hostiles-in-sight + VISIBLE FEATURES: render in BOTH compact and
    # non-compact modes. Trace 5/16 (no-compact, 3 seeds, Qwen3.5-9B) showed
    # the agent NEVER calling `descend` because the pre-parsed feature block
    # was gated to compact mode only. Non-compact agents have to scan the
    # ASCII grid themselves and routinely confuse `<` for `>` on dense maps.
    from nethack_core.observations import extract_hostiles_in_sight, extract_visible_features
    # The VISIBLE FEATURES list enumerates every stair/altar/door WITH its
    # coordinates — it locates things for the agent. The primitives curriculum
    # forbids that: the agent reads the map and finds features itself. (Hostiles
    # stays below — threat awareness, not the navigation goal.)
    _prim = bool(state.get("_primitives_curriculum")) if state is not None else False
    if state is not None and "raw_obs" in state:
        try:
            # VISIBLE FEATURES locates stairs/altars/doors for the agent — skip it
            # entirely in the primitives curriculum (the agent reads the map).
            if not _prim:
                features = extract_visible_features(state["raw_obs"].tty_chars)
                if "_seen_stairs_down" in state:
                    import re as _rex
                    for f in features:
                        if f.startswith("stairs DOWN at "):
                            for mc in _rex.finditer(r"\((\d+),(\d+)\)", f):
                                state["_seen_stairs_down"].add(
                                    (int(mc.group(1)), int(mc.group(2)))
                                )
                if features:
                    lines.append(f"=== VISIBLE FEATURES === {'; '.join(features)}")
                    lines.append("")
            hostiles = extract_hostiles_in_sight(state["raw_obs"].tty_chars, getattr(state["raw_obs"], "glyphs", None))
            if hostiles:
                lines.append(f"=== VISIBLE GLYPHS === {', '.join(hostiles)}")
                lines.append("")
        except Exception:
            pass
    if structured.messages:
        lines.append("=== MESSAGES ===")
        msgs = _run_length_encode_messages(structured.messages) if compact else list(structured.messages)
        for m in msgs:
            lines.append(f"  {m}")
        lines.append("")
    if structured.menu:
        # Menus are auto-dismissed by the harness via ESC after each step;
        # if you see this block, dismissal didn't fully clear (rare).
        lines.append("=== MENU (harness will auto-dismiss; ignore) ===")
        for i, opt in enumerate(structured.menu):
            lines.append(f"  [{i}] {opt.description}")
        lines.append("")
    if structured.inventory_prompt:
        p = structured.inventory_prompt
        # Inventory prompts are auto-dismissed; eat/quaff/read take an `item`
        # arg and bundle the selection in-skill, so this block should not
        # normally appear.
        lines.append(f"=== PROMPT: {p['action']} (harness will auto-dismiss; pass `item` to eat/quaff/read) ===")
        for i, item in enumerate(p["items"]):
            lines.append(f"  [{i}] {item.description}")
        lines.append("")
    return "\n".join(lines)


# ---------- the env class ----------

