"""Parse NetHack stats out of TTY status lines (for NLD human-data ingest).

The NLE human dataset (NLD-NAO / alt.org) stores games as ttyrec *terminal*
recordings, not stat vectors. To build a Valkyrie-by-depth stat model we decode
each frame's two-line bottom status and extract (depth, XP level, HP, max HP, and
the six attributes). Role is not on the status line, so :func:`detect_role`
scans a frame's text for the welcome banner ("... female human Valkyrie").

Standard NetHack 3.6 status lines look like::

    Agent the Skirmisher       St:18/03 Dx:14 Co:16 In:8 Wi:13 Ch:10  Neutral
    Dlvl:5 $:120 HP:54(54) Pw:12(12) AC:4 Xp:7/512 T:1234 Hungry

Strength is returned in NetHack's internal encoding (3..18; 18/01..18/00 ->
19..118; 19..25 -> 119..125), matching what the engine's ``modify(str=...)``
expects.
"""
from __future__ import annotations

import re
from typing import Optional

_ATTR_RE = {
    "str": re.compile(r"St:(\d+(?:/(?:\*\*|\d+))?)"),
    "dex": re.compile(r"Dx:(\d+)"),
    "con": re.compile(r"Co:(\d+)"),
    "int": re.compile(r"In:(\d+)"),
    "wis": re.compile(r"Wi:(\d+)"),
    "cha": re.compile(r"Ch:(\d+)"),
}
_DLVL_RE = re.compile(r"Dlvl:(-?\d+)")
_HP_RE = re.compile(r"HP:(-?\d+)\((\d+)\)")
_XP_RE = re.compile(r"(?:Xp|Exp):(\d+)")

# Roles as they appear in the welcome banner / "You are a ... <Role>".
_ROLES = (
    "Archeologist", "Barbarian", "Caveman", "Cavewoman", "Healer", "Knight",
    "Monk", "Priest", "Priestess", "Ranger", "Rogue", "Samurai", "Tourist",
    "Valkyrie", "Wizard",
)


def strength_to_internal(s: str) -> int:
    """Convert a displayed strength ('18/03', '18/**', '14', '20') to NetHack's
    internal 3..125 encoding."""
    s = s.strip()
    if "/" in s:
        base, pct = s.split("/", 1)
        if pct == "**" or pct == "00":
            return 118  # 18/** (== 18/00) maxes the percentile
        return 18 + int(pct)  # 18/01 -> 19 ... 18/99 -> 117
    n = int(s)
    if n <= 18:
        return n
    return 100 + n  # 19..25 -> 119..125


def parse_status(text: str) -> Optional[dict]:
    """Parse a frame's full text (the rendered terminal) into a stat dict.

    Returns None if the core fields (Dlvl + HP) aren't present (e.g. a menu or
    intro frame). Keys: depth, xp_level, hp, max_hp, str, dex, con, int, wis, cha
    (whichever are found; depth/hp/max_hp always present when non-None).
    """
    dlvl = _DLVL_RE.search(text)
    hp = _HP_RE.search(text)
    if not dlvl or not hp:
        return None
    out: dict = {
        "depth": int(dlvl.group(1)),
        "hp": int(hp.group(1)),
        "max_hp": int(hp.group(2)),
    }
    xp = _XP_RE.search(text)
    if xp:
        out["xp_level"] = int(xp.group(1))
    for name, rx in _ATTR_RE.items():
        m = rx.search(text)
        if not m:
            continue
        out[name] = strength_to_internal(m.group(1)) if name == "str" else int(m.group(1))
    return out


def detect_role(text: str) -> Optional[str]:
    """Detect the hero's role from a frame's text (welcome banner / title)."""
    for role in _ROLES:
        if role in text:
            return role
    return None


def is_valkyrie(text: str) -> bool:
    return "Valkyrie" in text
