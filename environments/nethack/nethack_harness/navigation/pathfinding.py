"""
nethack_harness.navigation.pathfinding
========================

A* over the NetHack glyph grid + frontier-based autoexplore. Powers
`skills.move_to` and `skills.autoexplore`.

The cheap-but-correct approach:
  * Walkable tiles: floor, corridor, doors (open), stairs, items lying around.
  * Blocked: walls, solid rock, closed doors w/o unlocking logic, monsters.
  * Diagonals allowed; cost = 1 (Chebyshev neighborhood).
  * Heuristic = Chebyshev distance (admissible for 8-connected grid).

We deliberately don't follow glyphbox's `nle.glyph_id_to_class` route — that
demands a fragile NLE-version-locked glyph constant table. Using `obs.chars`
(which is just ASCII) is portable across NLE 1.2/1.3 and easier to reason
about. The cost: we can't distinguish "an unidentified scroll" from "an
identified scroll" by glyph alone. For pathfinding that's fine — both are
walkable.

Coordinate convention: (x, y) where x is column (0..78), y is row (0..20).
NetHack's blstats[0] is x and blstats[1] is y so we match that.
"""

from __future__ import annotations

import heapq
from typing import Iterator, Optional

import numpy as np

from nethack_core import actions as nethack

from nethack_core.env import CoreObservation


# ---------- walkability ----------

# Tiles the player can step onto without unlocking / fighting.
_WALKABLE_CHARS: frozenset[int] = frozenset(ord(c) for c in (
    ".",   # floor (lit / unlit / dark)
    "#",   # corridor / sink / drawbridge
    ">",   # staircase down
    "<",   # staircase up
    "_",   # altar
    "{",   # fountain
    "\\",  # throne
    "'",   # open door
    "+",   # closed door (we'll try; if locked the step is a no-op)
    " ",   # NB: space is "rock" — we treat it conservatively as NOT walkable
    # items lying on the floor (all walkable):
    "(", ")", "[", "*", "$", "/", "=", "\"", "?", "!", "%",
))
# Subtract space from walkable: rocks are not walkable, but unseen tiles
# also render as space, which we want to handle specially in frontier logic.
_WALKABLE_CHARS = _WALKABLE_CHARS - frozenset({ord(" ")})


def is_walkable(ch_byte: int) -> bool:
    """Is this rendered character a tile the player can step onto?"""
    return ch_byte in _WALKABLE_CHARS


def is_unknown(ch_byte: int) -> bool:
    """Unseen-tile sentinel (also matches solid rock, which is fine for autoexplore)."""
    return ch_byte == ord(" ")


# NLE glyph index for "solid stone / dark void". Both seen rock AND truly-
# unseen tiles share this glyph in chars (both render as space). The way to
# tell them apart is *geometric*: if the candidate space is surrounded on
# multiple sides by a wall (`-` / `|`) AND has no space neighbor of its own
# on the far side, NLE has effectively revealed it as "rock outside the
# room" — there is nothing reachable behind it. A truly-unseen tile has at
# least one space neighbor on the far side (the rest of the unexplored map).
_WALL_CHARS: frozenset[int] = frozenset(ord(c) for c in ("|", "-"))


def is_truly_unseen(chars: np.ndarray, ux: int, uy: int) -> bool:
    """Is the space-tile at (ux, uy) genuinely unexplored (vs. seen stone)?

    Heuristic predicate (5 lines, no NLE-version coupling):
      * If the tile is not a space, it isn't "unknown" — return False.
      * Otherwise count how many of its 8 neighbors are either walls
        (`|`/`-`) or out-of-bounds. If the tile is bordered by 3+ walls
        and has no other space neighbor, treat it as seen stone — the
        room geometry on this side is fully revealed; nothing is hidden.
      * Else, treat it as truly unseen (a candidate frontier neighbor).
    """
    h, w = chars.shape
    if not (0 <= ux < w and 0 <= uy < h):
        return False
    if int(chars[uy, ux]) != ord(" "):
        return False
    wall_or_edge = 0
    space_neighbors = 0
    for dx, dy, _ in _NEIGHBOR_DIRS:
        nx, ny = ux + dx, uy + dy
        if not (0 <= nx < w and 0 <= ny < h):
            wall_or_edge += 1
            continue
        nc = int(chars[ny, nx])
        if nc in _WALL_CHARS:
            wall_or_edge += 1
        elif nc == ord(" "):
            space_neighbors += 1
    # Seen-stone: bordered by walls/edge on 3+ sides AND no further void
    # behind us. Nothing can be hidden there.
    if wall_or_edge >= 3 and space_neighbors == 0:
        return False
    return True


