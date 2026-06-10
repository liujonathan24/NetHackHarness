"""Post-hoc stats + static dashboard over saved rollout traces."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

from rollout_view import stats          # noqa: E402
from rollout_view import dashboard       # noqa: E402

_DEMO = _ROOT / "environments/nethack/outputs/evals/demo_B1_7/B1_7.ndjson"

_STATUS = ("=== STATUS ===\nHP: 9/14  AC: 4  Dlvl: 3  Turn: 42  XP: 2  $: 7  "
           "Pos: (12,5)  Hunger: Hungry")


def test_parse_status_extracts_scalar_fields():
    s = stats.parse_status(_STATUS)
    assert s["hp"] == 9 and s["max_hp"] == 14
    assert s["dlvl"] == 3 and s["xp"] == 2 and s["gold"] == 7
    assert s["hunger"] == 1  # "Hungry" -> ordinal 1


def test_load_trace_and_builtin_series():
    recs = stats.load_trace(_DEMO)
    assert len(recs) == 9
    dlvl = stats.series(recs, "dlvl")
    assert dlvl and all(v == 1.0 for _, v in dlvl)        # demo stays on dlvl 1
    assert [t for t, _ in dlvl] == sorted(t for t, _ in dlvl)  # ordered by turn


def test_register_custom_metric_is_applied_post_hoc():
    recs = stats.load_trace(_DEMO)
    stats.register_metric("hp_plus_xp", lambda r: (r["status"].get("hp", 0) + r["status"].get("xp", 0)))
    s = stats.series(recs, "hp_plus_xp")
    assert s and s[0][1] == 15.0  # hp 14 + xp 1
    assert "hp_plus_xp" in stats.metric_names()


def test_run_summary_and_aggregate():
    recs = stats.load_trace(_DEMO)
    summ = stats.run_summary(recs)
    assert summ["max_dlvl"] == 1.0 and summ["n_turns"] == 9 and summ["died"] is False
    agg = stats.aggregate([recs, recs])
    assert agg["n_runs"] == 2 and agg["mean_max_dlvl"] == 1.0 and agg["death_rate"] == 0.0


def test_render_dashboard_is_self_contained_html():
    recs = stats.load_trace(_DEMO)
    html = dashboard.render_dashboard([("run-a", recs), ("run-b", recs)],
                                      metrics=("dlvl", "hp", "xp"))
    assert html.startswith("<!doctype html>")
    assert "<svg" in html and "polyline" in html          # charts present
    assert "mean max dlvl" in html and "death rate" in html  # aggregate KPIs
    assert "http" not in html.split("<style>")[0]          # no external scripts in head before style


def test_load_results_jsonl_shapes_runs(tmp_path):
    import json
    row = {"completion": [
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "=== STATUS ===\nHP: 14/14  Dlvl: 1  XP: 1"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "=== STATUS ===\nHP: 12/14  Dlvl: 2  XP: 1"},
    ]}
    p = tmp_path / "results.jsonl"
    p.write_text(json.dumps(row) + "\n")
    runs = stats.load_results_jsonl(p)
    assert len(runs) == 1
    dlvl = stats.series(runs[0], "dlvl")
    assert [v for _, v in dlvl] == [1.0, 2.0]
