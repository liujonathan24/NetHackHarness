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


# The difficulty-knob catalog (names + order) is fixed for a given libnethack.so,
# so read it from the engine once per process and cache it.
_TUNE_NAMES = None


def tune_names(lib) -> list:
    """Return the ordered list of difficulty-knob names from the engine."""
    global _TUNE_NAMES
    if _TUNE_NAMES is None:
        n = lib.nle_tune_count()
        _TUNE_NAMES = [lib.nle_tune_name(i).decode("ascii") for i in range(n)]
    return _TUNE_NAMES


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


NLE_TUNE_MAX = 64


class NleSettings(ctypes.Structure):
    _fields_ = [
        ("hackdir", ctypes.c_char * 256),
        ("scoreprefix", ctypes.c_char * 256),
        ("options", ctypes.c_char * 512),
        ("wizkit", ctypes.c_char * 256),
        ("spawn_monsters", ctypes.c_int),
        ("ttyrecname", ctypes.c_char * 256),
        # Difficulty-knob overrides applied before the starting level is built.
        # Zero-safe: tune_n == 0 means no overrides (vanilla defaults).
        ("tune_n", ctypes.c_int),
        ("tune_idx", ctypes.c_int * NLE_TUNE_MAX),
        ("tune_val", ctypes.c_double * NLE_TUNE_MAX),
    ]


# ---------------------------------------------------------------------------
# RawEngine
# ---------------------------------------------------------------------------

