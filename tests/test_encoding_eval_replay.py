# tests/test_encoding_eval_replay.py
from __future__ import annotations

import json
from pathlib import Path

from tools.encoding_eval.replay import render_replay, REPLAY_LOG_KEYS


def _write_trace(run_dir: Path):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "r.ndjson").write_text("\n".join(json.dumps(e) for e in [
        {"turn": 0, "raw_grid": ["@.."], "rendered_user_message": "MAP txt",
         "rendered_user_content": "MAP txt"},
        {"turn": 1, "raw_grid": ["..>"], "rendered_user_message": "STATUS",
         "rendered_user_content": [{"type": "image_url", "image_url": {"path": "images/r_1_0.png"}},
                                   {"type": "text", "text": "STATUS"}]},
    ]))


def test_human_form_shows_game_state(tmp_path):
    _write_trace(tmp_path)
    out = render_replay(tmp_path, form="human")
    assert "@.." in out and "..>" in out  # tty frames present


def test_llm_form_shows_text_and_image_ref(tmp_path):
    _write_trace(tmp_path)
    out = render_replay(tmp_path, form="llm")
    assert "MAP txt" in out          # text encoding turn
    assert "images/r_1_0.png" in out  # image preserved (as a reference) for the pixel turn
    assert "STATUS" in out


def test_seam_documents_log_keys():
    # The stable seam Group B's viewer relies on.
    assert {"rendered_user_content", "raw_grid"} <= set(REPLAY_LOG_KEYS)
