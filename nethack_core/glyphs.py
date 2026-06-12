"""Pure-Python glyph classification (no nle).

Reimplements the glyph predicates the harness needs without importing
``nle.nethack``. Every constant and predicate is derived directly from the
NetHack fork the harness runs on:

  * Offset chain + predicate ranges: ``third_party/NetHack/src/include/display.h``
    (``GLYPH_*_OFF`` macros, ``glyph_is_*`` macros, ``MAX_GLYPH``).
  * Counts: ``NUMMONS`` (381), ``NUM_OBJECTS`` (453), ``MAXPCHARS`` (96).
  * Trap range: ``trap_to_defsym(1) == S_arrow_trap == 42``
    (``src/include/rm.h``), ``TRAPNUM == 24`` (``src/include/trap.h``).

These are deterministic functions of NetHack's fixed glyph numbering, so the
predicates can be expressed as plain integer range tests. The values match the
fork engine exactly (and ``nle.nethack`` for the shared numbering); see
``tests`` for the parity check that asserted equality over the full glyph range.

All predicates accept an int OR a numpy array and return a Python ``bool`` or a
numpy bool array correspondingly, mirroring nle's vectorized semantics.
"""

from __future__ import annotations

import numpy as np

# --- Counts (from the fork's generated tables / headers) --------------------
NUMMONS = 381
NUM_OBJECTS = 453
MAXPCHARS = 96

# --- Trap glyph sub-range within cmap (rm.h / trap.h) -----------------------
_S_ARROW_TRAP = 42      # trap_to_defsym(1) == S_arrow_trap
TRAPNUM = 24

# --- Offset chain (display.h GLYPH_*_OFF) -----------------------------------
GLYPH_MON_OFF = 0
GLYPH_PET_OFF = NUMMONS + GLYPH_MON_OFF                       # 381
GLYPH_INVIS_OFF = NUMMONS + GLYPH_PET_OFF                     # 762
GLYPH_DETECT_OFF = 1 + GLYPH_INVIS_OFF                        # 763
GLYPH_BODY_OFF = NUMMONS + GLYPH_DETECT_OFF                   # 1144
GLYPH_RIDDEN_OFF = NUMMONS + GLYPH_BODY_OFF                   # 1525
GLYPH_OBJ_OFF = NUMMONS + GLYPH_RIDDEN_OFF                    # 1906
GLYPH_CMAP_OFF = NUM_OBJECTS + GLYPH_OBJ_OFF                  # 2359
GLYPH_STATUE_OFF = 5595                                       # see MAX_GLYPH note
MAX_GLYPH = 5976

GLYPH_INVISIBLE = GLYPH_INVIS_OFF


def _as_int_array(g):
    """Return (array, was_scalar). Keeps int64 for safe range arithmetic."""
    arr = np.asarray(g)
    scalar = arr.ndim == 0
    return arr.astype(np.int64, copy=False), scalar


def _ret(mask, scalar):
    return bool(mask) if scalar else np.asarray(mask, dtype=bool)


def _in_range(g, lo, hi):
    """``lo <= g < hi`` for int or array g, returning bool / bool array."""
    arr, scalar = _as_int_array(g)
    mask = (arr >= lo) & (arr < hi)
    return _ret(mask, scalar)


# --- Monster predicates -----------------------------------------------------
def glyph_is_normal_monster(g):
    return _in_range(g, GLYPH_MON_OFF, GLYPH_MON_OFF + NUMMONS)


def glyph_is_pet(g):
    return _in_range(g, GLYPH_PET_OFF, GLYPH_PET_OFF + NUMMONS)


def glyph_is_ridden_monster(g):
    return _in_range(g, GLYPH_RIDDEN_OFF, GLYPH_RIDDEN_OFF + NUMMONS)


def glyph_is_detected_monster(g):
    return _in_range(g, GLYPH_DETECT_OFF, GLYPH_DETECT_OFF + NUMMONS)


def glyph_is_monster(g):
    """normal | pet | ridden | detected (display.h glyph_is_monster)."""
    arr, scalar = _as_int_array(g)
    mask = (
        ((arr >= GLYPH_MON_OFF) & (arr < GLYPH_MON_OFF + NUMMONS))
        | ((arr >= GLYPH_PET_OFF) & (arr < GLYPH_PET_OFF + NUMMONS))
        | ((arr >= GLYPH_RIDDEN_OFF) & (arr < GLYPH_RIDDEN_OFF + NUMMONS))
        | ((arr >= GLYPH_DETECT_OFF) & (arr < GLYPH_DETECT_OFF + NUMMONS))
    )
    return _ret(mask, scalar)


