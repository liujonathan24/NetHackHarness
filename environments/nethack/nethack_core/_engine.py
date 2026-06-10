import ctypes
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np


class EngineNotBuilt(RuntimeError):
    """Raised when libnethack.so cannot be located."""


def library_path() -> Path:
    env = os.environ.get("NLE_LIB_PATH")
    if env:
        # NLE_LIB_PATH is authoritative: if set but missing, raise immediately.
        p = Path(env)
        if p.exists():
            return p
        raise EngineNotBuilt(
            f"NLE_LIB_PATH={env!r} does not exist. Build it with "
            "environments/nethack/nethack_core/build_engine.sh "
            "(or set NLE_LIB_PATH to a valid path). Toolchain: cmake/bison/flex/libbz2."
        )
    # _engine.py is at environments/nethack/nethack_core/_engine.py;
    # parents[3] is the repo root.
    root = Path(__file__).resolve().parents[3]
    default = root / "third_party" / "NetHack" / "src" / "build" / "libnethack.so"
    if default.exists():
        return default
    raise EngineNotBuilt(
        "libnethack.so not found. Build it with "
        "environments/nethack/nethack_core/build_engine.sh "
        "(or set NLE_LIB_PATH). Toolchain: cmake/bison/flex/libbz2."
    )


_LIB = None


def load_library() -> ctypes.CDLL:
    global _LIB
    if _LIB is None:
        _LIB = ctypes.CDLL(str(library_path()))
    return _LIB


# ---------------------------------------------------------------------------
# Constants (verified against the fork's include/nleobs.h + sys/unix/nle.c)
# ---------------------------------------------------------------------------

NLE_BLSTATS_SIZE = 27
NLE_MESSAGE_SIZE = 256
NLE_PROGRAM_STATE_SIZE = 6
NLE_INTERNAL_SIZE = 9
NLE_MISC_SIZE = 3
NLE_INVENTORY_SIZE = 55
NLE_INVENTORY_STR_LENGTH = 80
NLE_SCREEN_DESCRIPTION_LENGTH = 80
NLE_TERM_CO = 80
NLE_TERM_LI = 24
ROWNO = 21
COLNO = 80
MAP = ROWNO * (COLNO - 1)   # 1659
TTY = NLE_TERM_LI * NLE_TERM_CO  # 1920

# Options string that fully specifies the character so the engine never blocks
# on interactive prompts during game creation.
_NETHACKOPTIONS = (
    "autopickup", "color", "disclose:+i +a +v +g +c +o", "mention_walls",
    "nobones", "nocmdassist", "nolegacy", "nosparkle",
    "pickup_burden:unencumbered", "pickup_types:$?!/", "runmode:teleport",
    "showexp", "showscore", "time",
)
_OPTIONS_STR = ",".join(_NETHACKOPTIONS) + ",name:Agent-mon-hum-neu-mal"


# ---------------------------------------------------------------------------
# ctypes struct mirrors — field order MUST match the C definitions exactly.
# ---------------------------------------------------------------------------

class NleObs(ctypes.Structure):
    _fields_ = [
        ("action", ctypes.c_int),
        ("done", ctypes.c_int),
        ("in_normal_game", ctypes.c_char),
        ("how_done", ctypes.c_int),
        ("glyphs", ctypes.POINTER(ctypes.c_short)),
        ("chars", ctypes.POINTER(ctypes.c_uint8)),
        ("colors", ctypes.POINTER(ctypes.c_uint8)),
        ("specials", ctypes.POINTER(ctypes.c_uint8)),
        ("blstats", ctypes.POINTER(ctypes.c_long)),
        ("message", ctypes.POINTER(ctypes.c_uint8)),
        ("program_state", ctypes.POINTER(ctypes.c_int)),
        ("internal", ctypes.POINTER(ctypes.c_int)),
        ("inv_glyphs", ctypes.POINTER(ctypes.c_short)),
        ("inv_strs", ctypes.POINTER(ctypes.c_uint8)),
        ("inv_letters", ctypes.POINTER(ctypes.c_uint8)),
        ("inv_oclasses", ctypes.POINTER(ctypes.c_uint8)),
        ("screen_descriptions", ctypes.POINTER(ctypes.c_uint8)),
        ("tty_chars", ctypes.POINTER(ctypes.c_uint8)),
        ("tty_colors", ctypes.POINTER(ctypes.c_int8)),
        ("tty_cursor", ctypes.POINTER(ctypes.c_uint8)),
        ("misc", ctypes.POINTER(ctypes.c_int)),
    ]


