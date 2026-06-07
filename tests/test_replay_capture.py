# tests/test_replay_capture.py
from __future__ import annotations

import json
from pathlib import Path

from nethack_harness.helpers import _capture_user_content


def test_text_content_passthrough(tmp_path):
    out = _capture_user_content("OBS TEXT", tmp_path, run_id="r", turn=3)
    assert out == "OBS TEXT"  # string content stored as-is


def test_image_content_written_as_png_and_referenced(tmp_path):
    import base64
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE").decode()
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
        {"type": "text", "text": "STATUS"},
    ]
    out = _capture_user_content(content, tmp_path, run_id="r", turn=3)
    # image entry replaced with a relative path; no base64 inline
    img_entry = next(e for e in out if e["type"] == "image_url")
    ref = img_entry["image_url"]["path"]
    assert "base64" not in json.dumps(out)
    assert (tmp_path / ref).exists()
    assert next(e for e in out if e["type"] == "text")["text"] == "STATUS"