# --- Object predicates ------------------------------------------------------
def glyph_is_normal_object(g):
    return _in_range(g, GLYPH_OBJ_OFF, GLYPH_OBJ_OFF + NUM_OBJECTS)


def glyph_is_body(g):
    return _in_range(g, GLYPH_BODY_OFF, GLYPH_BODY_OFF + NUMMONS)


def glyph_is_statue(g):
    return _in_range(g, GLYPH_STATUE_OFF, GLYPH_STATUE_OFF + NUMMONS)


def glyph_is_object(g):
    """normal object | statue | body (display.h glyph_is_object)."""
    arr, scalar = _as_int_array(g)
    mask = (
        ((arr >= GLYPH_OBJ_OFF) & (arr < GLYPH_OBJ_OFF + NUM_OBJECTS))
        | ((arr >= GLYPH_STATUE_OFF) & (arr < GLYPH_STATUE_OFF + NUMMONS))
        | ((arr >= GLYPH_BODY_OFF) & (arr < GLYPH_BODY_OFF + NUMMONS))
    )
    return _ret(mask, scalar)


# --- Cmap / trap predicates -------------------------------------------------
def glyph_is_cmap(g):
    return _in_range(g, GLYPH_CMAP_OFF, GLYPH_CMAP_OFF + MAXPCHARS)


def glyph_is_trap(g):
    lo = GLYPH_CMAP_OFF + _S_ARROW_TRAP
    return _in_range(g, lo, lo + TRAPNUM)


def glyph_is_invisible(g):
    arr, scalar = _as_int_array(g)
    return _ret(arr == GLYPH_INVISIBLE, scalar)


# --- glyph -> monster index (display.h glyph_to_mon, scalar) ----------------
def glyph_to_mon(g):
    """Monster index for a monster/pet/ridden/detected/statue glyph.

    Mirrors display.h's ``glyph_to_mon`` for the monster-bearing glyph classes
    the harness queries (it only calls this on glyphs already known to be
    monsters/pets). Scalar in, scalar out.
    """
    g = int(g)
    if GLYPH_MON_OFF <= g < GLYPH_MON_OFF + NUMMONS:
        return g - GLYPH_MON_OFF
    if GLYPH_PET_OFF <= g < GLYPH_PET_OFF + NUMMONS:
        return g - GLYPH_PET_OFF
    if GLYPH_DETECT_OFF <= g < GLYPH_DETECT_OFF + NUMMONS:
        return g - GLYPH_DETECT_OFF
    if GLYPH_RIDDEN_OFF <= g < GLYPH_RIDDEN_OFF + NUMMONS:
        return g - GLYPH_RIDDEN_OFF
    if GLYPH_STATUE_OFF <= g < GLYPH_STATUE_OFF + NUMMONS:
        return g - GLYPH_STATUE_OFF
    # NO_GLYPH equivalent: not a monster-bearing glyph.
    return NUMMONS


# --- cmap index -> clean ASCII char LUT -------------------------------------
# Derived from the fork's cmap symbol table (drawing.c / def_*_syms, the
# ``symdef.explanation`` strings). The harness only needs the clean-char
# mapping, not the strings, so the resolved LUT is baked here. Rule that
# produced it (over each cmap index's explanation string):
#   index 0 (dark/unexplored)          -> ' '
#   'staircase down' / 'ladder down'   -> '>'
#   'staircase up'   / 'ladder up'     -> '<'
#   'closed door'                      -> '|'  (BLOCKED for pathing)
#   doorway/open door/floor/corridor/dark part of a room/staircase/ladder/
#     altar/sink/fountain/ice/lowered drawbridge/throne -> '.'
#   everything else (walls/rock/traps/hazards) -> '|'
# Closed-door cmap indices are 15 and 16.
_CMAP_CLEAN_CHARS = bytes([
    32, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124,
    46, 46, 46, 124, 124, 124, 124, 46, 46, 46, 46, 60, 62, 60,
    62, 46, 124, 46, 46, 46, 124, 46, 124, 46, 46, 124, 124, 124,
    124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124,
    124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124,
    124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124,
    124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124, 124,
    124, 124, 124, 124, 124, 124, 124, 124,
])
assert len(_CMAP_CLEAN_CHARS) == MAXPCHARS

