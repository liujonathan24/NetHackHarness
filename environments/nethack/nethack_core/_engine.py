import ctypes
import os
from pathlib import Path


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
