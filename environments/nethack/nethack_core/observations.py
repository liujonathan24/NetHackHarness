"""
nethack_core.observations
=========================

Shape the raw NLE observation into a structured representation that surfaces
information the standard NLE setup hides from agents.

This is where the ICLR 2026 "Revisiting the NLE" fixes live:
    * menu extraction from tty_chars
    * inventory item resolution for prompts like "What do you want to throw? [abh]"
    * always-on inventory bag-of-words
    * role/race/alignment captured at episode start via #attributes

References:
    - iclr-blogposts.github.io/2026/blog/2026/revisiting-the-nle/
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .env import CoreObservation


# blstats indices per nle/include/nleobs.h (NetHack 3.6.x)
BLSTATS_IDX = {
    "x": 0, "y": 1, "strength_percentage": 2, "strength": 3,
    "dexterity": 4, "constitution": 5, "intelligence": 6,
    "wisdom": 7, "charisma": 8, "score": 9, "hitpoints": 10,
    "max_hitpoints": 11, "depth": 12, "gold": 13, "energy": 14,
    "max_energy": 15, "armor_class": 16, "monster_level": 17,
    "experience_level": 18, "experience_points": 19, "time": 20,
    "hunger_state": 21, "carrying_capacity": 22, "dungeon_number": 23,
    "level_number": 24, "condition": 25,
}


@dataclass
class InventoryItem:
    letter: str                    # e.g. "a"
    description: str               # e.g. "a +1 long sword (weapon in hand)"
    glyph: int                     # NLE inv_glyphs entry
    category: Optional[str] = None # weapon, armor, food, potion, scroll, ...
    is_worn: bool = False
    is_wielded: bool = False
    is_blessed: Optional[bool] = None  # None means unidentified status


@dataclass
class MenuOption:
    letter: str
    description: str


@dataclass
class StructuredObservation:
    """The thing we hand to the skill/code/chat layer."""
    map_view: str                          # ascii dungeon, menu region masked
    messages: list[str]
    inventory: list[InventoryItem]
    status: dict[str, int]
    character: dict[str, str]              # role/race/alignment/gender
    menu: Optional[list[MenuOption]] = None
    inventory_prompt: Optional[dict] = None  # {"action": "throw", "letters": [...], "items": [...]}
    adjacent: dict[str, str] = field(default_factory=dict)  # N/NE/E/.../NW -> description
    under_player: Optional[str] = None  # what tile the @ is standing on
    yn_prompt: Optional[dict] = None  # {"question": str, "default": "y"|"n"|None, "answer": "y"|"n"|"ESC"}


# ---------- menu extraction ----------

_MENU_END_RE = re.compile(r"\(end\)|\(\d+ of \d+\)")
_MENU_LINE_RE = re.compile(r"^\s*([a-zA-Z])\s+[-+]\s+(.*?)\s*$")
# Anywhere-on-row pattern used when the menu sits to the right of dungeon.
_MENU_INLINE_RE = re.compile(r"(?<![a-zA-Z])([a-zA-Z])\s+[-+]\s+\S")


def extract_menu(tty_chars: np.ndarray) -> Optional[list[MenuOption]]:
    """
    Detect an open menu and return its options.

    NetHack menus are anchored at the bottom of the screen with "(end)" or
    "(N of M)" markers. Lines look like 'a - some item description'.

    Returns None if no menu is open. As a side effect (via _menu_left_column)
    callers can also figure out which screen column the menu starts at; we
    don't return it here to keep the API narrow. See `extract_menu_region`
    if you need both the options *and* the column for masking.
    """
    options, _ = extract_menu_region(tty_chars)
    return options


def extract_menu_region(
    tty_chars: np.ndarray,
) -> tuple[Optional[list[MenuOption]], Optional[int]]:
    """
    Like extract_menu, but also returns the leftmost screen column at which
    any menu line starts. That column is what render_map_view uses to mask
    the menu out of the dungeon view.
    """
    # Don't rstrip — we need to count leading whitespace to compute the
    # menu column.
    rows = ["".join(chr(c) for c in row) for row in tty_chars]
    end_row = None
    for i in range(len(rows) - 1, -1, -1):
        if _MENU_END_RE.search(rows[i]):
            end_row = i
            break
    if end_row is None:
        return None, None

    # We need to match menu lines whether they sit at column 0 (the menu fills
    # the screen) or at a right-side column (the dungeon is visible to the
    # left). Use a "search anywhere on the row" pattern and record the column.
    options: list[MenuOption] = []
    columns: list[int] = []
    for i in range(end_row - 1, -1, -1):
        m = _MENU_INLINE_RE.search(rows[i])
        if m:
            # The pattern's full match starts at the option letter. Capture
            # group 1 is the letter; group 2 is the description (up to row end).
            letter = m.group(1)
            # Take everything after the dash/plus marker through the end of the
            # row (rstripped) as the description.
            desc_start = m.end(1)
            tail = rows[i][desc_start:].rstrip()
            # Strip the leading "  - " or "  + "
            tail = re.sub(r"^\s+[-+]\s+", "", tail)
            options.append(MenuOption(letter=letter, description=tail))
            columns.append(m.start(1))
        elif options:
            break
    options.reverse()
    if not options:
        return None, None
    left_col = min(columns) if columns else None
    return options, left_col


# ---------- inventory prompt extraction ----------

_INV_PROMPT_RE = re.compile(
    r"What do you want to (\w+)\??\s*\[([a-zA-Z\$\*\?]+)"
)


def extract_inventory_prompt(
    message: str, inventory: list[InventoryItem]
) -> Optional[dict]:
    """
    Detect prompts like "What do you want to throw? [abh]" and resolve the
    letters to actual inventory items. The whole point: model picks by item
    description, not by letter.
    """
    m = _INV_PROMPT_RE.search(message)
    if not m:
        return None
    action, letter_set = m.group(1), m.group(2)
    inv_by_letter = {item.letter: item for item in inventory}
    choices = [inv_by_letter[ch] for ch in letter_set if ch in inv_by_letter]
    return {"action": action, "letters": list(letter_set), "items": choices}


# ---------- inventory parsing ----------

def parse_inventory(inv_strs: np.ndarray, inv_letters: np.ndarray, inv_glyphs: np.ndarray) -> list[InventoryItem]:
    """Decode NLE's inv_strs into structured InventoryItems.

    Fast path: only iterate over slots whose letter is non-zero (NLE
    pre-allocates 55 slots; the vast majority are empty during early game).
    Numpy nonzero() is O(n) but in C and ~50x cheaper than Python iteration.
    For each occupied slot, we still decode the row in Python — that's the
    irreducible cost. Was: 258 us per call (whole-array iteration). Now:
    ~50 us when only 2-3 slots are filled, scales linearly with item count.
    """
    items = []
    nonzero = np.nonzero(inv_letters)[0]
    for idx in nonzero:
        str_row = inv_strs[idx]
        # Find the first NUL byte in C-speed rather than .split on a bytes
        # object — np.searchsorted-style is unavailable here, but tobytes()
        # is still cheap.
        raw = bytes(str_row)
        nul = raw.find(b"\x00")
        desc = raw[:nul if nul >= 0 else len(raw)].decode("ascii", errors="replace").strip()
        if not desc:
            continue
        items.append(InventoryItem(
            letter=chr(int(inv_letters[idx])),
            description=desc,
            glyph=int(inv_glyphs[idx]),
            is_worn="being worn" in desc,
            is_wielded="weapon in hand" in desc or "wielded" in desc,
            is_blessed=_parse_blessed(desc),
        ))
    return items


def _parse_blessed(desc: str) -> Optional[bool]:
    if "blessed" in desc:
        return True
    if "cursed" in desc:
        return False
    if "uncursed" in desc:
        return False
    return None  # unidentified


# ---------- status ----------

def parse_status(blstats: np.ndarray) -> dict[str, int]:
    return {name: int(blstats[idx]) for name, idx in BLSTATS_IDX.items()}


# ---------- character (role/race/alignment) ----------

# These are populated once at reset time by invoking #attributes through the env
# and parsing the resulting menu. See nethack_core.skills.bootstrap_character().
# We keep this as a structured dict so downstream code can use it without
# re-parsing on every step.

def parse_character_from_attributes_menu(menu_text: str) -> dict[str, str]:
    """
    Parse the #attributes display into role/race/alignment/gender.

    Lines we care about look like:
        "You are a Stripling, a lawful female human Valkyrie."

    TODO(jonathan): this is brittle. Replace with parsing of NLE's
    `role`, `race`, `align` exposed in extended observations if available.
    """
    out = {}
    m = re.search(
        r"a (lawful|neutral|chaotic) (male|female|neuter) (\w+) (\w+)",
        menu_text,
    )
    if m:
        out["alignment"] = m.group(1)
        out["gender"] = m.group(2)
        out["race"] = m.group(3)
        out["role"] = m.group(4)
    return out


# ---------- map view ----------

def render_map_view(
    tty_chars: np.ndarray,
    menu: Optional[list[MenuOption]] = None,
    menu_left_col: Optional[int] = None,
) -> str:
    """
    Render the playable dungeon area as ASCII. Mask out any menu region so
    the dungeon and menu don't visually conflate.

    If `menu_left_col` is provided (from extract_menu_region), the renderer
    truncates every row at that column. Otherwise it falls back to a heuristic
    that scans every row for the leftmost run of menu-letter pattern.
    """
    rows = ["".join(chr(c) for c in row) for row in tty_chars]
    if menu is not None:
        if menu_left_col is None:
            menu_left_col = _infer_menu_left_col(rows)
        if menu_left_col is not None and menu_left_col > 0:
            rows = [_strip_right_menu(r, menu_left_col) for r in rows]
    return "\n".join(r.rstrip() for r in rows)


def _strip_right_menu(row: str, left_col: int) -> str:
    """Cut a row at the menu's left column. Pad short rows untouched."""
    if len(row) <= left_col:
        return row
    return row[:left_col]


