"""NDJSON trace reader with a content-addressed on-disk cache.

The on-disk format is documented in environments/nethack/nethack.py
`_write_trace_entry` (lines 1907-1986). One JSON object per line, 16 fields.

Caching strategy
----------------
`read_trace(path)` first consults an in-memory dict keyed by
`(resolved_path, mtime_ns, size)`. On miss it tries an on-disk cache at
`~/.cache/launchpad/traces/<sha>.bin`, where `<sha>` is a sha256 over
`(resolved_path, mtime_ns, size)`. The on-disk file is written atomically
(tempfile in the same dir + `os.replace`). Mtime change invalidates both
tiers because the cache key changes.

The on-disk format is msgpack if available (bincode-equivalent compact
binary), otherwise pickle (protocol 5). The header byte distinguishes them
so an old cache written under one backend is ignored cleanly.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import pickle
import tempfile
import warnings
from pathlib import Path
from typing import Iterator

from tools.launchpad.types import TraceTurn

logger = logging.getLogger(__name__)

try:  # optional dependency — falls back to pickle when missing.
    import msgpack  # type: ignore[import-not-found]

    _HAVE_MSGPACK = True
except ImportError:
    msgpack = None  # type: ignore[assignment]
    _HAVE_MSGPACK = False


# Header bytes mark which serializer produced the cache file.
_CACHE_VERSION = 1
_HDR_MSGPACK = b"LPMP\x01"
_HDR_PICKLE = b"LPPK\x01"


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

# key: (resolved_path_str, mtime_ns, size) -> list[TraceTurn]
_MEM_CACHE: dict[tuple[str, int, int], list[TraceTurn]] = {}


def _cache_root() -> Path:
    root = Path(os.path.expanduser("~/.cache/launchpad/traces"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_key(path: Path) -> tuple[str, int, int] | None:
    """Return `(resolved_path, mtime_ns, size)` or None if path missing."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


def _cache_file_for(key: tuple[str, int, int]) -> Path:
    h = hashlib.sha256()
    h.update(key[0].encode("utf-8"))
    h.update(b"\x00")
    h.update(str(key[1]).encode("ascii"))
    h.update(b"\x00")
    h.update(str(key[2]).encode("ascii"))
    return _cache_root() / f"{h.hexdigest()}.bin"


def _serialize(turns: list[TraceTurn]) -> bytes:
    payload = [t.model_dump() for t in turns]
    if _HAVE_MSGPACK:
        assert msgpack is not None
        body = msgpack.packb(payload, use_bin_type=True)
        return _HDR_MSGPACK + body
    body = pickle.dumps(payload, protocol=5)
    return _HDR_PICKLE + body


def _deserialize(data: bytes) -> list[TraceTurn] | None:
    if data.startswith(_HDR_MSGPACK):
        if not _HAVE_MSGPACK:
            return None
        assert msgpack is not None
        try:
            payload = msgpack.unpackb(data[len(_HDR_MSGPACK):], raw=False)
        except (ValueError, msgpack.exceptions.ExtraData) as exc:  # type: ignore[attr-defined]
            logger.warning("msgpack cache corrupt: %s", exc)
            return None
    elif data.startswith(_HDR_PICKLE):
        try:
            payload = pickle.loads(data[len(_HDR_PICKLE):])
        except (pickle.UnpicklingError, EOFError, ValueError) as exc:
            logger.warning("pickle cache corrupt: %s", exc)
            return None
    else:
        return None
    try:
        return [TraceTurn(**row) for row in payload]
    except (TypeError, ValueError) as exc:
        logger.warning("cached payload failed model validation: %s", exc)
        return None


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".bin", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except OSError:
        # Clean up the tmp file on any I/O failure, then re-raise.
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------


