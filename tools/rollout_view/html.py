"""Shared HTML rendering for a rollout turn / run (used by replay export + live)."""
from __future__ import annotations
import html as _html


def _llm_blocks(content):
    if isinstance(content, str):
        return f"<pre>{_html.escape(content)}</pre>"
    out = []
    for e in content:
        if e.get("type") == "image_url":
            path = (e.get("image_url") or {}).get("path") or (e.get("image_url") or {}).get("url", "")
            out.append(f'<img src="{_html.escape(path)}" alt="obs image" style="max-width:100%">')
        elif e.get("type") == "text":
            out.append(f"<pre>{_html.escape(e.get('text',''))}</pre>")
    return "\n".join(out)


def render_turn(turn: dict) -> str:
    # Game-state column shows the raw ASCII map verbatim (it legitimately
    # contains map glyphs like '<'/'>'); only the LLM-input text is escaped.
    game = "\n".join(turn.get("raw_grid") or [])
    llm = _llm_blocks(turn.get("rendered_user_content", turn.get("rendered_user_message", "")))
    return (f'<section class="turn"><h3>turn {turn.get("turn")}</h3>'
            f'<div class="cols" style="display:flex;gap:1em">'
            f'<div class="game"><h4>game state</h4><pre>{game}</pre></div>'
            f'<div class="llm"><h4>LLM input</h4>{llm}</div></div></section>')


def render_run(turns: list) -> str:
    body = "\n".join(render_turn(t) for t in turns)
    return f"<!doctype html><meta charset=utf-8><title>rollout</title><body>{body}</body>"
