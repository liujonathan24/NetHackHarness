"""Tests for the Observation Creator (/obs) — pure-Python web + rollout_view glue.

Covers the safe composed-metric evaluator (AST whitelist — the security crux),
the xp_lvl->xp adapter, the /obs endpoints, and trace-path allow-list safety.
Does NOT depend on the C engine: it imports tools.play_server (Flask + stats)
and exercises the routes via app.test_client().
"""
from __future__ import annotations

import importlib
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

ps = importlib.import_module("tools.play_server")
from tools.rollout_view import stats  # noqa: E402


@pytest.fixture()
def client():
    ps.app.config["TESTING"] = True
    return ps.app.test_client()


# --- synthetic records for the evaluator ---------------------------------
def _recs():
    return [
        {"turn": 0, "status": {"xp": 1, "dlvl": 1}, "text": "", "raw_grid": None, "raw": {}},
        {"turn": 1, "status": {"xp": 3, "dlvl": 2}, "text": "", "raw_grid": None, "raw": {}},
        {"turn": 2, "status": {"xp": 5, "dlvl": 3}, "text": "", "raw_grid": None, "raw": {}},
    ]


def test_metrics_endpoint(client):
    r = client.get("/obs/metrics")
    assert r.status_code == 200
    metrics = r.get_json()["metrics"]
    assert metrics
    for m in ("dlvl", "hp", "xp"):
        assert m in metrics


def test_safe_eval_composition():
    known = set(stats.metric_names())
    fn = ps._compile_metric_expr("xp + 10*dlvl", known)
    recs = _recs()
    # xp + 10*dlvl : 1+10=11, 3+20=23, 5+30=35
    assert [fn(r) for r in recs] == [11.0, 23.0, 35.0]


def test_safe_eval_missing_metric_is_none():
    known = set(stats.metric_names())
    fn = ps._compile_metric_expr("xp + gold", known)
    # records have xp but no gold -> composed value is None at every turn
    assert all(fn(r) is None for r in _recs())


@pytest.mark.parametrize("expr", [
    '__import__("os")',
    "open('x')",
    "nope_metric + 1",
    "xp ** 2",
    "xp; dlvl",
    "[xp for x in range(3)]",
])
def test_safe_eval_rejects_malicious_or_invalid(expr):
    known = set(stats.metric_names())
    with pytest.raises(ValueError):
        ps._compile_metric_expr(expr, known)


@pytest.mark.parametrize("expr", [
    "os.path",        # attribute access
    "a[0]",           # subscript
    '"x"',            # string constant
    "True",           # bool constant
    "xp and dlvl",    # BoolOp
    "xp > 1",         # Compare
    "1" + "0" * 400,  # huge int literal -> OverflowError, surfaced as ValueError
])
def test_safe_eval_rejects_each_disallowed_ast(expr):
    known = set(stats.metric_names())
    with pytest.raises(ValueError):
        ps._compile_metric_expr(expr, known)


def test_safe_eval_non_finite_is_none():
    # 1e308*1e308 -> inf; must be treated as MISSING, not poison chart coords.
    known = set(stats.metric_names())
    fn = ps._compile_metric_expr("1e308 * 1e308", known)
    assert fn(_recs()[0]) is None


def test_xp_lvl_adapter():
    recs = [{"turn": 0, "status": {"xp_lvl": 3}, "text": "", "raw_grid": None, "raw": {}}]
    out = ps._normalize_records(recs)
    assert out[0]["status"]["xp"] == 3
    assert stats.series(out, "xp") == [(0, 3.0)]


def test_xp_lvl_adapter_does_not_clobber_existing_xp():
    recs = [{"turn": 0, "status": {"xp": 9, "xp_lvl": 3}, "text": "", "raw_grid": None, "raw": {}}]
    ps._normalize_records(recs)
    assert recs[0]["status"]["xp"] == 9


def _write_trace(path: pathlib.Path):
    lines = []
    for t in range(3):
        lines.append(json.dumps({
            "turn": t, "raw_grid": ["@..."], "status": {"hp": 10, "max_hp": 12,
            "dlvl": t + 1, "gold": 0, "xp_lvl": t + 1}, "messages": [],
        }))
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def trace_path(tmp_path, monkeypatch):
    """Hermetic allow-listed trace: write under tmp_path and point the server's
    allow-list at it (no writes into the real outputs/web_play dir)."""
    monkeypatch.setattr(ps, "_REC_DIR", tmp_path)
    monkeypatch.setattr(ps, "_TRACE_DIRS", [tmp_path])
    tp = tmp_path / "trace.ndjson"
    _write_trace(tp)
    return tp