class NleSeedsInit(ctypes.Structure):
    """NLE_ALLOW_SEEDING is defined in this fork's build."""
    _fields_ = [("seeds", ctypes.c_ulong * 2), ("reseed", ctypes.c_char)]


class NleSettings(ctypes.Structure):
    _fields_ = [
        ("hackdir", ctypes.c_char * 256),
        ("scoreprefix", ctypes.c_char * 256),
        ("options", ctypes.c_char * 512),
        ("wizkit", ctypes.c_char * 256),
        ("spawn_monsters", ctypes.c_int),
        ("ttyrecname", ctypes.c_char * 256),
    ]


# ---------------------------------------------------------------------------
# RawEngine
# ---------------------------------------------------------------------------

class RawEngine:
    """Thin ctypes wrapper around the fork's nle_start/nle_step/nle_end API.

    One engine per process (the C side maintains global NetHack state).
    Call start() before step(), and end() when done.  start() may be called
    again after end() for a fresh game.
    """

    def __init__(self) -> None:
        self._lib = load_library()
        self._setup_argtypes()

        # Allocate all observation buffers as contiguous numpy arrays.
        # They MUST remain referenced on self to prevent GC while the C side
        # holds raw pointers into them.
        self._glyphs = np.zeros(MAP, dtype=np.int16)
        self._chars = np.zeros(MAP, dtype=np.uint8)
        self._colors = np.zeros(MAP, dtype=np.uint8)
        self._specials = np.zeros(MAP, dtype=np.uint8)
        self._blstats = np.zeros(NLE_BLSTATS_SIZE, dtype=np.int64)
        self._message = np.zeros(NLE_MESSAGE_SIZE, dtype=np.uint8)
        self._program_state = np.zeros(NLE_PROGRAM_STATE_SIZE, dtype=np.int32)
        self._internal = np.zeros(NLE_INTERNAL_SIZE, dtype=np.int32)
        self._inv_glyphs = np.zeros(NLE_INVENTORY_SIZE, dtype=np.int16)
        self._inv_strs = np.zeros(
            NLE_INVENTORY_SIZE * NLE_INVENTORY_STR_LENGTH, dtype=np.uint8
        )
        self._inv_letters = np.zeros(NLE_INVENTORY_SIZE, dtype=np.uint8)
        self._inv_oclasses = np.zeros(NLE_INVENTORY_SIZE, dtype=np.uint8)
        self._screen_descriptions = np.zeros(
            ROWNO * (COLNO - 1) * NLE_SCREEN_DESCRIPTION_LENGTH, dtype=np.uint8
        )
        self._tty_chars = np.zeros(TTY, dtype=np.uint8)
        self._tty_colors = np.zeros(TTY, dtype=np.int8)
        self._tty_cursor = np.zeros(2, dtype=np.uint8)
        self._misc = np.zeros(NLE_MISC_SIZE, dtype=np.int32)

        # Build the NleObs struct and populate all pointer fields.
        self._obs = NleObs()
        self._obs.glyphs = self._glyphs.ctypes.data_as(
            ctypes.POINTER(ctypes.c_short)
        )
        self._obs.chars = self._chars.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.colors = self._colors.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.specials = self._specials.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.blstats = self._blstats.ctypes.data_as(
            ctypes.POINTER(ctypes.c_long)
        )
        self._obs.message = self._message.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.program_state = self._program_state.ctypes.data_as(
            ctypes.POINTER(ctypes.c_int)
        )
        self._obs.internal = self._internal.ctypes.data_as(
            ctypes.POINTER(ctypes.c_int)
        )
        self._obs.inv_glyphs = self._inv_glyphs.ctypes.data_as(
            ctypes.POINTER(ctypes.c_short)
        )
        self._obs.inv_strs = self._inv_strs.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.inv_letters = self._inv_letters.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.inv_oclasses = self._inv_oclasses.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.screen_descriptions = self._screen_descriptions.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.tty_chars = self._tty_chars.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.tty_colors = self._tty_colors.ctypes.data_as(
            ctypes.POINTER(ctypes.c_int8)
        )
        self._obs.tty_cursor = self._tty_cursor.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint8)
        )
        self._obs.misc = self._misc.ctypes.data_as(ctypes.POINTER(ctypes.c_int))

        self._ctx = None
        self._hackdir = None  # tempfile.mkdtemp() path string

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setup_argtypes(self) -> None:
        lib = self._lib

        lib.nle_start.restype = ctypes.c_void_p
        lib.nle_start.argtypes = [
            ctypes.POINTER(NleObs),
            ctypes.c_void_p,                # FILE* ttyrec (NULL = no recording)
            ctypes.POINTER(NleSeedsInit),
            ctypes.POINTER(NleSettings),
        ]

        lib.nle_step.restype = ctypes.c_void_p
        lib.nle_step.argtypes = [
            ctypes.c_void_p,                # nle_ctx_t*
            ctypes.POINTER(NleObs),
        ]

        lib.nle_end.restype = None
        lib.nle_end.argtypes = [ctypes.c_void_p]

    def _build_dat_path(self) -> Path:
        """Return the path to the pre-built dat directory (contains nhdat etc.)."""
        root = Path(__file__).resolve().parents[3]
        return root / "third_party" / "NetHack" / "src" / "build" / "dat"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def __del__(self) -> None:
        try:
            self.end()
        except Exception:
            pass

    def start(self, core: int, disp: int) -> "RawEngine":
        """Start a new game.  Returns self so callers can chain property reads.

        Safe to call while a game is already active — tears down the previous
        context first so no C context or temp hackdir is leaked.
        """
        # Tear down any prior game before creating a new one.
        self.end()

        # Make a writable copy of the built dat directory so the engine can
        # write lock/record/level files without polluting the source tree.
        src_dat = self._build_dat_path()
        self._hackdir = tempfile.mkdtemp(prefix="nethack_hackdir_")
        shutil.copytree(str(src_dat), self._hackdir, dirs_exist_ok=True)

        # Build settings.
        settings = NleSettings()
        settings.hackdir = self._hackdir.encode()
        settings.scoreprefix = b""
        options_bytes = _OPTIONS_STR.encode()
        settings.options = options_bytes
        settings.wizkit = b""
        settings.spawn_monsters = 1
        settings.ttyrecname = b""

        # Build seeds.
        seeds = NleSeedsInit()
        seeds.seeds[0] = core
        seeds.seeds[1] = disp
        seeds.reseed = b"\x00"  # False — deterministic

        self._obs.action = 0
        self._ctx = self._lib.nle_start(
            ctypes.byref(self._obs),
            None,
            ctypes.byref(seeds),
            ctypes.byref(settings),
        )
        return self

    def step(self, action: int) -> "RawEngine":
        """Send an action to the engine.  Returns self."""
        self._obs.action = int(action)
        self._lib.nle_step(self._ctx, ctypes.byref(self._obs))
        return self

    def end(self) -> None:
        """Tear down the current game context and clean up the temp hackdir."""
        if self._ctx is not None:
            self._lib.nle_end(self._ctx)
            self._ctx = None
        if self._hackdir is not None:
            shutil.rmtree(self._hackdir, ignore_errors=True)
            self._hackdir = None

    # ------------------------------------------------------------------
    # Observation properties (reshaped views — reflect in-place C updates)
    # ------------------------------------------------------------------

    @property
    def glyphs(self) -> np.ndarray:
        return self._glyphs.reshape(ROWNO, COLNO - 1)

    @property
    def chars(self) -> np.ndarray:
        return self._chars.reshape(ROWNO, COLNO - 1)

    @property
    def colors(self) -> np.ndarray:
        return self._colors.reshape(ROWNO, COLNO - 1)

    @property
    def tty_chars(self) -> np.ndarray:
        return self._tty_chars.reshape(NLE_TERM_LI, NLE_TERM_CO)

    @property
    def tty_colors(self) -> np.ndarray:
        return self._tty_colors.reshape(NLE_TERM_LI, NLE_TERM_CO)

    @property
    def blstats(self) -> np.ndarray:
        return self._blstats  # already (27,)

    @property
    def message(self) -> np.ndarray:
        return self._message  # already (256,)