def _infer_menu_left_col(rows: list[str]) -> Optional[int]:
    """Cheap fallback: leftmost column where any row looks menu-like."""
    candidates = []
    for r in rows:
        m = _MENU_INLINE_RE.search(r)
        if m:
            candidates.append(m.start())
    return min(candidates) if candidates else None


# ---------- adjacency + hostiles extraction ----------

# NetHack uppercase-letter monsters are often dangerous (Drow, Mind flayer,
# Vampire, etc.) but many lowercase are too (cockatrices `c`, leprechauns
# `l`). Cheapest meaningful signal: ANY non-@-non-player letter glyph adjacent
# to or visible near the player is "a monster you should consider".
#
# Punctuation we exclude (treated as terrain/dungeon features):
_TERRAIN_CHARS = set(b". # | - + < > _ { } \\ ^ ` \" } / ( ) [ ] ' = ? ! * | $")
# The player itself:
_PLAYER_CHAR = ord("@")


def _player_position(tty_chars) -> Optional[tuple[int, int]]:
    """Find the player marker @ in the dungeon area of the tty.
    Returns (x, y) or None. Dungeon rows are 1..21 (skip status lines 0 and 22-23)."""
    for y in range(1, min(22, tty_chars.shape[0])):
        for x in range(tty_chars.shape[1]):
            if tty_chars[y, x] == _PLAYER_CHAR:
                return (x, y)
    return None