def test_plot_endpoint_with_custom_metric(client, trace_path):
    r = client.post("/obs/plot", json={
        "paths": [str(trace_path)],
        "metrics": ["dlvl", "xp"],
        "custom": [{"name": "composed", "expr": "xp + 10*dlvl"}],
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    html = r.get_json()["charts_html"]
    assert "<svg" in html
    # the composed custom metric chart appears (title rendered into ctitle)
    assert "composed" in html


def _write_web_trace(path: pathlib.Path, *, n: int, varying: bool):
    """Real Map-Viewer Record format (status keys hp/max_hp/ac/dlvl/gold/xp_lvl).
    varying=True -> hp decreases each turn; dlvl/xp_lvl stay constant (the common
    short-recording case where the player barely descended)."""
    lines = []
    for t in range(n):
        lines.append(json.dumps({
            "turn": t, "raw_grid": ["@..."],
            "status": {"hp": (12 - t) if varying else 12, "max_hp": 12, "ac": 7,
                       "dlvl": 1, "gold": 0, "xp_lvl": 1},
            "messages": [],
        }))
    path.write_text("\n".join(lines) + "\n")


def test_single_real_trace_varying_metric_draws_a_line(client, tmp_path, monkeypatch):
    # Regression: plotting ONE real web trace used to look empty. A varying
    # metric (hp) must produce a visible polyline.
    monkeypatch.setattr(ps, "_TRACE_DIRS", [tmp_path])
    tp = tmp_path / "web_one.ndjson"
    _write_web_trace(tp, n=8, varying=True)
    r = client.post("/obs/plot", json={"paths": [str(tp)], "metrics": ["hp"], "custom": []})
    assert r.status_code == 200, r.get_data(as_text=True)
    html = r.get_json()["charts_html"]
    assert "<polyline" in html
    assert "<circle" in html  # point markers (see _svg_linechart)


def test_single_real_trace_constant_metric_is_visible(client, tmp_path, monkeypatch):
    # The default metrics (dlvl, xp) are often CONSTANT in a short recording.
    # A flat series must still render a visible mark, not "no data".
    monkeypatch.setattr(ps, "_TRACE_DIRS", [tmp_path])
    tp = tmp_path / "web_flat.ndjson"
    _write_web_trace(tp, n=8, varying=False)
    r = client.post("/obs/plot", json={"paths": [str(tp)], "metrics": ["dlvl", "xp"], "custom": []})
    assert r.status_code == 200, r.get_data(as_text=True)
    html = r.get_json()["charts_html"]
    # both flat metric charts draw markers (and a flat polyline)
    assert html.count("<polyline") >= 2
    assert "<circle" in html


def test_single_point_series_renders_a_mark(client, tmp_path, monkeypatch):
    # A one-turn recording -> one (x,y) point. A 1-vertex <polyline> is invisible;
    # the marker is what makes the single trace plot show anything at all.
    monkeypatch.setattr(ps, "_TRACE_DIRS", [tmp_path])
    tp = tmp_path / "web_oneturn.ndjson"
    _write_web_trace(tp, n=1, varying=True)
    r = client.post("/obs/plot", json={"paths": [str(tp)], "metrics": ["hp"], "custom": []})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert "<circle" in r.get_json()["charts_html"]


def test_plot_endpoint_path_safety(client):
    r = client.post("/obs/plot", json={
        "paths": ["/etc/passwd"], "metrics": ["dlvl"], "custom": [],
    })
    assert r.status_code == 400
    assert "not allowed" in r.get_json()["error"]


def test_plot_endpoint_rejects_bad_expr(client, trace_path):
    r = client.post("/obs/plot", json={
        "paths": [str(trace_path)], "metrics": [],
        "custom": [{"name": "evil", "expr": "__import__('os').system('echo hi')"}],
    })
    assert r.status_code == 400


def test_custom_metric_colliding_with_builtin_rejected(client, trace_path):
    # A custom metric named like a built-in (dlvl) would permanently shadow it.
    builtin_before = stats.BUILTIN_METRICS["dlvl"]
    r = client.post("/obs/plot", json={
        "paths": [str(trace_path)], "metrics": [],
        "custom": [{"name": "dlvl", "expr": "xp + 1"}],
    })
    assert r.status_code == 400
    assert "built-in" in r.get_json()["error"]
    # built-in untouched and not shadowed afterward
    assert stats.BUILTIN_METRICS["dlvl"] is builtin_before
    assert "dlvl" not in stats._CUSTOM_METRICS


def test_custom_metric_does_not_leak_into_metrics_endpoint(client, trace_path):
    r = client.post("/obs/plot", json={
        "paths": [str(trace_path)], "metrics": [],
        "custom": [{"name": "foo", "expr": "xp + 1"}],
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    # request-scoped: foo must NOT persist into the registry afterward
    assert "foo" not in stats._CUSTOM_METRICS
    listed = client.get("/obs/metrics").get_json()["metrics"]
    assert "foo" not in listed


def test_plot_endpoint_big_int_literal_is_400(client, trace_path):
    huge = "1" + "0" * 400
    r = client.post("/obs/plot", json={
        "paths": [str(trace_path)], "metrics": [],
        "custom": [{"name": "big", "expr": huge}],
    })
    assert r.status_code == 400  # OverflowError surfaced as clean 400, not 500


def test_plot_endpoint_non_dict_body_is_400(client):
    for body in ([1, 2], "hi"):
        r = client.post("/obs/plot", json=body)
        assert r.status_code == 400, body


def test_plot_endpoint_non_dict_custom_entry_is_400(client, trace_path):
    r = client.post("/obs/plot", json={
        "paths": [str(trace_path)], "metrics": ["dlvl"], "custom": ["notadict"],
    })
    assert r.status_code == 400


def test_trace_dirs_sibling_prefix_false_positive_rejected(client, monkeypatch):
    # A sibling dir whose name has an allow-listed dir as a string prefix
    # (outputs vs outputs_evil) must NOT be treated as allowed.
    allowed = _ROOT / "outputs"
    evil = _ROOT / "outputs_evil"
    monkeypatch.setattr(ps, "_TRACE_DIRS", [allowed])
    evil.mkdir(parents=True, exist_ok=True)
    fp = evil / "x.ndjson"
    _write_trace(fp)
    try:
        r = client.post("/obs/plot", json={
            "paths": [str(fp)], "metrics": ["dlvl"], "custom": [],
        })
        assert r.status_code == 400
        assert "not allowed" in r.get_json()["error"]
    finally:
        fp.unlink(missing_ok=True)
        try:
            evil.rmdir()
        except OSError:
            pass


def test_pages_serve_200(client):
    for path in ("/", "/map", "/obs", "/traces"):
        assert client.get(path).status_code == 200
