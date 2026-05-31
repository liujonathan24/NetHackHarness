"""Run discovery and summarization.

Walks ``experiments/results/**`` for eval JSON artifacts and ``runs/**`` for
train artifacts, parses metadata + light metrics, and returns
:class:`RunSummary` objects.

All functions are read-only. The on-disk JSON shape produced by ``prime eval``
(see ``experiments/results/wave2/*.json``) looks like::

    {
      "evaluation_id": "<id>",
      "samples": [ { "reward": 0.07, "scout_reward": 0.07,
                     "descent_reward": 0.0, "info": {"tier": ...,
                     "timing": {"start_time": <unix>}}, ... }, ... ],
      "total": <int>, ...
    }

Older one-off experiment JSONs (``experiments/results/exp*.json``) are
free-form; we still index them so they show up in ``launchpad runs ls``, but
with minimal metrics.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.launchpad.types import RunSummary

__all__ = [
    "list_runs",
    "get_run",
    "compare_runs",
    "latest_run",
    "iter_trace_files",
    "clear_cache",
]

log = logging.getLogger(__name__)

# Metric keys we promote from per-sample fields to run-level means.
_SAMPLE_METRIC_KEYS = (
    "reward",
    "scout_reward",
    "descent_reward",
    "success_reward",
    "ascension_reward",
    "score",
)

# Metric aliases accepted by compare_runs / get_run consumers.
_METRIC_ALIASES = {
    "scout": "scout_reward",
    "descent": "descent_reward",
    "success": "success_reward",
    "ascension": "ascension_reward",
}


# ---------------------------------------------------------------------------
# mtime-keyed cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CacheKey:
    path: str
    mtime_ns: int
    size: int


_cache: dict[_CacheKey, RunSummary] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    """Idempotently drop the in-memory summary cache."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.warning("skipping unparseable JSON %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        # Lists / scalars are not run artifacts.
        return None
    return data


def _parse_iso(ts: str) -> float | None:
    """Best-effort ISO-8601 -> unix seconds; returns None on failure."""
    try:
        # Python 3.11+ handles trailing 'Z'; pre-3.11 we strip it.
        s = ts.rstrip("Z")
        if "." in s and "+" not in s and "-" not in s.split("T", 1)[-1]:
            return datetime.fromisoformat(s).timestamp()
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


def _label_and_tags(path: Path, results_root: Path) -> tuple[str, list[str]]:
    """Derive (label, tags) from path layout.

    Convention:
      - parent dir name (if not 'results') becomes both a tag and the label
        prefix.
      - filename stem becomes the label; first ``_``-separated token is a tag
        (e.g. ``E1_seed31_xxx`` -> tags=['wave2', 'E1']).
    """
    rel = path.relative_to(results_root) if path.is_absolute() and results_root in path.parents else path
    tags: list[str] = []
    parent = rel.parent
    if parent != Path("."):
        # All non-trivial parent components are tags.
        tags.extend(p for p in parent.parts if p)
    stem = path.stem
    head = stem.split("_", 1)[0]
    if head and head not in tags:
        tags.append(head)
    return stem, tags


def _metrics_from_samples(samples: list[Any]) -> tuple[dict[str, float], int]:
    """Mean each known metric across samples; also returns rollout count."""
    metrics: dict[str, float] = {}
    if not samples:
        return metrics, 0
    for key in _SAMPLE_METRIC_KEYS:
        vals: list[float] = []
        for s in samples:
            if not isinstance(s, dict):
                continue
            v = s.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(float(v))
        if vals:
            metrics[key] = sum(vals) / len(vals)
            # Friendly alias.
            for short, long in _METRIC_ALIASES.items():
                if long == key:
                    metrics[short] = metrics[key]
    return metrics, len(samples)


def _times_from_samples(samples: list[Any]) -> tuple[float | None, float | None]:
    """Earliest start_time / latest end_time across samples."""
    starts: list[float] = []
    ends: list[float] = []
    for s in samples:
        if not isinstance(s, dict):
            continue
        info = s.get("info") if isinstance(s.get("info"), dict) else None
        timing = info.get("timing") if info and isinstance(info.get("timing"), dict) else None
        if timing:
            st = timing.get("start_time")
            if isinstance(st, (int, float)):
                starts.append(float(st))
            gen = timing.get("generation")
            if isinstance(gen, dict) and isinstance(gen.get("end"), (int, float)):
                ends.append(float(gen["end"]))
        created = s.get("created_at")
        if isinstance(created, str):
            ts = _parse_iso(created)
            if ts is not None:
                starts.append(ts)
                # latency_ms (ms) gives finish; gracefully ignore non-ints.
                lat = s.get("latency_ms")
                if isinstance(lat, (int, float)):
                    ends.append(ts + float(lat) / 1000.0)
    return (min(starts) if starts else None, max(ends) if ends else None)