class RawEngine:
    """Thin ctypes wrapper around the fork's nle_start/nle_step/nle_end API.

    Multiple independent RawEngine instances can run concurrently in the same
    process, including across threads: each instance owns its own nle_ctx_t,
    and the engine anchors a thread-local current_nle_ctx on every call (the
    fork migrated NetHack's globals into nle_ctx_t for exactly this).
    Per-env files are isolated via a per-instance temp hackdir.

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

        # Outstanding snapshot handles created by this instance.  A handle is
        # bound to the ctx that created it; end() frees any the caller leaked.
        self._snapshots = set()

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

        # In-memory snapshot / restore / branch.  The handle is an opaque,
        # self-contained malloc'd copy of (ctx + coroutine stack + arena).
        lib.nle_fr_snapshot.restype = ctypes.c_void_p
        lib.nle_fr_snapshot.argtypes = [ctypes.c_void_p]
        lib.nle_fr_restore.restype = None
        lib.nle_fr_restore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.nle_fr_destroy.restype = None
        lib.nle_fr_destroy.argtypes = [ctypes.c_void_p]

        # Difficulty knob catalog.  nle_get_tune returns nle_tune_t*, which is a
        # flat block of doubles indexed by the name table — so get/set are fully
        # generic (a new knob in the engine appears with no binding change).
        lib.nle_tune_count.restype = ctypes.c_int
        lib.nle_tune_count.argtypes = []
        lib.nle_tune_name.restype = ctypes.c_char_p
        lib.nle_tune_name.argtypes = [ctypes.c_int]
        lib.nle_get_tune.restype = ctypes.POINTER(ctypes.c_double)
        lib.nle_get_tune.argtypes = [ctypes.c_void_p]

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

    def start(self, core: int, disp: int, tune: dict = None) -> "RawEngine":
        """Start a new game.  Returns self so callers can chain property reads.

        Safe to call while a game is already active — tears down the previous
        context first so no C context or temp hackdir is leaked.

        ``tune`` optionally overrides difficulty knobs BEFORE the starting level
        is generated, so generation-time knobs (e.g. room_density) take effect on
        the starting floor.  Live knobs may also be set this way or via set_tune()
        after start().  Unknown knob names raise KeyError.
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

        # Apply start-time difficulty-knob overrides (generation knobs must be
        # set before the starting level is built). tune_n == 0 => vanilla.
        if tune:
            names = tune_names(self._lib)
            index = {name: i for i, name in enumerate(names)}
            if len(tune) > NLE_TUNE_MAX:
                raise ValueError(f"at most {NLE_TUNE_MAX} tune overrides at start")
            for j, (key, value) in enumerate(tune.items()):
                if key not in index:
                    raise KeyError(f"unknown tune knob {key!r}; known: {names}")
                settings.tune_idx[j] = index[key]
                settings.tune_val[j] = float(value)
            settings.tune_n = len(tune)

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
        """Tear down the current game context and clean up the temp hackdir.

        Frees any outstanding snapshot handles first: they become invalid once
        the ctx they would restore into is gone, and freeing them here prevents
        leaks across games (start() calls end() before creating a new game).
        Handles are self-contained copies, so destroy is independent of the ctx
        and ordering relative to nle_end does not matter.
        """
        for snap in list(self._snapshots):
            self._lib.nle_fr_destroy(snap)
        self._snapshots.clear()
        if self._ctx is not None:
            self._lib.nle_end(self._ctx)
            self._ctx = None
        if self._hackdir is not None:
            shutil.rmtree(self._hackdir, ignore_errors=True)
            self._hackdir = None

    # ------------------------------------------------------------------
    # In-memory snapshot / restore / branch
    # ------------------------------------------------------------------

    def snapshot(self):
        """Capture the full live game state and return an opaque handle.

        The handle wraps a self-contained C-side copy of (ctx + coroutine stack
        + arena + rl-port display mirror) taken at the moment of the call — not
        merely the initial state.  It can be restored to return the engine to
        this exact point, and the same handle can be restored repeatedly to
        branch alternate action lines with byte-exact fidelity each time.

        The handle is bound to THIS RawEngine instance: restoring it into a
        different instance's ctx is undefined, so restore() rejects handles it
        did not create.  Outstanding handles are freed by end()/__del__ if the
        caller does not free_snapshot() them first.

        Raises RuntimeError if no game is active or the C call fails.
        """
        if self._ctx is None:
            raise RuntimeError("snapshot() requires an active game; call start() first")
        handle = self._lib.nle_fr_snapshot(self._ctx)
        if not handle:
            raise RuntimeError("nle_fr_snapshot failed (returned NULL)")
        self._snapshots.add(handle)
        return handle

    def restore(self, handle) -> "RawEngine":
        """Restore the engine to the state captured by ``handle``.  Returns self.

        ``handle`` must be one this instance created (same-instance binding); a
        foreign or unknown handle raises ValueError rather than corrupting
        memory.

        Observation-buffer refill behavior (verified empirically): restore
        rewrites the engine's internal state (ctx + coroutine stack + arena) but
        does NOT itself repopulate the binding's numpy observation buffers — the
        buffers reflect the restored state only after the next step() refills
        them.  In practice callers step() after restore (to branch), so the
        buffers are correct by the time they are read.

        Fidelity (verified empirically against fresh-engine ground truth): the
        snapshot is COMPLETE.  Restore + any action line reproduces a from-scratch
        run byte-for-byte on glyphs, chars, colors AND blstats — including on
        repeated restores from the same handle after an abandoned branch explored
        a different part of the map.  (The fork allocates the engine's per-env
        heap buffers in the arena, and the C snapshot captures the rl-port display
        mirror — which lives outside the arena — alongside ctx/stack/arena, so no
        display residue leaks across branches.)

        Raises RuntimeError if no game is active.
        """
        if self._ctx is None:
            raise RuntimeError("restore() requires an active game; call start() first")
        if handle not in self._snapshots:
            raise ValueError(
                "restore() handle was not created by this RawEngine instance; "
                "a snapshot is bound to the ctx that created it"
            )
        self._lib.nle_fr_restore(self._ctx, handle)
        return self

    def free_snapshot(self, handle) -> None:
        """Explicitly free a snapshot handle created by this instance.

        No-op if the handle is unknown (e.g. already freed)."""
        if handle in self._snapshots:
            self._lib.nle_fr_destroy(handle)
            self._snapshots.discard(handle)

    # ------------------------------------------------------------------
    # Difficulty knobs (nle_tune_t)
    # ------------------------------------------------------------------

    def tune_catalog(self) -> list:
        """Return the ordered list of difficulty-knob names the engine exposes."""
        return list(tune_names(self._lib))

    def get_tune(self) -> dict:
        """Return the current difficulty knobs as a {name: value} dict.

        Requires an active game (the knob block lives on the engine ctx).
        """
        if self._ctx is None:
            raise RuntimeError("get_tune() requires an active game; call start() first")
        names = tune_names(self._lib)
        ptr = self._lib.nle_get_tune(self._ctx)
        return {name: float(ptr[i]) for i, name in enumerate(names)}

    def set_tune(self, **knobs) -> "RawEngine":
        """Set one or more difficulty knobs by name.  Returns self.

        Live (Layer 3) knobs take effect on the next step().  Unknown knob names
        raise KeyError.  Values are coerced to float (bools/ints ride as doubles).
        """
        if self._ctx is None:
            raise RuntimeError("set_tune() requires an active game; call start() first")
        names = tune_names(self._lib)
        index = {name: i for i, name in enumerate(names)}
        ptr = self._lib.nle_get_tune(self._ctx)
        for key, value in knobs.items():
            if key not in index:
                raise KeyError(
                    f"unknown tune knob {key!r}; known knobs: {names}"
                )
            ptr[index[key]] = float(value)
        return self

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

    @property
    def done(self) -> bool:
        """True once the current game has ended (death, escape, quit, ...)."""
        return bool(self._obs.done)

    @property
    def how_done(self) -> int:
        """The engine's how_done code for the ended game (valid when done)."""
        return int(self._obs.how_done)

    @property
    def in_normal_game(self) -> bool:
        """True while the engine is in normal play (not a menu/prompt screen)."""
        return bool(self._obs.in_normal_game[0]) if isinstance(
            self._obs.in_normal_game, bytes
        ) else bool(self._obs.in_normal_game)

    # ------------------------------------------------------------------
    # Snapshot builder
    # ------------------------------------------------------------------

    def to_core_observation(self):
        """Return a CoreObservation snapshot of the current engine state.

        Each buffer is copied so that subsequent step() calls do not mutate
        previously captured observations (callers may store trajectory frames).

        Deferred import: env.py will import _engine in a later task, so a
        module-level import here would create a cycle.
        """
        from .env import CoreObservation
        return CoreObservation(
            tty_chars=self._tty_chars.reshape(NLE_TERM_LI, NLE_TERM_CO).copy(),
            tty_colors=self._tty_colors.reshape(NLE_TERM_LI, NLE_TERM_CO).copy(),
            tty_cursor=self._tty_cursor.copy(),
            glyphs=self._glyphs.reshape(ROWNO, COLNO - 1).copy(),
            chars=self._chars.reshape(ROWNO, COLNO - 1).copy(),
            colors=self._colors.reshape(ROWNO, COLNO - 1).copy(),
            message=self._message.copy(),
            inv_strs=self._inv_strs.reshape(NLE_INVENTORY_SIZE, NLE_INVENTORY_STR_LENGTH).copy(),
            inv_letters=self._inv_letters.copy(),
            inv_glyphs=self._inv_glyphs.copy(),
            blstats=self._blstats.copy(),
            misc=self._misc.copy(),
        )
