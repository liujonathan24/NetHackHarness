"""NDJSON trace reader with a small LRU cache.

The on-disk format is documented in environments/nethack/nethack.py
`_write_trace_entry` (lines 1907-1986). One JSON object per line, 16 fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from tools.launchpad.types import TraceTurn


def read_trace(path: Path) -> list[TraceTurn]:
    """Read one `<run_id>.ndjson` file into a list of TraceTurn.

    Malformed lines are skipped (logged via `warnings.warn`).

    Raises:
        FileNotFoundError: if `path` doesn't exist.
    """
    raise NotImplementedError("core.traces.read_trace")


def stream_trace(path: Path) -> Iterator[TraceTurn]:
    """Stream turns lazily. Tolerates partial trailing line (in-flight writes).

    Raises:
        FileNotFoundError: if `path` doesn't exist.
    """
    raise NotImplementedError("core.traces.stream_trace")


def get_turn(path: Path, turn_index: int) -> TraceTurn:
    """Return the i-th turn (0-indexed by file order, NOT by `.turn`).

    Raises:
        IndexError: if `turn_index` is out of range.
    """
    raise NotImplementedError("core.traces.get_turn")


def trace_summary(path: Path) -> dict[str, float | int]:
    """Cheap aggregate over a trace: {n_turns, total_reward, max_dlvl, final_hp}.

    Returns zeros if the file is empty.
    """
    raise NotImplementedError("core.traces.trace_summary")


def clear_cache() -> None:
    """Drop any in-memory caches held by this module. Idempotent."""
    raise NotImplementedError("core.traces.clear_cache")
