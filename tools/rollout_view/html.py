"""Shared HTML rendering for a rollout: a single-window, slider-navigated viewer.

`render_turn` renders one turn (two columns: game-state | LLM-input). `render_run`
wraps all turns into a single-window page that shows ONE turn at a time, navigated
by a slider, prev/next buttons, and arrow keys (plus a live "step" affordance when
`live=True`). Used by the static replay export and the live stepper server.
"""
from __future__ import annotations
import html as _html

from tools.rollout_view.theme import THEME_CSS

# Viewer-specific layout on top of the shared dungeon/candy THEME_CSS, so the
# trace viewer matches the index page exactly.
_VIEWER_CSS = """
header { position: sticky; top: 0; z-index: 60; background: var(--panel);
  border-bottom: 2px solid var(--line); padding: .55em 1em; display: flex; gap: .7em;
  align-items: center; flex-wrap: wrap; }
header strong { color: var(--gold); }
#slider { flex: 1; min-width: 160px; }
#label { white-space: nowrap; color: var(--cyan); }
.turn { display: none; padding: 1.1em; }
.turn.active { display: block; }
.cols { display: flex; gap: 1.5em; align-items: flex-start; }
.cols > div { flex: 1; min-width: 0; }
.cols .game h4 { margin: 0 0 .4em; color: var(--cyan); font-weight: 600; }
.cols .llm h4 { margin: 0 0 .4em; color: var(--pink); font-weight: 600; }
.cols pre { white-space: pre-wrap; word-break: break-word; background: var(--bg);
  border: 1px solid var(--line); padding: .8em; border-radius: 4px; margin: 0; overflow-x: auto; }
.cols img.obs { width: 100%; border: 1px solid var(--line); border-radius: 4px; background: #000;
  image-rendering: pixelated; cursor: zoom-in; }
.imgwrap .zoomhint { color: var(--dim); font-size: 13px; margin-top: .2em; }
/* click-to-zoom lightbox: crisp pixel scaling, fills the screen */
#lightbox { position: fixed; inset: 0; z-index: 200; display: none; cursor: zoom-out;
  background: rgba(8,8,12,.94); align-items: center; justify-content: center; padding: 2vmin; }
#lightbox.open { display: flex; }
#lightbox img { max-width: 96vw; max-height: 96vh; image-rendering: pixelated;
  border: 2px solid var(--line); }
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

// Click-to-zoom lightbox (delegated, so it also covers live-appended turns).
const lb = document.getElementById('lightbox');
const lbImg = lb && lb.querySelector('img');
document.addEventListener('click', (e) => {
  if (e.target.classList && e.target.classList.contains('obs')) {
    lbImg.src = e.target.src; lb.classList.add('open');
  } else if (e.target === lb || e.target === lbImg) {
    lb.classList.remove('open');
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && lb) lb.classList.remove('open');
});
"""


def _llm_blocks(content, img_src=None) -> str:
    if isinstance(content, str):
        return f"<pre>{_html.escape(content)}</pre>"
    out = []
    for e in content:
        if e.get("type") == "image_url":
            raw = (e.get("image_url") or {}).get("path") or (e.get("image_url") or {}).get("url", "")
            # img_src maps a stored ref to a loadable URL. For recorded runs the
            # ref is a relative path (`images/x.png`) the server must resolve; for
            # live sessions it's an inline `data:` URI used as-is.
            src = img_src(raw) if (img_src and raw and not raw.startswith("data:")) else raw
            out.append(f'<div class="imgwrap"><img class="obs" src="{_html.escape(src)}" '
                       f'alt="obs image"><div class="zoomhint">click image to zoom</div></div>')
        elif e.get("type") == "text":
            out.append(f"<pre>{_html.escape(e.get('text', ''))}</pre>")
    return "\n".join(out)


def render_turn(turn: dict, *, img_src=None) -> str:
    """One turn as a hidden two-column section (game-state | LLM-input). The
    game-state column shows the raw ASCII map verbatim (it legitimately contains
    map glyphs like '<'/'>'); only the LLM-input text is escaped. `img_src(ref)`
    optionally maps a stored image ref to a loadable URL. The viewer JS toggles
    `.active` to show exactly one section at a time."""
    game = "\n".join(turn.get("raw_grid") or [])
    llm = _llm_blocks(turn.get("rendered_user_content", turn.get("rendered_user_message", "")), img_src)
    return (f'<section class="turn"><div class="cols" style="display:flex;gap:1.5em">'
            f'<div class="game"><h4>game state · turn {turn.get("turn")}</h4><pre>{game}</pre></div>'
            f'<div class="llm"><h4>LLM input</h4>{llm}</div></div></section>')


def render_run(turns: list, *, live: bool = False, title: str = "rollout", img_src=None) -> str:
    """Single-window, slider-navigated viewer over `turns`. `img_src(ref)` maps a
    stored image ref to a loadable URL (used when serving recorded runs)."""
    sections = "\n".join(render_turn(t, img_src=img_src) for t in turns)
    step_btn = '<button id="step">Step &#9654;</button>' if live else ""
    hint = ("<span class=hint>&larr; &rarr; scrub &middot; Space/s = step</span>" if live
            else "<span class=hint>&larr; &rarr; scrub turns</span>")
    return f"""<!doctype html><html><head><meta charset=utf-8><title>{_html.escape(title)}</title>
<style>{THEME_CSS}{_VIEWER_CSS}</style></head><body>
<header>
  <a href="/">&larr; runs</a> <strong>{_html.escape(title)}</strong>
  <button id="prev">&larr;</button>
  <input type="range" id="slider" min="0" max="{max(0, len(turns) - 1)}" value="0">
  <button id="next">&rarr;</button>
  <span id="label"></span>
  {step_btn} {hint}
</header>
<main id="turns">{sections}</main>
<div id="lightbox"><img alt="obs image (zoomed)"></div>
<script>window.LIVE = {str(bool(live)).lower()};</script>
<script>{_JS}</script>
</body></html>"""
