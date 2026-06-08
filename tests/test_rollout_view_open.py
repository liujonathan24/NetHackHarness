import json
from pathlib import Path

from tools.rollout_view.open import open_replay_html


def test_open_replay_html_exports_without_browser(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "r.ndjson").write_text(json.dumps(
        {"turn": 0, "raw_grid": ["@.."], "rendered_user_content": "MAP txt"}))
    out = open_replay_html(run, open_browser=False)
    assert out.exists() and out.name == "replay.html"
    assert "MAP txt" in out.read_text()