#: cmap indices whose explanation is "closed door" (BLOCKED for pathing).
CMAP_CLOSED_DOOR_INDICES = frozenset({15, 16})


def cmap_clean_char_lut() -> np.ndarray:
    """Return cmap-index -> clean ASCII char LUT (uint8, length MAXPCHARS)."""
    return np.frombuffer(_CMAP_CLEAN_CHARS, dtype=np.uint8)


# --- Monster names (permonst(idx).mname) ------------------------------------
# The fork's monster table (``src/src/monst.c`` -> generated
# ``src/build/include/pm.h``, NUMMONS == 381). Cerberus (``#ifdef CHARON``) and
# beholder (``#if 0``) are compiled out, so this build's table is identical to
# nle's ordering; index == PM_* == GLYPH_MON_OFF offset. Baked here so the
# harness need not link the C ``permonst`` accessor.
MONSTER_NAMES = (
    'giant ant', 'killer bee', 'soldier ant', 'fire ant', 'giant beetle', 'queen bee',
    'acid blob', 'quivering blob', 'gelatinous cube', 'chickatrice', 'cockatrice', 'pyrolisk',
    'jackal', 'fox', 'coyote', 'werejackal', 'little dog', 'dingo', 'dog', 'large dog',
    'wolf', 'werewolf', 'winter wolf cub', 'warg', 'winter wolf', 'hell hound pup',
    'hell hound', 'gas spore', 'floating eye', 'freezing sphere', 'flaming sphere',
    'shocking sphere', 'kitten', 'housecat', 'jaguar', 'lynx', 'panther', 'large cat',
    'tiger', 'gremlin', 'gargoyle', 'winged gargoyle', 'hobbit', 'dwarf', 'bugbear',
    'dwarf lord', 'dwarf king', 'mind flayer', 'master mind flayer', 'manes', 'homunculus',
    'imp', 'lemure', 'quasit', 'tengu', 'blue jelly', 'spotted jelly', 'ochre jelly',
    'kobold', 'large kobold', 'kobold lord', 'kobold shaman', 'leprechaun', 'small mimic',
    'large mimic', 'giant mimic', 'wood nymph', 'water nymph', 'mountain nymph', 'goblin',
    'hobgoblin', 'orc', 'hill orc', 'Mordor orc', 'Uruk-hai', 'orc shaman', 'orc-captain',
    'rock piercer', 'iron piercer', 'glass piercer', 'rothe', 'mumak', 'leocrotta', 'wumpus',
    'titanothere', 'baluchitherium', 'mastodon', 'sewer rat', 'giant rat', 'rabid rat',
    'wererat', 'rock mole', 'woodchuck', 'cave spider', 'centipede', 'giant spider',
    'scorpion', 'lurker above', 'trapper', 'pony', 'white unicorn', 'gray unicorn',
    'black unicorn', 'horse', 'warhorse', 'fog cloud', 'dust vortex', 'ice vortex',
    'energy vortex', 'steam vortex', 'fire vortex', 'baby long worm', 'baby purple worm',
    'long worm', 'purple worm', 'grid bug', 'xan', 'yellow light', 'black light', 'zruty',
    'couatl', 'Aleax', 'Angel', 'ki-rin', 'Archon', 'bat', 'giant bat', 'raven',
    'vampire bat', 'plains centaur', 'forest centaur', 'mountain centaur', 'baby gray dragon',
    'baby silver dragon', 'baby red dragon', 'baby white dragon', 'baby orange dragon',
    'baby black dragon', 'baby blue dragon', 'baby green dragon', 'baby yellow dragon',
    'gray dragon', 'silver dragon', 'red dragon', 'white dragon', 'orange dragon',
    'black dragon', 'blue dragon', 'green dragon', 'yellow dragon', 'stalker',
    'air elemental', 'fire elemental', 'earth elemental', 'water elemental', 'lichen',
    'brown mold', 'yellow mold', 'green mold', 'red mold', 'shrieker', 'violet fungus',
    'gnome', 'gnome lord', 'gnomish wizard', 'gnome king', 'giant', 'stone giant',
    'hill giant', 'fire giant', 'frost giant', 'ettin', 'storm giant', 'titan', 'minotaur',
    'jabberwock', 'Keystone Kop', 'Kop Sergeant', 'Kop Lieutenant', 'Kop Kaptain', 'lich',
    'demilich', 'master lich', 'arch-lich', 'kobold mummy', 'gnome mummy', 'orc mummy',
    'dwarf mummy', 'elf mummy', 'human mummy', 'ettin mummy', 'giant mummy',
    'red naga hatchling', 'black naga hatchling', 'golden naga hatchling',
    'guardian naga hatchling', 'red naga', 'black naga', 'golden naga', 'guardian naga',
    'ogre', 'ogre lord', 'ogre king', 'gray ooze', 'brown pudding', 'green slime',
    'black pudding', 'quantum mechanic', 'rust monster', 'disenchanter', 'garter snake',
    'snake', 'water moccasin', 'python', 'pit viper', 'cobra', 'troll', 'ice troll',
    'rock troll', 'water troll', 'Olog-hai', 'umber hulk', 'vampire', 'vampire lord',
    'Vlad the Impaler', 'barrow wight', 'wraith', 'Nazgul', 'xorn', 'monkey', 'ape',
    'owlbear', 'yeti', 'carnivorous ape', 'sasquatch', 'kobold zombie', 'gnome zombie',
    'orc zombie', 'dwarf zombie', 'elf zombie', 'human zombie', 'ettin zombie', 'ghoul',
    'giant zombie', 'skeleton', 'straw golem', 'paper golem', 'rope golem', 'gold golem',
    'leather golem', 'wood golem', 'flesh golem', 'clay golem', 'stone golem', 'glass golem',
    'iron golem', 'human', 'wererat', 'werejackal', 'werewolf', 'elf', 'Woodland-elf',
    'Green-elf', 'Grey-elf', 'elf-lord', 'Elvenking', 'doppelganger', 'shopkeeper', 'guard',
    'prisoner', 'Oracle', 'aligned priest', 'high priest', 'soldier', 'sergeant', 'nurse',
    'lieutenant', 'captain', 'watchman', 'watch captain', 'Medusa', 'Wizard of Yendor',
    'Croesus', 'ghost', 'shade', 'water demon', 'succubus', 'horned devil', 'incubus',
    'erinys', 'barbed devil', 'marilith', 'vrock', 'hezrou', 'bone devil', 'ice devil',
    'nalfeshnee', 'pit fiend', 'sandestin', 'balrog', 'Juiblex', 'Yeenoghu', 'Orcus',
    'Geryon', 'Dispater', 'Baalzebub', 'Asmodeus', 'Demogorgon', 'Death', 'Pestilence',
    'Famine', 'djinni', 'jellyfish', 'piranha', 'shark', 'giant eel', 'electric eel',
    'kraken', 'newt', 'gecko', 'iguana', 'baby crocodile', 'lizard', 'chameleon', 'crocodile',
    'salamander', 'long worm tail', 'archeologist', 'barbarian', 'caveman', 'cavewoman',
    'healer', 'knight', 'monk', 'priest', 'priestess', 'ranger', 'rogue', 'samurai',
    'tourist', 'valkyrie', 'wizard', 'Lord Carnarvon', 'Pelias', 'Shaman Karnov',
    'Hippocrates', 'King Arthur', 'Grand Master', 'Arch Priest', 'Orion', 'Master of Thieves',
    'Lord Sato', 'Twoflower', 'Norn', 'Neferet the Green', 'Minion of Huhetotl', 'Thoth Amon',
    'Chromatic Dragon', 'Cyclops', 'Ixoth', 'Master Kaen', 'Nalzok', 'Scorpius',
    'Master Assassin', 'Ashikaga Takauji', 'Lord Surtur', 'Dark One', 'student', 'chieftain',
    'neanderthal', 'attendant', 'page', 'abbot', 'acolyte', 'hunter', 'thug', 'ninja',
    'roshi', 'guide', 'warrior', 'apprentice',
)
assert len(MONSTER_NAMES) == NUMMONS


def monster_name(mon_idx) -> str | None:
    """Monster species name for a monster index (``permonst(idx).mname``)."""
    i = int(mon_idx)
    if 0 <= i < NUMMONS:
        return MONSTER_NAMES[i]
    return None
