"""Tests for ``tools.launchpad.core.runs``.

Read-only filesystem walks; no subprocess use here, so no
``asyncio.create_subprocess_exec`` patching is required (the contract for this
module is pure filesystem). Tests use the ``tmp_path`` fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.launchpad.core import runs as runs_mod
from tools.launchpad.types import RunSummary


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _hosted_sample(reward: float, scout: float, descent: float, start: float) -> dict:
    return {
        "trace_id": "hosted-1",
        "example_id": 0,
        "rollout_number": 1,
        "reward": reward,
        "scout_reward": scout,
        "descent_reward": descent,
        "success_reward": 0.0,
        "ascension_reward": 0.0,
        "latency_ms": 1000,
        "created_at": "2026-05-30T07:01:26.812120Z",
        "info": {"tier": "corridor_explore", "timing": {"start_time": start}},
    }


def _write_eval(
    root: Path,
    sub: str,
    name: str,
    eval_id: str,
    samples: list[dict],
) -> Path:
    d = root / "experiments" / "results" / sub
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps({"evaluation_id": eval_id, "samples": samples, "total": len(samples)}))
    return p


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    runs_mod.clear_cache()
    yield
    runs_mod.clear_cache()


@pytest.fixture
def populated_root(tmp_path: Path) -> Path:
    # Legacy/freeform artifact written first so its mtime is oldest (it has
    # no `samples`, so started_at falls back to file mtime).
    (tmp_path / "experiments" / "results").mkdir(parents=True, exist_ok=True)
    legacy = tmp_path / "experiments" / "results" / "exp01_seeding.json"
    legacy.write_text(json.dumps({"seed": 42, "verdict": "FIX CONFIRMED"}))
    import os
    os.utime(legacy, (1_000.0, 1_000.0))
    # Two wave2 runs (N + E1) plus one malformed file.
    _write_eval(
        tmp_path,
        "wave2",
        "N_seed22_aaa",
        "aaa",
        [_hosted_sample(0.10, 0.10, 0.0, start=1_000.0)],
    )
    _write_eval(
        tmp_path,
        "wave2",
        "E1_seed22_bbb",
        "bbb",
        [
            _hosted_sample(0.30, 0.30, 0.0, start=2_000.0),
            _hosted_sample(0.50, 0.50, 0.2, start=2_010.0),
        ],
    )
    # Malformed JSON: must be skipped (not raise).
    (tmp_path / "experiments" / "results" / "broken.json").write_text("{not json")
    return tmp_path


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_list_runs_newest_first_with_metrics(populated_root: Path) -> None:
    runs = runs_mod.list_runs(populated_root)
    # All three readable artifacts; broken file dropped, not raised.
    labels = [r.label for r in runs]
    assert "E1_seed22_bbb" in labels
    assert "N_seed22_aaa" in labels
    assert "exp01_seeding" in labels
    assert "broken" not in labels

    e1 = next(r for r in runs if r.label == "E1_seed22_bbb")
    n = next(r for r in runs if r.label == "N_seed22_aaa")

    # E1 started after N, so it sorts first.
    assert runs.index(e1) < runs.index(n)
    assert e1.kind == "eval"
    assert e1.n_rollouts == 2
    # Mean of 0.30 and 0.50.
    assert e1.metrics["scout_reward"] == pytest.approx(0.40)
    assert e1.metrics["scout"] == pytest.approx(0.40)  # alias
    assert "wave2" in e1.tags and "E1" in e1.tags
    assert e1.status == "done"
    assert e1.started_at == pytest.approx(2_000.0)


def test_list_runs_filters_by_tag_and_limit(populated_root: Path) -> None:
    only_e1 = runs_mod.list_runs(populated_root, tag="E1", limit=10)
    assert [r.label for r in only_e1] == ["E1_seed22_bbb"]

    limited = runs_mod.list_runs(populated_root, limit=1)
    assert len(limited) == 1


def test_get_run_compare_runs_latest_iter_traces(populated_root: Path, tmp_path: Path) -> None:
    # get_run accepts either evaluation_id or label.
    by_label = runs_mod.get_run(populated_root, "N_seed22_aaa")
    by_eval_id = runs_mod.get_run(populated_root, "aaa")
    assert by_label.run_id == by_eval_id.run_id == "aaa"

    cmp = runs_mod.compare_runs(populated_root, "aaa", "bbb", metric="scout")
    assert cmp["a"] == pytest.approx(0.10)
    assert cmp["b"] == pytest.approx(0.40)
    assert cmp["delta"] == pytest.approx(0.30)

    # ValueError on missing metric, KeyError on bad id.
    with pytest.raises(ValueError):
        runs_mod.compare_runs(populated_root, "aaa", "bbb", metric="not_a_real_metric")
    with pytest.raises(KeyError):
        runs_mod.get_run(populated_root, "nope")

    # latest_run respects filter.
    latest = runs_mod.latest_run(populated_root, kind="eval")
    assert latest.label == "E1_seed22_bbb"

    # iter_trace_files: no trace dir -> falls back to source_path JSON (legacy).
    summary = by_label
    fallback = list(runs_mod.iter_trace_files(summary))
    assert fallback == [Path(summary.source_path)] if summary.source_path else fallback == []

    # iter_trace_files: with a real dir, yields *.ndjson sorted.
    trace_dir = tmp_path / "fake_traces"
    trace_dir.mkdir()
    (trace_dir / "b.ndjson").write_text("{}\n")
    (trace_dir / "a.ndjson").write_text("{}\n")
    (trace_dir / "ignore.txt").write_text("nope")
    s = RunSummary(run_id="x", kind="eval", label="x", trace_dir=str(trace_dir))
    assert [p.name for p in runs_mod.iter_trace_files(s)] == ["a.ndjson", "b.ndjson"]


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_list_runs_missing_results_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        runs_mod.list_runs(tmp_path)


def test_latest_run_no_matches_raises(tmp_path: Path) -> None:
    (tmp_path / "experiments" / "results").mkdir(parents=True)
    with pytest.raises(LookupError):
        runs_mod.latest_run(tmp_path, kind="eval")


def test_cache_invalidates_on_mtime_change(populated_root: Path) -> None:
    # Prime the cache.
    first = runs_mod.list_runs(populated_root)
    n_first = next(r for r in first if r.label == "N_seed22_aaa")
    assert n_first.n_rollouts == 1

    # Rewrite the file with a new sample; new mtime -> cache miss -> refresh.
    p = populated_root / "experiments" / "results" / "wave2" / "N_seed22_aaa.json"
    new_blob = {
        "evaluation_id": "aaa",
        "samples": [
            _hosted_sample(0.10, 0.10, 0.0, start=1_000.0),
            _hosted_sample(0.90, 0.90, 0.0, start=1_500.0),
        ],
        "total": 2,
    }
    # Bump mtime explicitly so the test doesn't race the filesystem clock.
    import os
    p.write_text(json.dumps(new_blob))
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))

    refreshed = runs_mod.get_run(populated_root, "aaa")
    assert refreshed.n_rollouts == 2
    assert refreshed.metrics["scout_reward"] == pytest.approx(0.50)


def test_invalid_kind_rejected(populated_root: Path) -> None:
    with pytest.raises(ValueError):
        runs_mod.list_runs(populated_root, kind="bogus")