_DIR_OFFSETS = {
    "N": (0, -1), "NE": (1, -1), "E": (1, 0), "SE": (1, 1),
    "S": (0, 1), "SW": (-1, 1), "W": (-1, 0), "NW": (-1, -1),
}


def extract_under_player(tty_chars, chars, message: str = "") -> Optional[str]:
    """Describe the tile the player is standing on.

    NetHack's `chars` array shows `@` at the player's position (the player
    sprite overlays terrain), so we can't read it directly. Instead we
    parse the message buffer for "There is a X here" / "You see here X"
    phrases — NLE prints those whenever the player arrives on an
    interesting tile (stairs, altar, fountain, items).

    Returns a one-line description or None if the message buffer didn't
    surface the tile. Empty/uninformative tiles ("floor") return None so
    we don't clutter the obs with redundant info.
    """
    if not message:
        return None
    m = message.strip()
    # Order: stairs first (most load-bearing), then features, then "you see".
    for pattern, desc in _MESSAGE_PATTERNS:
        if pattern in m.lower():
            return desc
    # Generic "You see here X" → return what's here.
    import re as _re
    match = _re.search(r"You (?:feel|see)(?: something)? here[: ]+([^.]+)\.", m)
    if match:
        return f"on tile: {match.group(1).strip()}"
    return None


