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


def test_plot_endpoint_with_custom_metric(client, tmp_path):
    # write the trace into an allow-listed dir
    d = ps._REC_DIR
    d.mkdir(parents=True, exist_ok=True)
    tp = d / "test_obs_tmp.ndjson"
    _write_trace(tp)
    try:
        r = client.post("/obs/plot", json={
            "paths": [str(tp)],
            "metrics": ["dlvl", "xp"],
            "custom": [{"name": "composed", "expr": "xp + 10*dlvl"}],
        })
        assert r.status_code == 200, r.get_data(as_text=True)
        html = r.get_json()["charts_html"]
        assert "<svg" in html
        # the composed custom metric chart appears (title rendered into ctitle)
        assert "composed" in html
    finally:
        tp.unlink(missing_ok=True)


def test_plot_endpoint_path_safety(client):
    r = client.post("/obs/plot", json={
        "paths": ["/etc/passwd"], "metrics": ["dlvl"], "custom": [],
    })
    assert r.status_code == 400
    assert "not allowed" in r.get_json()["error"]


def test_plot_endpoint_rejects_bad_expr(client, tmp_path):
    d = ps._REC_DIR
    d.mkdir(parents=True, exist_ok=True)
    tp = d / "test_obs_tmp2.ndjson"
    _write_trace(tp)
    try:
        r = client.post("/obs/plot", json={
            "paths": [str(tp)], "metrics": [],
            "custom": [{"name": "evil", "expr": "__import__('os').system('echo hi')"}],
        })
        assert r.status_code == 400
    finally:
        tp.unlink(missing_ok=True)


def test_pages_serve_200(client):
    for path in ("/", "/map", "/obs", "/traces"):
        assert client.get(path).status_code == 200
