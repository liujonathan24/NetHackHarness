"""
nethack_core.skills
===================

NetPlay-style skill mode. Each skill is a callable that takes the current
NetHackCoreEnv and arguments, and returns a sequence of primitive NLE actions
plus a feedback message.

We use a registry pattern so the verifiers wrapper can introspect available
skills to auto-generate OpenAI tool schemas. This is the layer Alex's pysc2
analogy points at: the skill set is the agent's API to the world.

The full skill catalog is intentionally small in v0. Add to it as you
characterize what LLM agents actually need. Don't blindly mirror autoascend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Literal, Optional

from nle import nethack

from .env import NetHackCoreEnv
from .journal import Journal
from .observations import StructuredObservation, InventoryItem
from .pathfinding import a_star, nearest_frontier, player_xy


Direction = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW", "."]


# NLE primitive action ids for directional movement
# (see nle.nethack.ACTIONS and CompassDirection in nle/nethack.py)
_DIRECTION_TO_ACTION = {
    "N": nethack.CompassDirection.N,
    "NE": nethack.CompassDirection.NE,
    "E": nethack.CompassDirection.E,
    "SE": nethack.CompassDirection.SE,
    "S": nethack.CompassDirection.S,
    "SW": nethack.CompassDirection.SW,
    "W": nethack.CompassDirection.W,
    "NW": nethack.CompassDirection.NW,
    ".": nethack.MiscDirection.WAIT,
}


@dataclass
class SkillResult:
    """What a skill returns to the harness layer."""
    actions: list[int]            # NLE primitive action ids to step()
    feedback: str                 # human-readable summary
    interrupted: bool = False     # True if the skill self-terminated early
    # For non-NLE skills (journal etc.) `actions` is empty and the side
    # effect is in `journal_op` so the harness can apply it after the call.
    journal_op: Optional[Callable[[Journal], str]] = None


class SkillRegistry:
    """Holds the catalog of skills and their schemas."""

    def __init__(self) -> None:
        self._skills: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}

    def register(self, name: str, schema: dict):
        def decorator(fn):
            self._skills[name] = fn
            self._schemas[name] = schema
            return fn
        return decorator

    def call(self, _skill_name: str, _env: NetHackCoreEnv, _obs: StructuredObservation, /, **kwargs) -> SkillResult:
        # Positional-only (`/`) parameters with underscore-prefixed names so a
        # model passing `{"name": ...}`, `{"env": ...}`, or `{"obs": ...}` as
        # tool args can't collide with our dispatcher signature. (v0.0.37 crash:
        # Qwen3.5-9B sent {"name": ...} → "got multiple values for argument 'name'".)
        name, env, obs = _skill_name, _env, _obs
        # Also strip these out in case some caller forwards them.
        for reserved in ("_skill_name", "_env", "_obs", "name", "env", "obs"):
            kwargs.pop(reserved, None)
        if name not in self._skills:
            return SkillResult(actions=[], feedback=f"Unknown skill: {name}", interrupted=True)
        fn = self._skills[name]
        # Defensive: small models (e.g. Qwen3.5-0.8B) sometimes emit malformed
        # tool calls where the arg dict is wrapped like {"arguments": "..."} or
        # contains stray keys. Filter kwargs to the function's real signature
        # so a bad call produces feedback rather than a crash.
        import inspect
        try:
            sig = inspect.signature(fn)
            accepted = {k for k, p in sig.parameters.items() if p.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)}
            ignored = set(kwargs) - accepted
            kwargs = {k: v for k, v in kwargs.items() if k in accepted}
        except (TypeError, ValueError):
            ignored = set()
        # Type coercion at the boundary: small models often send `{"index": "5"}`
        # (string for int) or `{"x": 12.0}` (float for int). Coerce per the
        # schema's declared param types so the skill doesn't TypeError on
        # cosmetic shape mismatches.
        schema_params = self._schemas.get(name, {}).get("parameters", {}) or {}
        for pname, pschema in schema_params.items():
            if pname not in kwargs:
                continue
            v = kwargs[pname]
            target = pschema.get("type")
            try:
                if target == "integer" and not isinstance(v, bool):
                    kwargs[pname] = int(v) if isinstance(v, (int, float, str)) else v
                elif target == "number":
                    kwargs[pname] = float(v) if isinstance(v, (int, float, str)) else v
                elif target == "string":
                    kwargs[pname] = str(v) if not isinstance(v, str) else v
            except (TypeError, ValueError):
                pass  # leave as-is; the skill will surface a friendlier error
        try:
            result = fn(env, obs, **kwargs)
        except (TypeError, AttributeError) as e:
            return SkillResult(actions=[], feedback=f"Skill {name} call failed: {e}. Schema: {self._schemas.get(name, {})}", interrupted=True)
        if ignored:
            extra = f"[ignored unknown args: {sorted(ignored)}]"
            result = SkillResult(actions=result.actions, feedback=f"{extra} {result.feedback or ''}".strip(), journal_op=result.journal_op, interrupted=result.interrupted)
        return result

    def all_schemas(self) -> dict[str, dict]:
        return dict(self._schemas)


registry = SkillRegistry()


# ---------- movement / exploration ----------

_DIRECTION_ALIASES = {
    "north": "N", "northeast": "NE", "east": "E", "southeast": "SE",
    "south": "S", "southwest": "SW", "west": "W", "northwest": "NW",
    "up": "N", "down": "S", "left": "W", "right": "E", "wait": ".",
}


def _normalize_direction(d: str) -> Optional[str]:
    """Normalize a direction string to the canonical N/NE/.../NW/'.' form.

    Accepts canonical form, lowercase, full names ('north'), and aliases
    ('up' = N, 'down' = S, 'left' = W, 'right' = E). Small models reliably
    emit these instead of the compact form; being strict costs the model
    a wasted turn for a cosmetic mismatch.
    """
    if not isinstance(d, str):
        return None
    s = d.strip()
    upper = s.upper()
    if upper in _DIRECTION_TO_ACTION:
        return upper
    lower = s.lower()
    if lower in _DIRECTION_ALIASES:
        return _DIRECTION_ALIASES[lower]
    return None


@registry.register("move", schema={
    "description": (
        "Move in a compass direction. By default runs in that direction until an "
        "obstacle is encountered (walls, monsters, corridor branches) — like "
        "NetHack's shift+direction 'run' command. This matches what experienced "
        "human players do for traversal. Pass run=False for a single step."
    ),
    "parameters": {
        "direction": {"type": "string", "enum": list(_DIRECTION_TO_ACTION.keys()), "description": "Compass direction (N/NE/E/SE/S/SW/W/NW) or '.' to wait. Aliases like 'north'/'up' are also accepted."},
        "run": {"type": "boolean", "default": True, "description": "If True (default), queue up to 25 steps in this direction; NLE will stop at first obstacle. If False, single step."},
    },
})
def move(env: NetHackCoreEnv, obs: StructuredObservation, direction: str, run: bool = True) -> SkillResult:
    canon = _normalize_direction(direction)
    if canon is None:
        return SkillResult([], f"Invalid direction: {direction!r}. Use N/NE/E/SE/S/SW/W/NW (or 'wait').", interrupted=True)
    step = int(_DIRECTION_TO_ACTION[canon])
    # SHORT-CIRCUIT: if `>` is visible and reachable, divert this move() to
    # a path-to-stairs + descend. This rescues rollouts where the LM saw
    # stairs in VISIBLE FEATURES but tried to micromanage with single
    # move() calls instead of calling find_and_descend/autoexplore.
    try:
        chars2, start2 = _current_chars_and_player(env)
        h2, w2 = chars2.shape
        stair2 = None
        for yy in range(h2):
            for xx in range(w2):
                if int(chars2[yy, xx]) == ord('>'):
                    stair2 = (xx, yy); break
            if stair2: break
        if stair2 is not None and stair2 != start2:
            p2 = a_star(chars2, start2, stair2)
            if p2 and len(p2) <= 60:
                acts = _enum_actions_to_indices(env, p2)
                try:
                    actions_list = env.underlying.unwrapped.actions
                    enum_to_idx = {int(a): i for i, a in enumerate(actions_list)}
                    more_idx = enum_to_idx.get(int(nethack.MiscAction.MORE), 0)
                    down_idx = enum_to_idx.get(int(nethack.MiscDirection.DOWN), 0)
                    acts = acts + [more_idx, down_idx]
                except Exception:
                    pass
                return SkillResult(
                    actions=acts,
                    feedback=(
                        f"move({canon}) — diverted: `>` visible at {stair2}, "
                        f"pathing {len(p2)} steps and descending."
                    ),
                )
    except Exception:
        pass
    if not run or canon == ".":
        return SkillResult([step], f"Moved {canon}.")
    # Compute path via a_star to a tile far in this direction — gives us
    # an obstacle-aware "run" that auto-stops at walls and corridor turns.
    try:
        chars, start = _current_chars_and_player(env)
        h, w = chars.shape
        dx_map = {"N":(0,-1),"NE":(1,-1),"E":(1,0),"SE":(1,1),
                  "S":(0,1),"SW":(-1,1),"W":(-1,0),"NW":(-1,-1)}
        dx, dy = dx_map[canon]
        # Step forward until obstacle or edge.
        cx, cy = start
        path = []
        for _ in range(25):
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < w and 0 <= ny < h): break
            tile = int(chars[ny, nx])
            from .pathfinding import is_walkable
            if not is_walkable(tile): break
            path.append(step)
            cx, cy = nx, ny
            # Stop at items / interesting tiles so we don't run past them.
            if tile in (ord('>'), ord('<'), ord('_'), ord('{'), ord('+'),
                        ord('%'), ord('$'), ord('('), ord(')'), ord('['),
                        ord('*'), ord('?'), ord('!'), ord('/'), ord('='),
                        ord('"')):
                break
        if not path:
            # First step blocked — return single step so feedback reports it.
            return SkillResult([step], f"Moved {canon} (blocked at first step).")
        return SkillResult(path, f"Ran {canon} for {len(path)} steps.")
    except Exception:
        return SkillResult([step], f"Moved {canon} (run setup failed).")


@registry.register("attack", schema={
    "description": (
        "Melee attack an adjacent monster in the given direction. Do NOT call "
        "if the target shows `[PET — don't attack]` in ADJACENT — attacking a "
        "pet damages alignment. Walk around pets instead."
    ),
    "parameters": {"direction": {"type": "string", "enum": list(_DIRECTION_TO_ACTION.keys())}},
})
def attack(env: NetHackCoreEnv, obs: StructuredObservation, direction: str) -> SkillResult:
    # In NetHack, melee = move toward the monster. Same action.
    # We separate it as a skill for legibility in traces.
    canon = _normalize_direction(direction)
    if canon is None:
        return SkillResult([], f"Invalid direction: {direction!r}.", interrupted=True)
    # Sanity check: is there actually a letter glyph adjacent in this
    # direction? If not, the agent is "attacking" empty space — likely a
    # misread of the map. Warn but still pass the action through (NetHack
    # will just walk one step, harmless).
    adj = getattr(obs, "adjacent", None) or {}
    tile = adj.get(canon, "")
    target_warning = ""
    if tile and not (len(tile) >= 1 and tile[0].isalpha() and tile[0] != "@"):
        target_warning = (
            f" (note: ADJACENT shows {canon}={tile!r}, no monster there — "
            "this will just walk forward.)"
        )
    result = move(env, obs, direction=direction)
    if target_warning and result.feedback:
        result = SkillResult(actions=result.actions, feedback=result.feedback + target_warning, interrupted=result.interrupted)
    return result


@registry.register("descend", schema={
    "description": (
        "Descend the down-staircase. You MUST be standing on a '>' tile. "
        "Check `=== UNDER PLAYER ===` first — it should say 'stairs DOWN (>)'. "
        "If it says 'stairs UP (<)' you'll go BACK to a previous level instead. "
        "If it says 'floor' or anything else, this call wastes a turn."
    ),
    "parameters": {},
})
def descend(env: NetHackCoreEnv, obs: StructuredObservation) -> SkillResult:
    # Friendlier feedback: if under_player exists and isn't `>`, short-circuit
    # with an explanatory message so the agent doesn't waste a turn AND
    # doesn't get a generic "couldn't descend" message.
    under = getattr(obs, "under_player", None)
    if under and not under.startswith("stairs DOWN"):
        return SkillResult(
            [],
            f"Can't descend — you're standing on: {under}. Find a '>' tile and step ON it first.",
            interrupted=True,
        )
    # Convert enum values to action INDICES — env.step takes indices not
    # raw NLE enum keycodes. Without this fix, descend sends [13, 62] which
    # env.step interprets as indices 13 and 62; index 62 is OOB and crashes
    # (or silently no-ops). This bug ate every "successful" descent attempt
    # for who-knows-how-long.
    if env is None:
        # Test path: no real env; fall back to enum values (tests don't step).
        return SkillResult([int(nethack.MiscAction.MORE), int(ord('>'))], "Attempted to descend.")
    actions = env.underlying.unwrapped.actions
    enum_to_idx = {int(a): i for i, a in enumerate(actions)}
    more_idx = enum_to_idx.get(int(nethack.MiscAction.MORE), 0)
    down_idx = enum_to_idx.get(int(nethack.MiscDirection.DOWN), enum_to_idx.get(int(ord('>')), 0))
    return SkillResult([more_idx, down_idx], "Attempted to descend.")


@registry.register("search", schema={
    "description": (
        "Search adjacent tiles for hidden passages and traps. Pass `times` "
        "to repeat — hidden passages typically need 5-10 searches at the same "
        "tile to reveal. Defaults to 1."
    ),
    "parameters": {
        "times": {
            "type": "integer",
            "default": 1,
            "description": "Number of consecutive search actions (1-20).",
        },
    },
})
def search(env: NetHackCoreEnv, obs: StructuredObservation, times: int = 1) -> SkillResult:
    try:
        n = int(times)
    except (TypeError, ValueError):
        n = 1
    n = max(1, min(20, n))
    return SkillResult([int(ord('s'))] * n, f"Searched x{n}." if n > 1 else "Searched.")


# ---------- survival actions (eat / quaff / read / pray / engrave / kick / throw) ----------
#
# These press a single command key. NetHack will then prompt for inventory
# selection if needed; the agent answers via `inventory_item` on the next turn.

def _find_inv_letter(obs: StructuredObservation, item: Optional[str], kinds: tuple[str, ...]) -> tuple[Optional[str], str]:
    """Resolve `item` (substring or letter) → inventory letter. Returns (letter, feedback).
    Letter is None if no match — feedback explains why.
    `kinds`: lowercase keyword filter (e.g. ('food',) for eat). Empty tuple = any."""
    inv = obs.inventory or []
    candidates = [it for it in inv if not kinds or any(k in it.description.lower() for k in kinds)]
    if not candidates:
        return None, f"No matching items in inventory (looked for: {', '.join(kinds) or 'any'})."
    if not item:
        listing = ", ".join(f"{c.letter}={c.description}" for c in candidates[:6])
        return None, f"Specify `item` (letter or substring). Candidates: {listing}"
    item = item.strip()
    # Letter match first.
    if len(item) == 1:
        for c in candidates:
            if c.letter == item:
                return c.letter, f"Selected {c.description}."
    # Substring match against description.
    lo = item.lower()
    for c in candidates:
        if lo in c.description.lower():
            return c.letter, f"Selected {c.description}."
    listing = ", ".join(f"{c.letter}={c.description}" for c in candidates[:6])
    return None, f"No item matched {item!r}. Candidates: {listing}"


@registry.register("eat", schema={
    "description": (
        "Eat an edible item from inventory. Pass `item` = substring of the food's "
        "description (e.g. 'apple', 'food ration') OR its inventory letter. "
        "If no edible items exist or `item` doesn't match, the turn is NOT consumed "
        "and you get feedback listing candidates."
    ),
    "parameters": {"item": {"type": "string", "description": "substring or letter of the food", "default": None}},
})
def eat(env: NetHackCoreEnv, obs: StructuredObservation, item: Optional[str] = None) -> SkillResult:
    letter, feedback = _find_inv_letter(obs, item, ("food", "corpse", "ration", "fruit", "apple", "pancake", "cookie", "tripe"))
    if letter is None:
        return SkillResult([], feedback, interrupted=True)
    return SkillResult([int(ord('e')), int(ord(letter))], feedback)


@registry.register("quaff", schema={
    "description": (
        "Quaff (drink) a potion. Pass `item` = substring or letter. If no potion "
        "matches, the turn is NOT consumed."
    ),
    "parameters": {"item": {"type": "string", "description": "substring or letter of the potion", "default": None}},
})
def quaff(env: NetHackCoreEnv, obs: StructuredObservation, item: Optional[str] = None) -> SkillResult:
    letter, feedback = _find_inv_letter(obs, item, ("potion",))
    if letter is None:
        return SkillResult([], feedback, interrupted=True)
    return SkillResult([int(ord('q')), int(ord(letter))], feedback)


@registry.register("read", schema={
    "description": (
        "Read a scroll or spellbook. Pass `item` = substring or letter. If no "
        "readable matches, the turn is NOT consumed."
    ),
    "parameters": {"item": {"type": "string", "description": "substring or letter of the scroll/book", "default": None}},
})
def read(env: NetHackCoreEnv, obs: StructuredObservation, item: Optional[str] = None) -> SkillResult:
    letter, feedback = _find_inv_letter(obs, item, ("scroll", "spellbook", "book"))
    if letter is None:
        return SkillResult([], feedback, interrupted=True)
    return SkillResult([int(ord('r')), int(ord(letter))], feedback)


@registry.register("pray", schema={
    "description": "Pray to your god (#pray, then 'y' to confirm). Risky if recently used.",
    "parameters": {},
})
def pray(env: NetHackCoreEnv, obs: StructuredObservation) -> SkillResult:
    # '#' enters extended-command mode; 'p','r','a','y' types the command; '\n' submits; 'y' confirms.
    return SkillResult([int(ord('#')), int(ord('p')), int(ord('r')), int(ord('a')), int(ord('y')),
                        int(nethack.MiscAction.MORE), int(ord('y'))], "Prayed.")


@registry.register("engrave_elbereth", schema={
    "description": "Engrave 'Elbereth' in the dust to scare most monsters. Uses E command.",
    "parameters": {},
})
def engrave_elbereth(env: NetHackCoreEnv, obs: StructuredObservation) -> SkillResult:
    # E + - (use finger) + Elbereth + Enter + Enter
    actions = [int(ord('E')), int(ord('-'))]
    for ch in "Elbereth":
        actions.append(int(ord(ch)))
    actions.append(int(nethack.MiscAction.MORE))  # finish text
    actions.append(int(nethack.MiscAction.MORE))  # any prompt close
    return SkillResult(actions, "Engraved Elbereth.")


# vi-style direction keystrokes that NetHack accepts on direction prompts.
_DIRECTION_VI_KEY = {
    "N": "k", "S": "j", "E": "l", "W": "h",
    "NE": "u", "NW": "y", "SE": "n", "SW": "b",
    ".": ".",
}


@registry.register("kick", schema={
    "description": "Kick (ctrl-D) in a direction. Used to break locks/doors. Pass `direction` (N/NE/.../NW).",
    "parameters": {"direction": {"type": "string", "enum": list(_DIRECTION_VI_KEY.keys()),
                                 "description": "Compass direction to kick.", "default": "N"}},
})
def kick(env: NetHackCoreEnv, obs: StructuredObservation, direction: str = "N") -> SkillResult:
    canon = _normalize_direction(direction)
    if canon is None or canon not in _DIRECTION_VI_KEY:
        return SkillResult([], f"Invalid direction: {direction!r}", interrupted=True)
    # Ctrl-D = 0x04, then the vi-style direction key.
    return SkillResult([0x04, int(ord(_DIRECTION_VI_KEY[canon]))], f"Kicked {canon}.")


@registry.register("throw", schema={
    "description": "Throw an item in a direction. Pass `item` (substring/letter) AND `direction`.",
    "parameters": {
        "item": {"type": "string", "description": "substring or letter of the item to throw"},
        "direction": {"type": "string", "enum": list(_DIRECTION_VI_KEY.keys()), "default": "N"},
    },
})
def throw(env: NetHackCoreEnv, obs: StructuredObservation, item: Optional[str] = None, direction: str = "N") -> SkillResult:
    letter, feedback = _find_inv_letter(obs, item, ())  # any inventory item
    if letter is None:
        return SkillResult([], feedback, interrupted=True)
    canon = _normalize_direction(direction)
    if canon is None or canon not in _DIRECTION_VI_KEY:
        return SkillResult([], f"Invalid direction: {direction!r}", interrupted=True)
    return SkillResult(
        [int(ord('t')), int(ord(letter)), int(ord(_DIRECTION_VI_KEY[canon]))],
        f"Threw {feedback} {canon}.",
    )


# ---------- inventory ----------

@registry.register("pickup", schema={
    "description": "Pick up items on the current tile.",
    "parameters": {},
})
def pickup(env: NetHackCoreEnv, obs: StructuredObservation) -> SkillResult:
    return SkillResult([int(ord(','))], "Attempted to pick up.")


@registry.register("inventory_item", schema={
    "description": (
        "Respond to an inventory prompt (e.g. 'What do you want to throw?'). "
        "ONLY use when the observation has a '=== PROMPT: ...' block — that "
        "block lists numbered items; pass the matching 0-based index. "
        "Outside a prompt this returns 'No inventory prompt is open.'"
    ),
    "parameters": {"index": {"type": "integer", "description": "0-based index into the listed prompt items"}},
})
def inventory_item(env: NetHackCoreEnv, obs: StructuredObservation, index: int) -> SkillResult:
    if obs.inventory_prompt is None:
        return SkillResult([], "No inventory prompt is open.", interrupted=True)
    items = obs.inventory_prompt["items"]
    if not (0 <= index < len(items)):
        return SkillResult([], f"Index {index} out of range for {len(items)} choices.", interrupted=True)
    target: InventoryItem = items[index]
    return SkillResult([int(ord(target.letter))], f"Selected {target.description}.")


@registry.register("menu_option", schema={
    "description": (
        "Select a menu option by index. ONLY use when the observation has a "
        "'=== MENU ===' block; otherwise this returns 'No menu is open.' and "
        "you waste a turn. Index is 0-based into the listed options."
    ),
    "parameters": {"index": {"type": "integer", "description": "0-based index into the visible menu"}},
})
def menu_option(env: NetHackCoreEnv, obs: StructuredObservation, index: int) -> SkillResult:
    if obs.menu is None:
        return SkillResult([], "No menu is open.", interrupted=True)
    if not (0 <= index < len(obs.menu)):
        return SkillResult([], f"Index {index} out of range.", interrupted=True)
    return SkillResult([int(ord(obs.menu[index].letter))], f"Selected: {obs.menu[index].description}")


# ---------- bootstrap: capture role/race/alignment on episode start ----------

# Two forms of the welcome message we need to handle:
#   "Hello Agent, welcome to NetHack!  You are a neutral male human Monk."
#   "Hello Agent, the Stripling, welcome to NetHack!  You are a lawful female human Valkyrie."
# The role-title prefix (Stripling, Candidate, ...) varies by role + XP rank.
_WELCOME_RE = re.compile(
    r"You are (?:a |an )?"
    r"(?P<alignment>lawful|neutral|chaotic)\s+"
    r"(?P<gender>male|female|neuter)\s+"
    r"(?P<race>\w+)\s+"
    r"(?P<role>\w+)"
)
_UNKNOWN_CHARACTER = {
    "role": "unknown",
    "race": "unknown",
    "alignment": "unknown",
    "gender": "unknown",
}


def parse_character_from_welcome(message: str) -> dict[str, str]:
    """
    Parse role/race/alignment/gender from the NetHack opening welcome line.

    Returns the canonical {"role","race","alignment","gender"} dict with
    "unknown" sentinels if parsing fails (we never want to crash here — the
    rest of the system runs fine without character info, just without the
    role-aware prompt block).
    """
    m = _WELCOME_RE.search(message)
    if not m:
        return dict(_UNKNOWN_CHARACTER)
    out = m.groupdict()
    # Role from the welcome message is the role *singular* (e.g. "Monk", not
    # the title "Stripling"). Normalize to lowercase for consistency with the
    # rest of the obs schema.
    return {k: v.lower() for k, v in out.items()}


# Rank titles (xp level 1 only) per role, used as a fallback when NLE's
# welcome message has been preempted by a calendar event. Source: NetHack
# 3.6 role definitions. Only the level-1 title is unique enough to map back.
_LEVEL1_TITLE_TO_ROLE = {
    "Candidate": "monk",
    "Stripling": "valkyrie",
    "Hatamoto": "samurai",
    "Evoker": "wizard",
    "Aspirant": "priest",
    "Tenderfoot": "ranger",
    "Footpad": "rogue",
    "Plunderer": "barbarian",
    "Rambler": "tourist",
    "Digger": "archeologist",
    "Troglodyte": "caveman",
    "Rhizotomist": "healer",
    "Gallant": "knight",
}


def _bootstrap_from_status_line(tty_chars) -> dict[str, str]:
    """Fallback parser: reads "Agent the <Title>" + alignment word from the
    NetHack status line (row 22 of the tty). Used when the welcome message
    buffer is preempted (e.g. by a new-moon calendar event)."""
    out = dict(_UNKNOWN_CHARACTER)
    if tty_chars is None or len(tty_chars) < 23:
        return out
    line = "".join(chr(c) for c in tty_chars[22]).strip()
    # Title (xp1 rank) → role.
    for title, role in _LEVEL1_TITLE_TO_ROLE.items():
        if f" the {title}" in line:
            out["role"] = role
            break
    # Alignment word at end of first half of status line.
    for align in ("Lawful", "Neutral", "Chaotic"):
        if align in line:
            out["alignment"] = align.lower()
            break
    return out


def bootstrap_character(env: NetHackCoreEnv) -> dict[str, str]:
    """
    Read role/race/alignment/gender from the env's current observation.

    Primary path: NetHack's first message after `env.reset()` is usually
    "Hello <name>, welcome to NetHack!  You are a <align> <gender> <race>
    <role>." We parse that. Free — consumes no in-game turn.

    Fallback path: on dates when NLE prepends a calendar event ("Be careful!
    New moon tonight."), the welcome line gets overwritten in the message
    buffer. We then scrape the tty status line ("Agent the Candidate ...
    Neutral S:0") for the role's level-1 rank title + alignment word. This
    won't recover race or gender (those don't appear in the status line)
    but at least gives a real role/alignment instead of "unknown".

    Why not `#attributes`? The Score / Staircase / etc. tasks restrict the
    action set to 23 actions and don't include Command.ATTRIBUTES. We'd have
    to either extend the action set (raises portability questions for
    PufferLib consumers) or screen-scrape the resulting menu. The welcome +
    status-line fallback combination works on every NLE task class.
    """
    out = dict(_UNKNOWN_CHARACTER)
    try:
        nle_env = env.underlying
        last_msg = nle_env.unwrapped.last_observation
        keys = nle_env.unwrapped._observation_keys
        # Primary: welcome message
        if "message" in keys:
            msg_bytes = last_msg[keys.index("message")]
            msg = bytes(msg_bytes).split(b"\x00", 1)[0].decode("ascii", errors="replace")
            parsed = parse_character_from_welcome(msg)
            if parsed.get("role") != "unknown":
                return parsed
        # Fallback: status line via tty_chars
        if "tty_chars" in keys:
            tty = last_msg[keys.index("tty_chars")]
            fallback = _bootstrap_from_status_line(tty)
            for k in ("role", "alignment"):
                if fallback.get(k) != "unknown":
                    out[k] = fallback[k]
    except Exception:
        # Defensive: never break bootstrap.
        pass
    return out


# ---------- to-be-implemented ----------
# These are real skills, just stubs for now. Each is a self-contained PR worth.

def _current_chars_and_player(env: NetHackCoreEnv):
    """Pull the latest chars grid and player (x, y) from the underlying NLE.

    The skill API gets a StructuredObservation but we want the raw chars
    array for pathfinding. The CoreObservation lives in the verifiers state
    dict, not here; so we read it back from NLE's last_observation.
    """
    nle_env = env.underlying.unwrapped
    keys = nle_env._observation_keys
    last = nle_env.last_observation
    chars = last[keys.index("chars")]
    blstats = last[keys.index("blstats")]
    return chars, (int(blstats[0]), int(blstats[1]))


def _enum_actions_to_indices(env: NetHackCoreEnv, enum_actions: list[int]) -> list[int]:
    """
    Pathfinding returns NLE action ENUM values (e.g. 107 for CompassDirection.N).
    NetHackScore.step expects INDICES into env.actions (e.g. 1 for N). This
    converts the former to the latter, skipping any enum value not present in
    the action set (which would otherwise raise IndexError mid-trajectory).
    """
    actions = env.underlying.unwrapped.actions
    enum_to_idx = {int(a): i for i, a in enumerate(actions)}
    out: list[int] = []
    for a in enum_actions:
        if a in enum_to_idx:
            out.append(enum_to_idx[a])
    return out


@registry.register("move_to", schema={
    "description": (
        "Pathfind to a specific (x, y) tile on the current level. Uses A* "
        "over the visible map. The path is precomputed — if a monster steps "
        "into the path mid-traversal, the rollout will end up engaging it. "
        "For careful exploration, call autoexplore instead."
    ),
    "parameters": {
        "x": {"type": "integer", "description": "Column 0..78"},
        "y": {"type": "integer", "description": "Row 0..20"},
    },
})
def move_to(env: NetHackCoreEnv, obs: StructuredObservation, x: int, y: int) -> SkillResult:
    chars, start = _current_chars_and_player(env)
    tx, ty = int(x), int(y)
    # SHORT-CIRCUIT: if the player ASKED for `>` (target tile is stairs DOWN)
    # OR `>` is currently visible and reachable, path to `>` and append
    # descend in one tool call. Same rescue logic as move().
    try:
        h2, w2 = chars.shape
        stair2 = None
        # honor explicit request first
        if 0 <= ty < h2 and 0 <= tx < w2 and int(chars[ty, tx]) == ord('>'):
            stair2 = (tx, ty)
        else:
            for yy in range(h2):
                for xx in range(w2):
                    if int(chars[yy, xx]) == ord('>'):
                        stair2 = (xx, yy); break
                if stair2: break
        if stair2 is not None and stair2 != start:
            p2 = a_star(chars, start, stair2)
            if p2:
                acts = _enum_actions_to_indices(env, p2)
                try:
                    actions_list = env.underlying.unwrapped.actions
                    enum_to_idx = {int(a): i for i, a in enumerate(actions_list)}
                    more_idx = enum_to_idx.get(int(nethack.MiscAction.MORE), 0)
                    down_idx = enum_to_idx.get(int(nethack.MiscDirection.DOWN), 0)
                    acts = acts + [more_idx, down_idx]
                except Exception:
                    pass
                return SkillResult(
                    actions=acts,
                    feedback=f"move_to({tx},{ty}) — diverted to `>` at {stair2}, pathing {len(p2)} steps and descending.",
                )
    except Exception:
        pass
    path = a_star(chars, start, (tx, ty))
    if path is None:
        # Surface why the target is unreachable: out of bounds, or what
        # tile sits there. Bare "No path" sent the model into spin loops.
        try:
            h = chars.shape[0] if hasattr(chars, "shape") else len(chars)
            w = chars.shape[1] if hasattr(chars, "shape") else len(chars[0])
            if not (0 <= ty < h and 0 <= tx < w):
                detail = f"target ({tx},{ty}) is out of bounds (map is 0..{w-1} x 0..{h-1})"
            else:
                ch = int(chars[ty][tx])
                glyph = chr(ch) if 32 <= ch < 127 else "?"
                if glyph in ("|", "-"):
                    detail = f"target is a wall ({glyph})"
                elif glyph == " ":
                    detail = "target is unseen (no path discovered yet — explore first)"
                else:
                    detail = f"target tile is `{glyph}` but no walkable path connects it"
        except Exception:
            detail = "no walkable path"
        return SkillResult([], f"No path from {start} to ({tx},{ty}): {detail}.", interrupted=True)
    if not path:
        return SkillResult([], f"Already at ({tx},{ty}).", interrupted=False)
    return SkillResult(
        actions=_enum_actions_to_indices(env, path),
        feedback=f"Pathing to ({x},{y}): {len(path)} steps.",
    )


def _stairs_up_xy(chars):
    """Return (x, y) of the first visible `<` tile, or None."""
    try:
        h, w = chars.shape
        for y in range(h):
            for x in range(w):
                if int(chars[y, x]) == ord('<'):
                    return (x, y)
    except Exception:
        pass
    return None


@registry.register("autoexplore", schema={
    "description": (
        "Walk toward the nearest unexplored region of the current level. "
        "Picks the closest frontier (walkable tile adjacent to an unseen "
        "tile) and pathfinds to it. Call repeatedly to explore the whole "
        "level. Halts and returns when the level is fully revealed."
    ),
    "parameters": {
        "max_steps": {
            "type": "integer",
            "default": 30,
            "description": "Cap on path length per call; lower means more chances to react.",
        },
    },
})
def autoexplore(env: NetHackCoreEnv, obs: StructuredObservation, max_steps: int = 30) -> SkillResult:
    chars, start = _current_chars_and_player(env)
    # Short-circuit: if stairs DOWN are already visible and reachable, walk
    # to them instead of any frontier. Trace 9071d001 showed the agent
    # calling autoexplore long after `>` was visible — autoexplore picked
    # the closest *frontier*, not the goal. Now the goal wins.
    try:
        h, w = (chars.shape[0], chars.shape[1]) if hasattr(chars, "shape") else (len(chars), len(chars[0]))
        stair_coords = None
        for sy in range(h):
            for sx in range(w):
                if int(chars[sy, sx]) == ord('>'):
                    stair_coords = (sx, sy)
                    break
            if stair_coords:
                break
        if stair_coords is not None and stair_coords != start:
            path = a_star(chars, start, stair_coords)
            if path:
                trimmed = path[:max_steps]
                acts = _enum_actions_to_indices(env, trimmed)
                # Auto-descend: append MORE + DOWN indices so a single
                # autoexplore call when `>` is visible reaches the stairs
                # AND descends without needing another LM round-trip.
                # Without this, the agent saw the stairs hint but then
                # picked move_to / move single-step instead of `descend`.
                try:
                    actions_list = env.underlying.unwrapped.actions
                    enum_to_idx = {int(a): i for i, a in enumerate(actions_list)}
                    more_idx = enum_to_idx.get(int(nethack.MiscAction.MORE), 0)
                    down_idx = enum_to_idx.get(int(nethack.MiscDirection.DOWN), 0)
                    acts = acts + [more_idx, down_idx]
                except Exception:
                    pass
                return SkillResult(
                    actions=acts,
                    feedback=(
                        f"Stairs DOWN at {stair_coords} are visible — "
                        f"pathing {len(trimmed)} steps and descending."
                    ),
                )
    except Exception:
        pass
    result = nearest_frontier(chars, start)
    # Skip-stairs-UP guard: trace 5/16 showed the frontier picker happily
    # returning the `<` tile (it's walkable + adjacent to closed door which
    # counts as unknown when door state is partially loaded). Walking to
    # `<` is pointless when our objective is to descend — re-pick from
    # find_frontiers and exclude the `<` tile. If no alternative exists,
    # fall through to the no-frontier branch (search/kick advice).
    if result is not None:
        target, _path = result
        up_xy = _stairs_up_xy(chars)
        if up_xy is not None and target == up_xy:
            from .pathfinding import find_frontiers, a_star
            alts = [
                f for f in find_frontiers(chars)
                if int(chars[f[1], f[0]]) != ord('<') and f != start
            ]
            best = None
            best_path = None
            for cand in alts:
                p = a_star(chars, start, cand)
                if p and (best_path is None or len(p) < len(best_path)):
                    best = cand
                    best_path = p
            if best is not None:
                result = (best, best_path)
            # else: keep original `<` target — better than no movement
    if result is None:
        # No frontier means we've explored everything reachable. If stairs
        # down aren't visible, the level likely has hidden passages — auto-
        # walk to a dead-end corridor tile and queue a search burst there.
        # This is the human heuristic: when stuck, search at corridor ends.
        has_stairs_down = any(b'>' in row.tobytes() for row in chars) if hasattr(chars, "__iter__") else False
        if has_stairs_down:
            tip = " Stairs `>` are visible — `move_to` them and `descend`."
            return SkillResult([], "Level appears fully explored from this position." + tip, interrupted=True)
        # Dead-end search: find walkable tiles (preferably corridor `#`) with
        # only one walkable cardinal neighbor. Path to the closest one and
        # queue 20 `search` actions there. NetHack `s` is action enum index
        # for search; appending many of them lets us search in one tool call.
        from .pathfinding import a_star
        try:
            h, w = chars.shape
            dead_ends = []
            for yy in range(h):
                for xx in range(w):
                    ch = int(chars[yy, xx])
                    if ch not in (ord('#'), ord('.')):
                        continue
                    n = 0
                    for ddx, ddy in ((0,-1),(1,0),(0,1),(-1,0)):
                        nx, ny = xx+ddx, yy+ddy
                        if 0 <= nx < w and 0 <= ny < h:
                            nc = int(chars[ny, nx])
                            if nc in (ord('.'), ord('#'), ord('+'),
                                     ord('<'), ord('>'), ord("'")):
                                n += 1
                    if n == 1 and (xx, yy) != start:
                        dead_ends.append((xx, yy))
            # Score: prefer corridor tiles over room floors (room dead-ends
            # are usually corners with nothing behind them).
            best = None
            best_path = None
            best_score = 1 << 30
            for de in dead_ends:
                p = a_star(chars, start, de)
                if not p:
                    continue
                is_corr = int(chars[de[1], de[0]]) == ord('#')
                score = len(p) + (0 if is_corr else 100)
                if score < best_score:
                    best_score = score
                    best = de
                    best_path = p
            if best is not None and best_path:
                # Pull a portable search-action enum from the env's last
                # observation; fall back to literal ord('s') (which works
                # via vi-key dispatch on most NLE action sets).
                from nle import nethack as _nh
                actions = env.underlying.unwrapped.actions
                enum_to_idx = {int(a): i for i, a in enumerate(actions)}
                search_action_idx = enum_to_idx.get(int(_nh.Command.SEARCH), int(ord('s')))
                path_idx = _enum_actions_to_indices(env, best_path[:max_steps])
                return SkillResult(
                    actions=path_idx + [search_action_idx] * 20,
                    feedback=(
                        f"No frontiers reachable; walking to dead-end "
                        f"{best} ({len(best_path)} steps) and searching 20× "
                        "for hidden passages."
                    ),
                )
        except Exception:
            pass
        # If we couldn't even find a dead-end, fall back to a strong tip.
        has_door = False
        try:
            has_door = any(b'+' in row.tobytes() for row in chars)
        except Exception:
            pass
        if has_door:
            tip = (
                " No `>` visible but a closed door `+` exists on the map. "
                "`move_to` adjacent to it; if it won't open, "
                "`kick(direction=...)` 2-5 times to break the lock."
            )
        else:
            tip = (
                " No `>` or dead-ends found. Call `search(times=20)` here "
                "and walk to wall corners to keep searching."
            )
        return SkillResult([], "Level appears fully explored." + tip, interrupted=True)
    target, path = result
    path = path[:max_steps]
    if not path:
        return SkillResult(
            [],
            f"Standing on a frontier already; try a different direction.",
            interrupted=True,
        )
    # Tail-hint: very short paths suggest the level is mostly explored —
    # the model often loops on autoexplore when frontiers are tiny. Surface
    # a tip so the next obs prompts a different action.
    suffix = ""
    if len(path) <= 2:
        has_stairs_down = any(b'>' in row.tobytes() for row in chars) if hasattr(chars, "__iter__") else False
        if has_stairs_down:
            suffix = " (short — `>` visible; consider `move_to` and `descend`)"
        else:
            # Short-frontier rerouting: if there's a known door/passage we
            # haven't been through, prefer pathing to it over the tiny
            # frontier. Picks the closest such door by A* path length.
            from .pathfinding import a_star as _astar2
            from .observations import extract_visible_features
            try:
                nle_env = env.underlying.unwrapped
                keys = nle_env._observation_keys
                last_obs_buf = nle_env.last_observation
                tty = last_obs_buf[keys.index("tty_chars")] if "tty_chars" in keys else None
            except Exception:
                tty = None
            if tty is not None:
                feats = extract_visible_features(tty)
                doors = []
                import re as _r
                for f in feats:
                    if f.startswith("door (open/gap)") or f.startswith("door (closed)"):
                        for mm in _r.finditer(r"\((\d+),(\d+)\)", f):
                            doors.append((int(mm.group(1)), int(mm.group(2))))
                best_door = None
                best_door_path = None
                for dxy in doors:
                    if dxy == start:
                        continue
                    p2 = _astar2(chars, start, dxy)
                    if p2 and len(p2) > 1 and (best_door_path is None or len(p2) < len(best_door_path)):
                        best_door = dxy
                        best_door_path = p2
                if best_door is not None and best_door_path is not None:
                    trimmed2 = best_door_path[:max_steps]
                    return SkillResult(
                        actions=_enum_actions_to_indices(env, trimmed2),
                        feedback=(
                            f"Autoexplore: frontier exhausted nearby; pathing "
                            f"to door at {best_door} ({len(trimmed2)} steps). "
                            f"If door is locked there, kick to break it."
                        ),
                    )
            suffix = " (short — try `search` at a wall or `move_to` a known feature)"
    return SkillResult(
        actions=_enum_actions_to_indices(env, path),
        feedback=f"Autoexploring toward {target}: {len(path)} steps." + suffix,
    )


@registry.register("find_and_descend", schema={
    "description": (
        "MEGA-SKILL for the corridor_explore / mini_dungeon objective. "
        "Bundles many decisions into one tool call:\n"
        "1) If `>` is currently visible, path to it and append `>` (descend).\n"
        "2) Else if a not-yet-walked door is reachable, path to it (kick "
        "automatically if message says locked next turn).\n"
        "3) Else walk to the nearest corridor dead-end and search 25 times.\n"
        "Returns up to ~80 NLE actions in one call. Re-call until reward "
        "for descent fires. Cheaper than micromanaging move()/move_to()."
    ),
    "parameters": {
        "max_actions": {
            "type": "integer",
            "default": 80,
            "description": "Cap on actions queued per call.",
        },
    },
})
def find_and_descend(env: NetHackCoreEnv, obs: StructuredObservation, max_actions: int = 80) -> SkillResult:
    chars, start = _current_chars_and_player(env)
    from .pathfinding import a_star, find_frontiers
    h, w = chars.shape
    # 1) Stairs DOWN visible? Path + descend.
    stair = None
    for yy in range(h):
        for xx in range(w):
            if int(chars[yy, xx]) == ord('>'):
                stair = (xx, yy); break
        if stair: break
    # Compute descend action indices (env.step takes indices not enum values).
    _acts = env.underlying.unwrapped.actions
    _e2i = {int(a): i for i, a in enumerate(_acts)}
    _more_i = _e2i.get(int(nethack.MiscAction.MORE), 0)
    _down_i = _e2i.get(int(nethack.MiscDirection.DOWN), _e2i.get(int(ord('>')), 0))
    if stair is not None:
        if stair == start:
            return SkillResult([_more_i, _down_i], "Already on `>` — descending.")
        p = a_star(chars, start, stair)
        if p:
            actions = _enum_actions_to_indices(env, p[:max_actions - 2])
            actions += [_more_i, _down_i]
            return SkillResult(
                actions=actions,
                feedback=f"`>` visible at {stair}; pathing {len(p)} steps and descending.",
            )
    # 2) Pick a reachable door (open/gap or closed) and path there.
    from .observations import extract_visible_features
    try:
        nle_env = env.underlying.unwrapped
        keys = nle_env._observation_keys
        tty = nle_env.last_observation[keys.index("tty_chars")] if "tty_chars" in keys else None
    except Exception:
        tty = None
    door_xy = None; door_path = None
    if tty is not None:
        import re as _r
        feats = extract_visible_features(tty)
        candidates = []
        for f in feats:
            if f.startswith("door (open/gap)") or f.startswith("door (closed)"):
                for mm in _r.finditer(r"\((\d+),(\d+)\)", f):
                    candidates.append((int(mm.group(1)), int(mm.group(2))))
        best_len = 1 << 30
        for dxy in candidates:
            if dxy == start: continue
            p2 = a_star(chars, start, dxy)
            if p2 and len(p2) < best_len:
                best_len = len(p2); door_xy = dxy; door_path = p2
    if door_xy is not None and door_path:
        return SkillResult(
            actions=_enum_actions_to_indices(env, door_path[:max_actions]),
            feedback=f"No `>` visible; pathing to door at {door_xy} ({len(door_path)} steps).",
        )
    # 3) Frontier — but prefer the FARTHEST reachable frontier so we
    # actually make progress per skill call. nearest_frontier returns the
    # immediate next walkable+unknown-adjacent tile, which is usually 1
    # step away on a corridor → the LM has to round-trip on every step.
    # Scan all frontiers and pick the longest-A* one (excluding <).
    fs = find_frontiers(chars)
    best_fr = None; best_fr_path = None; best_len = -1
    for fr in fs:
        if int(chars[fr[1], fr[0]]) == ord('<'):
            continue
        if fr == start:
            continue
        p = a_star(chars, start, fr)
        if p and len(p) > best_len:
            best_len = len(p); best_fr = fr; best_fr_path = p
    if best_fr is not None and best_fr_path:
        return SkillResult(
            actions=_enum_actions_to_indices(env, best_fr_path[:max_actions]),
            feedback=f"Pathing to far frontier at {best_fr} ({len(best_fr_path)} steps).",
        )
    # Dead-end fallback.
    dead_ends = []
    for yy in range(h):
        for xx in range(w):
            ch = int(chars[yy, xx])
            if ch not in (ord('#'), ord('.')): continue
            n = 0
            for ddx, ddy in ((0,-1),(1,0),(0,1),(-1,0)):
                nx, ny = xx+ddx, yy+ddy
                if 0 <= nx < w and 0 <= ny < h:
                    nc = int(chars[ny, nx])
                    if nc in (ord('.'), ord('#'), ord('+'), ord('<'), ord('>'), ord("'")):
                        n += 1
            if n == 1 and (xx, yy) != start:
                dead_ends.append((xx, yy))
    best_de = None; best_p = None; best_score = 1 << 30
    for de in dead_ends:
        p = a_star(chars, start, de)
        if not p: continue
        is_corr = int(chars[de[1], de[0]]) == ord('#')
        sc = len(p) + (0 if is_corr else 100)
        if sc < best_score:
            best_score = sc; best_de = de; best_p = p
    from nle import nethack as _nh
    actions_list = nle_env.actions if hasattr(nle_env, "actions") else env.underlying.unwrapped.actions
    enum_to_idx = {int(a): i for i, a in enumerate(actions_list)}
    s_idx = enum_to_idx.get(int(_nh.Command.SEARCH), int(ord('s')))
    if best_de is not None and best_p is not None:
        a = _enum_actions_to_indices(env, best_p[:max_actions - 25])
        a += [s_idx] * 25
        return SkillResult(
            actions=a,
            feedback=f"Walking to dead-end {best_de} ({len(best_p)} steps) and searching 25× for hidden passages.",
        )
    # No useful action; just search in place.
    return SkillResult(
        actions=[s_idx] * 25,
        feedback="No frontier/door/dead-end found; searching here 25× (consider `move` to a new corridor).",
    )


def list_skills() -> list[str]:
    return sorted(registry._skills.keys())


# ---------- journal skills (no env step, pure state mutation) ----------

@registry.register("add_note", schema={
    "description": (
        "Write or overwrite a note under a keyed slot. Use this to remember "
        "facts that will be useful many turns later: item locations, monster "
        "behaviors, dungeon layout summaries. Keep notes terse and concrete."
    ),
    "parameters": {
        "key": {"type": "string", "description": "Short slug, e.g. 'altar_dlvl_4' or 'cursed_items'."},
        "text": {"type": "string", "description": "The note body."},
    },
})
def add_note(env: NetHackCoreEnv, obs: StructuredObservation, key: str, text: str) -> SkillResult:
    def op(j: Journal) -> str:
        return j.add_note(key, text)
    return SkillResult(actions=[], feedback="", journal_op=op)


@registry.register("recall", schema={
    "description": (
        "Search your notes for the given query substring. Returns matching "
        "(key, text) pairs. Use this when you suspect you've seen something "
        "before but can't remember the detail."
    ),
    "parameters": {"query": {"type": "string"}},
})
def recall(env: NetHackCoreEnv, obs: StructuredObservation, query: str) -> SkillResult:
    def op(j: Journal) -> str:
        hits = j.recall(query)  # includes objective under key 'objective'
        if not hits:
            if not j.notes and not j.objective:
                return "No notes recorded yet. Use add_note(key, text) to record findings first."
            keys = (["objective"] if j.objective else []) + list(j.notes.keys())
            return f"No matches for '{query}'. Existing keys: {', '.join(keys[:6])}"
        return "Recalled:\n" + "\n".join(f"  - {k}: {t}" for k, t in hits)
    return SkillResult(actions=[], feedback="", journal_op=op)


@registry.register("pin_objective", schema={
    "description": (
        "Set your current top-level objective. Always rendered into every "
        "observation thereafter. Replace as your strategy evolves."
    ),
    "parameters": {"text": {"type": "string"}},
})
def pin_objective(env: NetHackCoreEnv, obs: StructuredObservation, text: str) -> SkillResult:
    def op(j: Journal) -> str:
        return j.pin_objective(text)
    return SkillResult(actions=[], feedback="", journal_op=op)


# ---------- wiki skills ----------

@registry.register("wiki_lookup", schema={
    "description": (
        "Fetch a named NetHack wiki page (e.g. 'cockatrice', 'mine town'). "
        "Use when you've identified a specific monster or feature and want "
        "the canonical lore."
    ),
    "parameters": {"entity": {"type": "string", "description": "Page title (case-insensitive)"}},
})
def wiki_lookup(env: NetHackCoreEnv, obs: StructuredObservation, entity: str) -> SkillResult:
    from .wiki import get_index
    idx = get_index()
    page = idx.lookup(entity)
    if page is None:
        # Surface nearest matches via substring search so the agent can
        # retry with a valid title instead of giving up on the tool.
        hits = idx.search(entity, k=3)
        if hits:
            suggestions = ", ".join(h.title for h in hits)
            return SkillResult(
                actions=[],
                feedback=f"No exact page {entity!r}. Did you mean: {suggestions}? (call wiki_lookup with one of these titles)",
                interrupted=True,
            )
        return SkillResult(
            actions=[], feedback=f"No wiki page for {entity!r} and no fuzzy matches.",
            interrupted=True,
        )
    return SkillResult(
        actions=[], feedback=f"[wiki: {page.title}] {page.short()}",
        interrupted=True,
    )


@registry.register("wiki_search", schema={
    "description": (
        "Substring-search the NetHack wiki. Returns up to k pages whose "
        "title or body contain the query. Use for fuzzy / exploratory "
        "questions ('what beats stunning?')."
    ),
    "parameters": {
        "query": {"type": "string"},
        "k": {"type": "integer", "default": 3},
    },
})
def wiki_search(env: NetHackCoreEnv, obs: StructuredObservation, query: str, k: int = 3) -> SkillResult:
    from .wiki import get_index
    pages = get_index().search(query, k=int(k))
    if not pages:
        return SkillResult(
            actions=[], feedback=f"No wiki results for {query!r}.",
            interrupted=True,
        )
    body = "\n\n".join(f"[{p.title}] {p.short(200)}" for p in pages)
    return SkillResult(actions=[], feedback=body, interrupted=True)