# Substring → description. Lowercase comparison.
_MESSAGE_PATTERNS = (
    ("there is a staircase down here", "stairs DOWN (>) — call `descend` to go to next dungeon level"),
    ("there is a staircase up here", "stairs UP (<) — these go BACK to a previous level, NOT down"),
    ("there is an altar", "altar (_) — drop items to identify; pray with care"),
    ("there is a fountain here", "fountain ({) — risky to quaff/dip but can yield wishes"),
    ("there is a sink here", "sink (#)"),
    ("there is a grave here", "grave (\\)"),
    ("there is a throne here", "throne (\\)"),
    ("there is a fountain", "fountain ({)"),
)


_TERRAIN_DESCRIPTIONS = {
    ord("."): "floor (.)",
    ord("#"): "corridor (#)",
    ord(">"): "stairs DOWN (>) — call `descend` to go to next dungeon level",
    ord("<"): "stairs UP (<) — these go BACK to a previous level, NOT down",
    ord("_"): "altar (_)",
    ord("{"): "fountain ({)",
    ord("}"): "moat (})",
    ord("\\"): "throne (\\)",
    ord("|"): "wall (|)",
    ord("-"): "wall (-)",
    ord("+"): "door (+)",
    ord("/"): "wand (/)",
    ord("!"): "potion (!)",
    ord("?"): "scroll (?)",
    ord("="): "ring (=)",
    ord("("): "weapon (",
    ord("["): "armor ([)",
    ord("$"): "gold ($)",
    ord("`"): "boulder (`)",
    ord('"'): "amulet (\")",
}


def _describe_terrain(ch: int) -> str:
    return _TERRAIN_DESCRIPTIONS.get(ch, f"unknown ({chr(ch) if 32 <= ch < 127 else '?'})")


_ADJACENT_LABEL_OVERRIDE = {
    ">": ">(stairs DOWN)",
    "<": "<(stairs UP)",
    "_": "_(altar)",
    "{": "{(fountain)",
    "}": "}(moat)",
    "\\": "\\(throne)",
    "$": "$(gold)",
}

# Class hints for adjacent letter glyphs. NetHack uses ~50 monster classes;
# we cover the most common spawn classes for early game so the agent stops
# inventing names like "fireplace" for `f`. Trace 9071d001 showed the model
# repeatedly mislabeling `f` as fireplace/fountain/floor.
_MONSTER_CLASS_HINT = {
    "a": "ant/insect", "b": "blob", "c": "cockatrice/canary",
    "d": "dog/canine", "e": "floating eye/sphere", "f": "cat/small feline",
    "g": "gnome/gremlin", "h": "dwarf/hobbit", "i": "imp",
    "j": "jelly", "k": "kobold", "l": "leprechaun",
    "m": "mimic", "n": "nymph", "o": "orc",
    "p": "piercer", "q": "quadruped", "r": "rat",
    "s": "spider/scorpion", "t": "trapper", "u": "unicorn",
    "v": "vortex", "w": "worm", "x": "grid bug",
    "y": "light", "z": "zruty",
    "B": "bat", "D": "dragon", "G": "gnome lord",
    "H": "giant", "K": "kobold lord", "S": "snake",
    "Z": "zombie",
}


# NLE glyph offsets. Pets live in [GLYPH_PET_OFF, GLYPH_PET_OFF + NUMMONS).
# Imported lazily so observations.py stays importable without nle (tests).
_GLYPH_MON_OFF = 0
_GLYPH_PET_OFF = 381
_NUMMONS = 381


