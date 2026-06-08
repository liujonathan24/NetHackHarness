"""Tests for the rollout-view UI: single-window slider viewer + index page."""
import json
from pathlib import Path

from tools.rollout_view.html import render_run
from tools.rollout_view.index import discover_runs, render_index


def _turns():
    return [
        {"turn": 0, "raw_grid": ["@.."], "rendered_user_content": "MAP A"},
        {"turn": 1, "raw_grid": ["..>"],
         "rendered_user_content": [{"type": "image_url", "image_url": {"path": "images/x.png"}},
                                   {"type": "text", "text": "B"}]},
    ]


def test_viewer_is_single_window_with_slider_and_keys():
    html = render_run(_turns())
    # one section per turn (JS shows one at a time), a range slider, prev/next, key handler
    assert html.count('class="turn"') == 2
    assert 'type="range"' in html and 'id="slider"' in html
    assert 'id="prev"' in html and 'id="next"' in html
    assert "keydown" in html and "ArrowLeft" in html and "ArrowRight" in html


def test_viewer_live_mode_has_step_control_and_flag():
    html = render_run(_turns(), live=True)
    assert 'id="step"' in html
    assert "window.LIVE = true" in html
    assert "stepLive" in html  # the live step fetch


def test_viewer_replay_mode_has_no_step():
    html = render_run(_turns(), live=False)
    assert 'id="step"' not in html
    assert "window.LIVE = false" in html


def test_index_lists_runs_and_live_launcher(tmp_path):
    root = tmp_path / "evals"
    (root / "run_a").mkdir(parents=True)
    (root / "run_a" / "t.ndjson").write_text(json.dumps(_turns()[0]))
    (root / "run_b").mkdir(parents=True)
    (root / "run_b" / "t.ndjson").write_text(json.dumps(_turns()[0]))
    runs = discover_runs(root)
    assert {p.name for p in runs} == {"run_a", "run_b"}
    idx = render_index(runs, root=root)
    assert "run_a" in idx and "run_b" in idx
    assert 'action="/live"' in idx and 'name="variant"' in idx   # live launcher
    assert "/run?dir=" in idx                                    # per-run viewer links


def test_discover_runs_empty_root(tmp_path):
    assert discover_runs(tmp_path / "nope") == []
