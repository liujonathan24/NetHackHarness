"""The rollout-view entry page: browse recorded runs + launch a live session."""
from __future__ import annotations
import html as _html
from pathlib import Path
from urllib.parse import quote

from tools.rollout_view.theme import THEME_CSS

# Keep in sync with the registered observation encodings.
DEFAULT_VARIANTS = ("B1", "IMG", "IMG_TTY", "JSON", "TOON")

# Index-specific layout, on top of the shared dungeon/candy THEME_CSS. Run rows get
# a small candy "tile" that rotates through the candy ramp (like colored dungeon
# tiles) — calm gray base, a few candy pops.
_INDEX_CSS = """
.wrap { max-width: 720px; margin: 0 auto; padding: 2.2em 1.2em; }
form { display: flex; gap: .7em; align-items: center; flex-wrap: wrap; margin: 0; }
form label { color: var(--dim); font-size: 16px; }
.runs { list-style: none; margin: 0; padding: 0; }
.runs li a { display: flex; align-items: center; gap: .7em; padding: .35em .6em;
  border: 2px solid transparent; color: var(--text); }
.runs li a .tile { color: var(--pink); }
.runs li:nth-child(5n+2) a .tile { color: var(--cyan); }
.runs li:nth-child(5n+3) a .tile { color: var(--gold); }
.runs li:nth-child(5n+4) a .tile { color: var(--violet); }
.runs li:nth-child(5n+5) a .tile { color: var(--mint); }
.runs li a .name { flex: 1; }
.runs li a .count { color: var(--dim); font-size: 16px; }
.runs li a:hover { border-color: var(--line-lt); background: rgba(255,255,255,.03); }
.runs li a:hover .name { color: #fff; }
.empty { color: var(--dim); padding: .4em .2em; }
"""


def discover_runs(root) -> list:
    """Return recorded-run directories under `root` (a dir holding >=1 *.ndjson),
    most-recent first. A run dir is any directory that directly contains an
    `.ndjson` trace file."""
    root = Path(root)
    if not root.exists():
        return []
    runs = {f.parent for f in root.rglob("*.ndjson")}
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


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
        items.append(f'<li><a href="{href}"><span class=tile>&#9646;</span>'
                     f'<span class=name>{_html.escape(label)}</span>'
                     f'<span class=count>{n} trace{"s" if n != 1 else ""}</span></a></li>')
    runs_html = ('<ul class=runs>' + "\n".join(items) + '</ul>' if items
                 else '<p class=empty>no recorded runs yet &mdash; start a live session above</p>')
    opts = "\n".join(f'<option value="{_html.escape(v)}">{_html.escape(v)}</option>' for v in variants)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>NetHack Rollout Viewer</title><style>{THEME_CSS}{_INDEX_CSS}</style></head>
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
  <section class=panel>
    <div class=bar>&#128193; BROWSE FILES</div>
    <p class=hint><a href="/browse">click through the runs folder &rarr;</a>
    &middot; open any <code>.ndjson</code>/<code>.jsonl</code> in the stats dashboard</p>
  </section>
</div></body></html>"""