def _glyph_kind(glyph_id: int) -> Optional[str]:
    """Return 'pet' if glyph_id is a tame monster, 'hostile' if a wild
    monster, None otherwise. Uses NLE's standard glyph layout."""
    if _GLYPH_PET_OFF <= glyph_id < _GLYPH_PET_OFF + _NUMMONS:
        return "pet"
    if _GLYPH_MON_OFF <= glyph_id < _GLYPH_MON_OFF + _NUMMONS:
        return "hostile"
    return None


def extract_adjacent(tty_chars, glyphs=None) -> dict[str, str]:
    """8-neighborhood of the player. Each direction maps to either the raw
    glyph character or — for highly load-bearing tiles like stairs — a
    human-readable label so the LM doesn't confuse `<` with descent. Empty
    dict if player not found.

    When `glyphs` (the NLE 21x79 glyph-id array) is provided, monster
    letters are annotated with pet/hostile status — load-bearing because
    the 9071d001 trace showed the agent repeatedly attacking its own
    kitten (`f` looks the same hostile or tame in the tty)."""
    pos = _player_position(tty_chars)
    if pos is None:
        return {}
    x, y = pos
    # tty_chars dungeon area is rows 1..21; glyphs is the (21, 79) dungeon
    # map indexed from row 0. So glyph row = tty row - 1.
    out: dict[str, str] = {}
    for d, (dx, dy) in _DIR_OFFSETS.items():
        nx, ny = x + dx, y + dy
        if 0 <= ny < tty_chars.shape[0] and 0 <= nx < tty_chars.shape[1]:
            ch = int(tty_chars[ny, nx])
            glyph = chr(ch) if 32 <= ch < 127 else "?"
            kind: Optional[str] = None
            if glyphs is not None and 1 <= ny <= 21:
                gy = ny - 1
                if 0 <= gy < glyphs.shape[0] and 0 <= nx < glyphs.shape[1]:
                    kind = _glyph_kind(int(glyphs[gy, nx]))
            if glyph in _ADJACENT_LABEL_OVERRIDE:
                out[d] = _ADJACENT_LABEL_OVERRIDE[glyph]
            elif glyph in _MONSTER_CLASS_HINT:
                base = f"{glyph}({_MONSTER_CLASS_HINT[glyph]})"
                if kind == "pet":
                    out[d] = f"{base}[PET — don't attack]"
                elif kind == "hostile":
                    out[d] = f"{base}[hostile]"
                else:
                    out[d] = base
            else:
                out[d] = glyph
    return out


_FEATURE_GLYPHS = {
    ord(">"): "stairs DOWN",
    ord("<"): "stairs UP",
    ord("_"): "altar",
    ord("{"): "fountain",
    ord("\\"): "throne",
    ord("$"): "gold",
}


def extract_visible_features(tty_chars) -> list[str]:
    """Return a list of important map features with (x, y) coordinates.

    Returned format: ["stairs DOWN at (47,6)", "altar at (12,3)"]. Saves the
    model from scanning the full ASCII tty grid to locate a `>` it can navigate
    to. Trace 9071d001 showed Qwen3.5-9B confusing `<` for `>` and never
    finding the actual stairs down despite 66 autoexplore calls.

    Coordinates use the same y-origin as the tty (row 0 is the top message
    line; the map starts around row 1).
    """
    out: list[str] = []
    seen_by_label: dict[str, list[tuple[int, int]]] = {}
    for y in range(1, min(22, tty_chars.shape[0])):
        for x in range(tty_chars.shape[1]):
            ch = int(tty_chars[y, x])
            label = _FEATURE_GLYPHS.get(ch)
            if label:
                seen_by_label.setdefault(label, []).append((x, y))
    for label in ("stairs DOWN", "stairs UP", "altar", "fountain", "throne", "gold"):
        coords = seen_by_label.get(label, [])
        if not coords:
            continue
        # Cap at 3 instances per label.
        coord_strs = ", ".join(f"({x},{y})" for x, y in coords[:3])
        more = "" if len(coords) <= 3 else f" +{len(coords)-3} more"
        out.append(f"{label} at {coord_strs}{more}")
    return out


