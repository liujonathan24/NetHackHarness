"""Static HTML replay export over the encoding-eval REPLAY_LOG_KEYS seam."""
from __future__ import annotations
import json
from pathlib import Path
from tools.rollout_view.html import render_run


def _load_turns(run_dir: Path) -> list:
    turns = []
    for f in sorted(Path(run_dir).glob("*.ndjson")):
        turns += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    return turns


def export_replay_html(run_dir, out_name: str = "replay.html") -> Path:
    run_dir = Path(run_dir)
    out = run_dir / out_name
    out.write_text(render_run(_load_turns(run_dir)))
    return out
