"""The rollout-view entry page: browse recorded runs + launch a live session."""
from __future__ import annotations
import html as _html
from pathlib import Path
from urllib.parse import quote

# Keep in sync with the registered observation encodings.
DEFAULT_VARIANTS = ("B1", "IMG", "IMG_TTY", "JSON", "TOON")


def discover_runs(root) -> list:
    """Return recorded-run directories under `root` (a dir holding >=1 *.ndjson),
    most-recent first. A run dir is any directory that directly contains an
    `.ndjson` trace file."""
    root = Path(root)
    if not root.exists():
        return []
    runs = {f.parent for f in root.rglob("*.ndjson")}
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


# Retro green-phosphor CRT terminal aesthetic (fits NetHack's roots). Self-contained
# inline CSS; pixel fonts via Google Fonts with a graceful monospace fallback offline.
_INDEX_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap');
:root { --grn:#39ff14; --grn-dim:#1f7a12; --amber:#ffb000; --bg:#040f08; --panel:#07200f; }
* { box-sizing: border-box; }
html, body { margin: 0; }
body { min-height: 100vh; background:
    radial-gradient(ellipse at 50% 0%, #0b2a16 0%, #040f08 70%);
  color: var(--grn); font-family: 'VT323', ui-monospace, monospace; font-size: 20px;
  letter-spacing: .5px; padding: 2.2em 1.2em; }
/* CRT scanlines + subtle vignette */
body::after { content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 50;
  background: repeating-linear-gradient(0deg, rgba(0,0,0,.28) 0 1px, transparent 1px 3px);
  mix-blend-mode: multiply; }
.wrap { max-width: 720px; margin: 0 auto; }
h1 { font-family: 'Press Start 2P', monospace; font-size: 20px; line-height: 1.5;
  color: var(--grn); text-shadow: 0 0 6px var(--grn), 0 0 16px rgba(57,255,20,.7);
  margin: 0 0 1.4em; }
.cursor { animation: blink 1.1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.panel { border: 3px solid var(--grn); background: var(--panel); padding: .9em 1.1em;
  margin: 0 0 1.6em; box-shadow: 0 0 0 3px var(--bg), 0 0 18px rgba(57,255,20,.35); }
.panel > .bar { font-family: 'Press Start 2P', monospace; font-size: 10px; color: var(--amber);
  text-shadow: 0 0 6px rgba(255,176,0,.6); margin: 0 0 .8em; }
form { display: flex; gap: .7em; align-items: center; flex-wrap: wrap; margin: 0; }
select, button { font-family: 'VT323', monospace; font-size: 19px; background: var(--bg);
  color: var(--grn); border: 2px solid var(--grn); padding: .15em .6em; }
button { cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }
button:hover, select:focus, button:focus-visible { background: var(--grn); color: var(--bg);
  box-shadow: 0 0 12px var(--grn); outline: none; }
.runs { list-style: none; margin: 0; padding: 0; }
.runs li a { display: flex; justify-content: space-between; gap: 1em; text-decoration: none;
  color: var(--grn); padding: .35em .7em; border: 2px solid transparent; }
.runs li a::before { content: "  "; white-space: pre; color: var(--amber); }
.runs li a:hover { border-color: var(--grn); background: rgba(57,255,20,.08);
  box-shadow: 0 0 10px rgba(57,255,20,.3); }
.runs li a:hover::before { content: "\\25B8 "; }
.count { color: var(--grn-dim); }
.hint { color: var(--grn-dim); font-size: 16px; }
.empty { color: var(--grn-dim); padding: .4em .2em; }
@media (prefers-reduced-motion: reduce) { .cursor { animation: none; } }
"""


def render_index(run_dirs, *, variants=DEFAULT_VARIANTS, root=None) -> str:
    """Entry page: a list of recorded runs (link to the viewer) + a live-launch
    form. `run_dirs` are paths; each links to `/run?dir=<path>`."""
    root = Path(root) if root is not None else None
    items = []
    for d in run_dirs:
        d = Path(d)
        label = str(d.relative_to(root)) if root and root in d.parents else d.name
        n = len(list(d.glob("*.ndjson")))
        href = "/run?dir=" + quote(str(d))
        items.append(f'<li><a href="{href}"><span>{_html.escape(label)}</span>'
                     f'<span class=count>{n} trace{"s" if n != 1 else ""}</span></a></li>')
    runs_html = ('<ul class=runs>' + "\n".join(items) + '</ul>' if items
                 else '<p class=empty>no recorded runs yet &mdash; start a live session above</p>')
    opts = "\n".join(f'<option value="{_html.escape(v)}">{_html.escape(v)}</option>' for v in variants)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>NetHack Rollout Viewer</title><style>{_INDEX_CSS}</style></head>
<body><div class=wrap>
  <h1>NETHACK ROLLOUT VIEWER<span class=cursor>_</span></h1>
  <section class=panel>
    <div class=bar>&#9654; LIVE SESSION</div>
    <form action="/live" method="get">
      <label for="variant">VARIANT</label>
      <select id="variant" name="variant">{opts}</select>
      <button type=submit>Start</button>
      <span class=hint>steps a rollout live &middot; manual</span>
    </form>
  </section>
  <section class=panel>
    <div class=bar>&#9632; RECORDED RUNS</div>
    {runs_html}
  </section>
</div></body></html>"""
