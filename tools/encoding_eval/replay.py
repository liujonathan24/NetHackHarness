"""Minimal replay renderer + the documented log seam for Group B's viewer.

A recorded run dir contains per-turn NDJSON trace files (keys below) and an
images/ dir. ``render_replay`` produces a plain-text rendering in either the
human-viewable game-state form or the exact LLM-input form. The rich viewer
(Group B / tools/launchpad) reads the same format via this entry point.
"""
from __future__ import annotations

import json
from pathlib import Path

# The stable on-disk seam: keys a viewer can rely on per trace entry.
REPLAY_LOG_KEYS = ("turn", "raw_grid", "rendered_user_message", "rendered_user_content")


def _load_turns(run_dir: Path):
    turns = []
    for f in sorted(Path(run_dir).glob("*.ndjson")):
        for line in f.read_text().splitlines():
            if line.strip():
                turns.append(json.loads(line))
    return turns


def _content_to_lines(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    out = []
    for e in content:
        if e.get("type") == "image_url":
            ref = (e.get("image_url") or {}).get("path") or (e.get("image_url") or {}).get("url", "")
            out.append(f"[image: {ref}]")
        elif e.get("type") == "text":
            out.append(e.get("text", ""))
    return out


def render_replay(run_dir, *, form: str = "human") -> str:
    turns = _load_turns(run_dir)
    blocks = []
    for t in turns:
        head = f"=== turn {t.get('turn')} ==="
        if form == "human":
            body = "\n".join(t.get("raw_grid") or [])
        elif form == "llm":
            body = "\n".join(_content_to_lines(
                t.get("rendered_user_content", t.get("rendered_user_message", ""))))
        else:
            raise ValueError(f"unknown form: {form!r} (expected 'human' or 'llm')")
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)