def _summary_for_file(path: Path, results_root: Path, kind: str) -> RunSummary | None:
    """Parse one JSON artifact into a RunSummary (or None if unreadable)."""
    try:
        st = path.stat()
    except OSError as exc:
        log.warning("stat() failed for %s: %s", path, exc)
        return None
    key = _CacheKey(str(path), st.st_mtime_ns, st.st_size)
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached

    data = _safe_load_json(path)
    if data is None:
        return None

    label, tags = _label_and_tags(path, results_root)
    run_id = data.get("evaluation_id") if isinstance(data.get("evaluation_id"), str) else label

    samples = data.get("samples")
    if not isinstance(samples, list):
        samples = []
    metrics, n_roll = _metrics_from_samples(samples)
    started_at, finished_at = _times_from_samples(samples)
    if started_at is None:
        # Fall back to file mtime so newest-first ordering still works.
        started_at = float(st.st_mtime)

    # Heuristic status: hosted artifacts only exist once the run finished.
    status: str = "done" if samples else "unknown"

    # Trace dir: look for sibling 'traces/<run_id>' or '<stem>_traces' dir.
    trace_dir: str | None = None
    for candidate in (path.with_suffix("") / "traces", path.parent / "traces" / run_id):
        if candidate.is_dir():
            trace_dir = str(candidate)
            break

    # Model: hosted JSON omits it explicitly; try to pull from samples[0].info.
    model: str | None = None
    for s in samples:
        if isinstance(s, dict):
            info = s.get("info")
            if isinstance(info, dict):
                m = info.get("model")
                if isinstance(m, str):
                    model = m
                    break

    summary = RunSummary(
        run_id=run_id,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        model=model,
        harness=None,
        tags=tags,
        status=status,  # type: ignore[arg-type]
        started_at=started_at,
        finished_at=finished_at,
        metrics=metrics,
        trace_dir=trace_dir,
        n_rollouts=n_roll,
        source_path=str(path),
    )
    with _cache_lock:
        _cache[key] = summary
    return summary


# ---------------------------------------------------------------------------
# Disk walks
# ---------------------------------------------------------------------------


def _walk_eval(root: Path) -> Iterator[RunSummary]:
    results_root = root / "experiments" / "results"
    if not results_root.is_dir():
        raise FileNotFoundError(f"missing {results_root}")
    for path in sorted(results_root.rglob("*.json")):
        if not path.is_file():
            continue
        summary = _summary_for_file(path, results_root, kind="eval")
        if summary is not None:
            yield summary


def _walk_train(root: Path) -> Iterator[RunSummary]:
    runs_root = root / "runs"
    if not runs_root.is_dir():
        return
    for path in sorted(runs_root.rglob("*.json")):
        if not path.is_file():
            continue
        summary = _summary_for_file(path, runs_root, kind="train")
        if summary is not None:
            yield summary


def _walk(root: Path, kind: str | None) -> Iterator[RunSummary]:
    if kind in (None, "eval"):
        yield from _walk_eval(root)
    if kind in (None, "train"):
        yield from _walk_train(root)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_runs(
    root: Path,
    kind: str | None = None,
    tag: str | None = None,
    limit: int = 20,
) -> list[RunSummary]:
    """Return up to ``limit`` most-recent runs under ``root``.

    Newest first by ``started_at`` (None sorts last). ``tag`` does substring
    match against ``RunSummary.tags`` entries.
    """
    if kind is not None and kind not in ("eval", "train"):
        raise ValueError(f"kind must be 'eval', 'train', or None, got {kind!r}")
    if limit < 0:
        raise ValueError("limit must be >= 0")

    runs = list(_walk(root, kind))
    if tag is not None:
        runs = [r for r in runs if any(tag in t for t in r.tags)]
    runs.sort(
        key=lambda r: (r.started_at is None, -(r.started_at or 0.0)),
    )
    return runs[:limit]


def get_run(root: Path, run_id: str) -> RunSummary:
    """Look up one run by id (matches ``run_id`` or filename stem)."""
    for summary in _walk(root, kind=None):
        if summary.run_id == run_id or summary.label == run_id:
            return summary
    raise KeyError(run_id)


def compare_runs(
    root: Path,
    run_a: str,
    run_b: str,
    metric: str = "scout",
) -> dict[str, float]:
    """Return ``{"a": float, "b": float, "delta": b - a}`` for ``metric``."""
    a = get_run(root, run_a)
    b = get_run(root, run_b)
    key = _METRIC_ALIASES.get(metric, metric)
    if key not in a.metrics or key not in b.metrics:
        raise ValueError(
            f"metric {metric!r} not present on both runs "
            f"(a: {sorted(a.metrics)}, b: {sorted(b.metrics)})"
        )
    av = float(a.metrics[key])
    bv = float(b.metrics[key])
    return {"a": av, "b": bv, "delta": bv - av}


def latest_run(root: Path, kind: str | None = None) -> RunSummary:
    """Most-recently-started run matching ``kind`` (or any kind)."""
    runs = list_runs(root, kind=kind, limit=1)
    if not runs:
        raise LookupError(f"no runs found under {root} (kind={kind!r})")
    return runs[0]


def iter_trace_files(summary: RunSummary) -> Iterable[Path]:
    """Yield trace files for ``summary`` in stable (sorted) order.

    Prefers per-rollout ``*.ndjson`` (new runs) when ``summary.trace_dir`` is set
    and populated; falls back to the legacy samples JSON path on disk
    (one file per run; each sample becomes a synthetic rollout).
    """
    if summary.trace_dir:
        p = Path(summary.trace_dir)
        if p.is_dir():
            ndjsons = [e for e in sorted(p.glob("*.ndjson")) if e.is_file()]
            if ndjsons:
                yield from ndjsons
                return
    legacy = Path(summary.source_path) if summary.source_path else None
    if legacy and legacy.is_file() and legacy.suffix == ".json":
        yield legacy