# ---------- A* ----------

# 8 compass directions: (dx, dy, NLE_action_enum).
_NEIGHBOR_DIRS = [
    (0, -1, nethack.CompassDirection.N),
    (1, -1, nethack.CompassDirection.NE),
    (1, 0, nethack.CompassDirection.E),
    (1, 1, nethack.CompassDirection.SE),
    (0, 1, nethack.CompassDirection.S),
    (-1, 1, nethack.CompassDirection.SW),
    (-1, 0, nethack.CompassDirection.W),
    (-1, -1, nethack.CompassDirection.NW),
]


def _chebyshev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


def a_star(
    chars: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
    block_diagonals_through_doors: bool = True,
) -> Optional[list[int]]:
    """
    Compute a path from `start` to `goal` over the visible map.

    Returns a list of NLE action ids (CompassDirection enum values) or None
    if no path exists. The start tile is not included in the action list;
    the first action takes the player off the start tile.

    `block_diagonals_through_doors` disallows diagonal moves that would clip
    a doorway corner — NetHack disallows this in-game so the agent would
    bounce.
    """
    sx, sy = start
    gx, gy = goal
    h, w = chars.shape

    if not (0 <= gx < w and 0 <= gy < h):
        return None
    if start == goal:
        return []
    if not is_walkable(int(chars[gy, gx])):
        return None

    open_heap: list[tuple[int, int, tuple[int, int]]] = []
    counter = 0
    heapq.heappush(open_heap, (0, counter, start))
    came_from: dict[tuple[int, int], tuple[tuple[int, int], int]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current == goal:
            return _reconstruct_path(came_from, current)
        cx, cy = current
        for dx, dy, action in _NEIGHBOR_DIRS:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            nch = int(chars[ny, nx])
            if not is_walkable(nch):
                continue
            if block_diagonals_through_doors and dx != 0 and dy != 0:
                # NetHack forbids two kinds of diagonal move; A* must not
                # propose either or the engine silently refuses the step and
                # the hero stalls one tile short of the target (observed bug:
                # move_to onto a stair pressed '>' from the wrong tile).
                corner_h = int(chars[cy, nx])   # tile horizontally adjacent
                corner_v = int(chars[ny, cx])   # tile vertically adjacent
                # (1) No diagonal into/out of a doorway corner.
                if chr(corner_h) in "+'" or chr(corner_v) in "+'":
                    continue
                # (2) No diagonal SQUEEZE between two walls/rock: if BOTH
                # orthogonal corner cells are non-walkable, the gap can't be
                # traversed diagonally (you may still round a single corner).
                if not is_walkable(corner_h) and not is_walkable(corner_v):
                    continue
            tentative = g_score[current] + 1
            if tentative < g_score.get((nx, ny), 10**9):
                g_score[(nx, ny)] = tentative
                came_from[(nx, ny)] = (current, int(action))
                f_score = tentative + _chebyshev(nx, ny, gx, gy)
                counter += 1
                heapq.heappush(open_heap, (f_score, counter, (nx, ny)))

    return None


def reachable_set(
    chars: np.ndarray,
    start: tuple[int, int],
) -> set[tuple[int, int]]:
    """Flood-fill the set of walkable tiles reachable from `start`.

    BFS over the same 8-connected walkable neighborhood `a_star` uses (and
    the same doorway-diagonal rule), so the reachable set is exactly the set
    of tiles for which `a_star(chars, start, t)` would succeed. `start` itself
    is included if it is in-bounds.

    Used by `move_to` to make best-effort progress toward a target that has no
    fully-explored path yet: pick the reachable tile nearest the target and
    step toward it, revealing more map for subsequent calls.
    """
    h, w = chars.shape
    sx, sy = start
    out: set[tuple[int, int]] = set()
    if not (0 <= sx < w and 0 <= sy < h):
        return out
    from collections import deque
    out.add(start)
    queue: deque = deque([start])
    while queue:
        cx, cy = queue.popleft()
        for dx, dy, _ in _NEIGHBOR_DIRS:
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in out:
                continue
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if not is_walkable(int(chars[ny, nx])):
                continue
            if dx != 0 and dy != 0:
                # Same doorway-corner rule a_star enforces, so reachability
                # matches pathability exactly.
                if chr(int(chars[cy, nx])) in "+'" or chr(int(chars[ny, cx])) in "+'":
                    continue
            out.add((nx, ny))
            queue.append((nx, ny))
    return out


def _reconstruct_path(
    came_from: dict[tuple[int, int], tuple[tuple[int, int], int]],
    end: tuple[int, int],
) -> list[int]:
    actions: list[int] = []
    cur = end
    while cur in came_from:
        prev, action = came_from[cur]
        actions.append(action)
        cur = prev
    actions.reverse()
    return actions


# ---------- frontier-based autoexplore ----------

def find_frontiers(
    chars: np.ndarray,
    blacklist: Optional[set[tuple[int, int]]] = None,
    strict: bool = True,
) -> list[tuple[int, int]]:
    """
    Return all walkable tiles that are adjacent to an unknown / unseen tile.
    These are the targets autoexplore picks from.

    Args:
        chars: NLE chars grid (h, w) uint8.
        blacklist: optional set of (x, y) tiles to exclude — used by the
            visited-frontier memory in nethack.py to skip frontiers the
            agent has already approached without revealing new tiles.
        strict: if True (default), use `is_truly_unseen` to discriminate
            seen-stone (walled-off rock) from genuinely-unexplored void.
            Pass strict=False to recover legacy (memoryless, glyph-blind)
            behavior — the harness uses this only for fallback paths.
    """
    h, w = chars.shape
    bl = blacklist or frozenset()
    out: list[tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if (x, y) in bl:
                continue
            if not is_walkable(int(chars[y, x])):
                continue
            for dx, dy, _ in _NEIGHBOR_DIRS:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                nc = int(chars[ny, nx])
                if strict:
                    if is_truly_unseen(chars, nx, ny):
                        out.append((x, y))
                        break
                else:
                    if is_unknown(nc):
                        out.append((x, y))
                        break
    return out


def nearest_frontier(
    chars: np.ndarray,
    start: tuple[int, int],
    blacklist: Optional[set[tuple[int, int]]] = None,
    strict: bool = True,
) -> Optional[tuple[tuple[int, int], list[int]]]:
    """
    Find the closest reachable frontier from `start` and return (target, path).
    None if no frontier is reachable (level fully explored).

    We BFS from start and short-circuit the moment we step onto a frontier
    tile. Frontier-ness is checked on-the-fly (a frontier is a walkable
    tile adjacent to an unknown tile), so we don't pre-scan the full grid.
    This is the optimization documented in onboarding/10-profiling-hot-path.md.
    """
    h, w = chars.shape
    sx, sy = start
    if not (0 <= sx < w and 0 <= sy < h):
        return None

    # collections.deque pops left in O(1); plain list.pop(0) is O(n) and
    # explodes for large maps. Switch.
    from collections import deque
    bl = blacklist or frozenset()
    visited = {start}
    queue: deque = deque([(start, [])])
    while queue:
        (cx, cy), path = queue.popleft()
        # Frontier check on-the-fly: walkable + at least one space neighbor.
        if (cx, cy) != start and (cx, cy) not in bl and is_walkable(int(chars[cy, cx])):
            for ddx, ddy, _ in _NEIGHBOR_DIRS:
                nx2, ny2 = cx + ddx, cy + ddy
                if not (0 <= nx2 < w and 0 <= ny2 < h):
                    continue
                if strict:
                    if is_truly_unseen(chars, nx2, ny2):
                        return (cx, cy), path
                else:
                    if is_unknown(int(chars[ny2, nx2])):
                        return (cx, cy), path
        for dx, dy, action in _NEIGHBOR_DIRS:
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in visited:
                continue
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if not is_walkable(int(chars[ny, nx])):
                continue
            visited.add((nx, ny))
            queue.append(((nx, ny), path + [int(action)]))
    return None


def player_xy(obs: CoreObservation) -> tuple[int, int]:
    """Read player coordinates from blstats (indices 0, 1)."""
    return int(obs.blstats[0]), int(obs.blstats[1])
