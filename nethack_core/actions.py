"""Semantic NetHack action vocabulary -- named keystrokes.

Self-contained (no nle); the int value of each member is the keystroke byte
the engine consumes. ``EngineEnv.step(action)`` takes these int values directly
(e.g. ``CompassDirection.N == 107 == ord('k')``, ``Command.SEARCH == 115 ==
ord('s')``, ``MiscAction.MORE == 13``).

These mirror ``nle.nethack``'s enums verbatim (stable public API). Keeping our
own copy lets the harness drive the fork engine without importing nle at all.
"""

from enum import IntEnum


class CompassDirection(IntEnum):
    N = 107
    E = 108
    S = 106
    W = 104
    NE = 117
    SE = 110
    SW = 98
    NW = 121


class CompassDirectionLonger(IntEnum):
    N = 75
    E = 76
    S = 74
    W = 72
    NE = 85
    SE = 78
    SW = 66
    NW = 89


class MiscDirection(IntEnum):
    UP = 60
    DOWN = 62
    WAIT = 46


class MiscAction(IntEnum):
    MORE = 13


class Command(IntEnum):
    EXTCMD = 35
    EXTLIST = 191
    ADJUST = 225
    ANNOTATE = 193
    APPLY = 97
    ATTRIBUTES = 24
    AUTOPICKUP = 64
    CALL = 67
    CAST = 90
    CHAT = 227
    CLOSE = 99
    CONDUCT = 195
    DIP = 228
    DROP = 100
    DROPTYPE = 68
    EAT = 101
    ENGRAVE = 69
    ENHANCE = 229
    ESC = 27
    FIGHT = 70
    FIRE = 102
    FORCE = 230
    GLANCE = 59
    HISTORY = 86
    INVENTORY = 105
    INVENTTYPE = 73
    INVOKE = 233
    JUMP = 234
    KICK = 4
    KNOWN = 92
    KNOWNCLASS = 96
    LOOK = 58
    LOOT = 236
    MONSTER = 237
    MOVE = 109
    MOVEFAR = 77
    OFFER = 239
    OPEN = 111
    OPTIONS = 79
    OVERVIEW = 15
    PAY = 112
    PICKUP = 44
    PRAY = 240
    PUTON = 80
    QUAFF = 113
    QUIT = 241
    QUIVER = 81
    READ = 114
    REDRAW = 18
    REMOVE = 82
    RIDE = 210
    RUB = 242
    RUSH = 103
    RUSH2 = 71
    SAVE = 83
    SEARCH = 115
    SEEALL = 42
    SEEAMULET = 34
    SEEARMOR = 91
    SEEGOLD = 36
    SEERINGS = 61
    SEESPELLS = 43
    SEETOOLS = 40
    SEETRAP = 94
    SEEWEAPON = 41
    SHELL = 33
    SIT = 243
    SWAP = 120
    TAKEOFF = 84
    TAKEOFFALL = 65
    TELEPORT = 20
    THROW = 116
    TIP = 212
    TRAVEL = 95
    TURN = 244
    TWOWEAPON = 88
    UNTRAP = 245
    VERSION = 246
    VERSIONSHORT = 118
    WEAR = 87
    WHATDOES = 38
    WHATIS = 47
    WIELD = 119
    WIPE = 247
    ZAP = 122


class TextCharacters(IntEnum):
    PLUS = 43
    MINUS = 45
    SPACE = 32
    APOS = 39
    QUOTE = 34
    NUM_0 = 48
    NUM_1 = 49
    NUM_2 = 50
    NUM_3 = 51
    NUM_4 = 52
    NUM_5 = 53
    NUM_6 = 54
    NUM_7 = 55
    NUM_8 = 56
    NUM_9 = 57
    DOLLAR = 36


__all__ = [
    "CompassDirection",
    "CompassDirectionLonger",
    "MiscDirection",
    "MiscAction",
    "Command",
    "TextCharacters",
]