def _parse_line(line: str, lineno: int, source: str) -> TraceTurn | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        warnings.warn(
            f"skipping malformed JSON in {source}:{lineno}: {exc}",
            RuntimeWarning,
            stacklevel=3,
        )
        return None
    if not isinstance(obj, dict):
        warnings.warn(
            f"skipping non-object JSON in {source}:{lineno}",
            RuntimeWarning,
            stacklevel=3,
        )
        return None
    try:
        return TraceTurn(**obj)
    except (TypeError, ValueError) as exc:
        warnings.warn(
            f"skipping invalid TraceTurn in {source}:{lineno}: {exc}",
            RuntimeWarning,
            stacklevel=3,
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_trace(path: Path, sample_idx: int = 0) -> list[TraceTurn]:
    """Read a trace file into a list of TraceTurn.

    Dispatches by file shape:
      - ``*.ndjson``                       -> NDJSON-per-turn reader (new runs)
      - ``*.json`` with top-level samples  -> legacy synthesizer
                                              (one sample at a time; pick via sample_idx)

    Malformed NDJSON lines are skipped (logged via `warnings.warn`).

    Raises:
        FileNotFoundError: if `path` doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix == ".json":
        from tools.launchpad.core.legacy_trace import (
            is_legacy_samples_file,
            read_legacy_samples,
        )
        if is_legacy_samples_file(path):
            return read_legacy_samples(path, sample_idx=sample_idx)
    key = _cache_key(path)
    if key is None:
        raise FileNotFoundError(path)

    cached = _MEM_CACHE.get(key)
    if cached is not None:
        return list(cached)

    disk_file = _cache_file_for(key)
    if disk_file.exists():
        try:
            data = disk_file.read_bytes()
        except OSError as exc:
            logger.warning("could not read trace cache %s: %s", disk_file, exc)
        else:
            parsed = _deserialize(data)
            if parsed is not None:
                _MEM_CACHE[key] = parsed
                return list(parsed)

    turns: list[TraceTurn] = []
    source = str(path)
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            turn = _parse_line(raw, lineno, source)
            if turn is not None:
                turns.append(turn)

    _MEM_CACHE[key] = turns
    try:
        _atomic_write(disk_file, _serialize(turns))
    except OSError as exc:
        logger.warning("failed to write trace cache %s: %s", disk_file, exc)
    return list(turns)


def stream_trace(path: Path) -> Iterator[TraceTurn]:
    """Stream turns lazily. Tolerates partial trailing line (in-flight writes).

    Raises:
        FileNotFoundError: if `path` doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(path)
    return _stream_impl(path)


def _stream_impl(path: Path) -> Iterator[TraceTurn]:
    source = str(path)
    with path.open("rb") as fh:
        buf = b""
        lineno = 0
        while True:
            chunk = fh.read(io.DEFAULT_BUFFER_SIZE)
            if not chunk:
                break
            buf += chunk
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                lineno += 1
                line_bytes = buf[:nl]
                buf = buf[nl + 1:]
                line = line_bytes.decode("utf-8", errors="replace")
                turn = _parse_line(line, lineno, source)
                if turn is not None:
                    yield turn
        # Trailing bytes WITHOUT newline are treated as in-flight: skip silently
        # (vs. raising/warning) per contract.


def get_turn(path: Path, turn_index: int) -> TraceTurn:
    """Return the i-th turn (0-indexed by file order, NOT by `.turn`).

    Raises:
        FileNotFoundError: if `path` doesn't exist.
        IndexError: if `turn_index` is out of range.
    """
    if turn_index < 0:
        raise IndexError(f"turn_index must be >= 0, got {turn_index}")
    if not path.exists():
        raise FileNotFoundError(path)
    for i, turn in enumerate(_stream_impl(path)):
        if i == turn_index:
            return turn
    raise IndexError(f"turn_index {turn_index} out of range")


def trace_summary(path: Path) -> dict[str, float | int]:
    """Cheap aggregate over a trace: {n_turns, total_reward, max_dlvl, final_hp}.

    Returns zeros if the file is empty.

    Raises:
        FileNotFoundError: if `path` doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(path)
    n_turns = 0
    total_reward = 0.0
    max_dlvl = 0
    final_hp = 0
    for turn in _stream_impl(path):
        n_turns += 1
        total_reward += float(turn.reward)
        cand = turn.max_dlvl_reached if turn.max_dlvl_reached is not None else turn.dlvl
        if cand is not None and cand > max_dlvl:
            max_dlvl = int(cand)
        if turn.hp is not None:
            final_hp = int(turn.hp)
    return {
        "n_turns": n_turns,
        "total_reward": total_reward,
        "max_dlvl": max_dlvl,
        "final_hp": final_hp,
    }


def clear_cache() -> None:
    """Drop in-memory and on-disk caches held by this module. Idempotent."""
    _MEM_CACHE.clear()
    root = Path(os.path.expanduser("~/.cache/launchpad/traces"))
    if not root.exists():
        return
    for child in root.iterdir():
        if child.is_file() and child.suffix == ".bin":
            try:
                child.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("could not remove cache file %s: %s", child, exc)