def extract_hostiles_in_sight(tty_chars) -> list[str]:
    """Return a deduplicated list of visible glyph chars that look like
    monsters (letter, not @). Lowercase 'd' = "dog or jackal-class"; we
    don't have monster-name resolution here — that needs the glyph table.

    Returned format: ["d (×2)", "k", "@ (player)"] sorted alphabetically.
    Cheap and lossy but lets the agent see "there's something in the room"
    without parsing the full map."""
    seen: dict[str, int] = {}
    for y in range(1, min(22, tty_chars.shape[0])):
        for x in range(tty_chars.shape[1]):
            ch = int(tty_chars[y, x])
            if ch == _PLAYER_CHAR:
                continue
            if (ch >= ord("a") and ch <= ord("z")) or (ch >= ord("A") and ch <= ord("Z")):
                key = chr(ch)
                seen[key] = seen.get(key, 0) + 1
    if not seen:
        return []
    return [f"{k} (×{v})" if v > 1 else k for k, v in sorted(seen.items())]


# ---------- top-level entry point ----------

_YN_PROMPT_RE = re.compile(r"\[(yn|ynq|yna|ynaq)\](?:\s*\(([yn])\))?", re.IGNORECASE)
# Policy: prompts where we usually want YES (the model already invoked the
# precipitating action). Match against lowercased question text.
_YN_YES_PATTERNS = (
    "continue?",
    "stop eating",     # interrupt eat-spam (yes = stop and conserve)
    "swap places",     # accept friendly swaps
    "force fight",
    "force attack",
    "pick up",         # auto-pickup confirmation; yes is the safe default
    "see?",            # "do you want to see?" (inventory list); yes is fine
)
_YN_NO_PATTERNS = (
    "really quit",
    "really save",
    "die?",
    "stop praying",
    "abort",
    "throw away",      # do not destroy items
    "really attack",   # peaceful safety net: NetHack only shows this for
                       # peaceful targets; default (n) preserves the pet.
                       # The model's `attack` tool call gets cancelled —
                       # safer than killing pets / triggering alignment
                       # penalties. If we ever add a `force_attack` skill,
                       # route that through a different path.
)


def extract_yn_prompt(message: str) -> Optional[dict]:
    """Detect NetHack y/n confirmation prompts in the message buffer.

    Returns {"question": ..., "default": "y"|"n"|None, "answer": "y"|"n"|"ESC"}
    or None if no y/n prompt is present.

    These prompts (e.g. "Really attack the little dog? [yn] (n)") confused
    Qwen3.5-9B into calling menu_option spuriously in 42% of v0.0.33 turns —
    they look superficially like a menu but require a single-letter keystroke.
    The harness now auto-answers per policy: pro-action when the model already
    asked for the action (attack, pray, eat), conservative otherwise.
    """
    if not message:
        return None
    m = _YN_PROMPT_RE.search(message)
    if not m:
        return None
    parens_default = m.group(2)
    q_lower = message.lower()
    if any(p in q_lower for p in _YN_YES_PATTERNS):
        answer = "y"
    elif any(p in q_lower for p in _YN_NO_PATTERNS):
        answer = "n"
    elif parens_default:
        answer = parens_default.lower()
    else:
        answer = "ESC"
    return {"question": message.strip(), "default": parens_default, "answer": answer}


def shape(obs: CoreObservation, character: dict[str, str]) -> StructuredObservation:
    """Single entry: raw NLE obs -> StructuredObservation."""
    message = bytes(obs.message).split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    inventory = parse_inventory(obs.inv_strs, obs.inv_letters, obs.inv_glyphs)
    menu, menu_left_col = extract_menu_region(obs.tty_chars)
    inv_prompt = extract_inventory_prompt(message, inventory)
    status = parse_status(obs.blstats)
    adjacent = extract_adjacent(obs.tty_chars, getattr(obs, "glyphs", None))
    under = extract_under_player(obs.tty_chars, obs.chars, message)
    yn = extract_yn_prompt(message)
    return StructuredObservation(
        map_view=render_map_view(obs.tty_chars, menu, menu_left_col),
        messages=[message] if message else [],
        inventory=inventory,
        status=status,
        character=character,
        menu=menu,
        inventory_prompt=inv_prompt,
        adjacent=adjacent,
        under_player=under,
        yn_prompt=yn,
    )
