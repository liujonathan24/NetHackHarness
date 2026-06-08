import json
from pathlib import Path
from tools.rollout_view.html import render_turn, render_run
from tools.rollout_view.replay_export import export_replay_html


def _turns():
    return [
        {"turn": 0, "raw_grid": ["@.."], "rendered_user_content": "MAP txt"},
        {"turn": 1, "raw_grid": ["..>"],
         "rendered_user_content": [{"type": "image_url", "image_url": {"path": "images/r_1.png"}},
                                   {"type": "text", "text": "STATUS"}]},
    ]


def test_render_turn_two_columns_text_and_image():
    html = render_turn(_turns()[1])
    assert "..>" in html               # game-state column (raw_grid)
    assert "STATUS" in html            # llm text
    assert "images/r_1.png" in html and "<img" in html  # real image embedded


def test_export_replay_html_writes_self_contained_file(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    (run / "r.ndjson").write_text("\n".join(json.dumps(t) for t in _turns()))
    out = export_replay_html(run)
    assert out.exists() and out.suffix == ".html"
    body = out.read_text()
    assert "MAP txt" in body and "<img" in body
