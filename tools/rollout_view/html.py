"""Shared HTML rendering for a rollout: a single-window, slider-navigated viewer.

`render_turn` renders one turn (two columns: game-state | LLM-input). `render_run`
wraps all turns into a single-window page that shows ONE turn at a time, navigated
by a slider, prev/next buttons, and arrow keys (plus a live "step" affordance when
`live=True`). Used by the static replay export and the live stepper server.
"""
from __future__ import annotations
import html as _html

_CSS = """
* { box-sizing: border-box; }
body { font: 14px/1.4 ui-monospace, monospace; margin: 0; background: #1e1e1e; color: #ddd; }
header { position: sticky; top: 0; background: #111; padding: .6em 1em; display: flex;
         gap: .8em; align-items: center; border-bottom: 1px solid #333; flex-wrap: wrap; }
header a { color: #6cf; text-decoration: none; }
button { background: #2a2a2a; color: #ddd; border: 1px solid #444; border-radius: 4px;
         padding: .3em .7em; cursor: pointer; font: inherit; }
button:hover { background: #383838; }
#slider { flex: 1; min-width: 160px; }
#label { white-space: nowrap; color: #9ad; }
.turn { display: none; padding: 1em; }
.turn.active { display: block; }
.cols { display: flex; gap: 1.5em; align-items: flex-start; }
.cols > div { flex: 1; min-width: 0; }
.cols h4 { margin: 0 0 .4em; color: #9ad; font-weight: 600; }
.cols pre { white-space: pre-wrap; word-break: break-word; background: #161616;
            padding: .8em; border-radius: 6px; margin: 0; overflow-x: auto; }
.cols img { max-width: 100%; border-radius: 6px; background: #000; }
.hint { color: #888; font-size: 12px; }
"""

_JS = """
const turns = () => Array.from(document.querySelectorAll('.turn'));
let i = 0;
function show(n) {
  const ts = turns();
  if (!ts.length) return;
  i = Math.max(0, Math.min(ts.length - 1, n));
  ts.forEach((t, k) => t.classList.toggle('active', k === i));
  const s = document.getElementById('slider');
  s.max = ts.length - 1; s.value = i;
  document.getElementById('label').textContent = `turn ${i + 1} / ${ts.length}`;
}
document.getElementById('prev').onclick = () => show(i - 1);
document.getElementById('next').onclick = () => show(i + 1);
document.getElementById('slider').oninput = (e) => show(+e.target.value);
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') { show(i - 1); }
  else if (e.key === 'ArrowRight') { show(i + 1); }
  else if (window.LIVE && (e.key === ' ' || e.key === 's')) { e.preventDefault(); stepLive(); }
});
async function stepLive() {
  const r = await fetch('/step', { method: 'POST' });
  if (!r.ok) return;
  const tmp = document.createElement('div'); tmp.innerHTML = await r.text();
  const sec = tmp.querySelector('.turn');
  if (sec) { document.getElementById('turns').appendChild(sec); show(turns().length - 1); }
}
const stepBtn = document.getElementById('step');
if (stepBtn) stepBtn.onclick = stepLive;
window.addEventListener('load', () => show(window.LIVE ? turns().length - 1 : 0));
"""


def _llm_blocks(content) -> str:
    if isinstance(content, str):
        return f"<pre>{_html.escape(content)}</pre>"
    out = []
    for e in content:
        if e.get("type") == "image_url":
            path = (e.get("image_url") or {}).get("path") or (e.get("image_url") or {}).get("url", "")
            out.append(f'<img src="{_html.escape(path)}" alt="obs image">')
        elif e.get("type") == "text":
            out.append(f"<pre>{_html.escape(e.get('text', ''))}</pre>")
    return "\n".join(out)


def render_turn(turn: dict) -> str:
    """One turn as a hidden two-column section (game-state | LLM-input). The
    game-state column shows the raw ASCII map verbatim (it legitimately contains
    map glyphs like '<'/'>'); only the LLM-input text is escaped. The viewer JS
    toggles `.active` to show exactly one section at a time."""
    game = "\n".join(turn.get("raw_grid") or [])
    llm = _llm_blocks(turn.get("rendered_user_content", turn.get("rendered_user_message", "")))
    return (f'<section class="turn"><div class="cols" style="display:flex;gap:1.5em">'
            f'<div class="game"><h4>game state · turn {turn.get("turn")}</h4><pre>{game}</pre></div>'
            f'<div class="llm"><h4>LLM input</h4>{llm}</div></div></section>')


def render_run(turns: list, *, live: bool = False, title: str = "rollout") -> str:
    """Single-window, slider-navigated viewer over `turns`."""
    sections = "\n".join(render_turn(t) for t in turns)
    step_btn = '<button id="step">Step &#9654;</button>' if live else ""
    hint = ("<span class=hint>&larr; &rarr; scrub &middot; Space/s = step</span>" if live
            else "<span class=hint>&larr; &rarr; scrub turns</span>")
    return f"""<!doctype html><html><head><meta charset=utf-8><title>{_html.escape(title)}</title>
<style>{_CSS}</style></head><body>
<header>
  <a href="/">&larr; runs</a> <strong>{_html.escape(title)}</strong>
  <button id="prev">&larr;</button>
  <input type="range" id="slider" min="0" max="{max(0, len(turns) - 1)}" value="0">
  <button id="next">&rarr;</button>
  <span id="label"></span>
  {step_btn} {hint}
</header>
<main id="turns">{sections}</main>
<script>window.LIVE = {str(bool(live)).lower()};</script>
<script>{_JS}</script>
</body></html>"""
