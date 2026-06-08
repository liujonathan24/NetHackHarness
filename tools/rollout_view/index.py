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
        items.append(f'<li><a href="{href}">{_html.escape(label)}</a> '
                     f'<span class=hint>({n} trace file{"s" if n != 1 else ""})</span></li>')
    runs_html = "<ul>" + "\n".join(items) + "</ul>" if items else "<p class=hint>No recorded runs found.</p>"
    opts = "\n".join(f'<option value="{_html.escape(v)}">{_html.escape(v)}</option>' for v in variants)
    return f"""<!doctype html><html><head><meta charset=utf-8><title>rollout views</title>
<style>
body {{ font: 14px/1.5 ui-monospace, monospace; margin: 0; background: #1e1e1e; color: #ddd; padding: 1.5em; }}
h2 {{ color: #9ad; }} a {{ color: #6cf; }} .hint {{ color: #888; font-size: 12px; }}
li {{ margin: .3em 0; }} form {{ margin: .5em 0 1.5em; }}
select, button {{ font: inherit; background: #2a2a2a; color: #ddd; border: 1px solid #444;
                  border-radius: 4px; padding: .3em .6em; }}
button {{ cursor: pointer; }}
</style></head><body>
<h2>Live session</h2>
<form action="/live" method="get">
  variant <select name="variant">{opts}</select>
  <button type="submit">Start &#9654;</button>
  <span class=hint>steps a model rollout live (manual stepping)</span>
</form>
<h2>Recorded runs</h2>
{runs_html}
</body></html>"""
