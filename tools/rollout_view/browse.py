"""Finder-style filesystem browser for the rollout-view UI.

Renders a clickable directory listing (navigate into nested folders via
breadcrumbs + folder links) confined to a root. Trace/results files link
straight to the stats dashboard; run dirs (holding .ndjson) link to the
slider viewer. Pure stdlib + the shared retro theme.
"""
from __future__ import annotations

import html as _html
from pathlib import Path
from urllib.parse import quote

from .theme import THEME_CSS

_DATA_SUFFIXES = (".ndjson", ".jsonl")


def _safe_join(root: Path, rel: str) -> Path | None:
    """Resolve root/rel, refusing anything that escapes root."""
    root = Path(root).resolve()
    target = (root / rel).resolve()
    if target == root or root in target.parents:
        return target
    return None


def _is_run_dir(d: Path) -> bool:
    try:
        return d.is_dir() and any(d.glob("*.ndjson"))
    except OSError:
        return False


def _sizeof(p: Path) -> str:
    try:
        n = p.stat().st_size
    except OSError:
        return ""
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}T"


def _breadcrumb(root: Path, rel: str) -> str:
    parts = [p for p in Path(rel).parts if p not in ("", ".")]
    crumbs = [f'<a href="/browse">{_html.escape(root.name or "root")}</a>']
    acc = ""
    for part in parts:
        acc = f"{acc}/{part}" if acc else part
        crumbs.append(f'<a href="/browse?path={quote(acc)}">{_html.escape(part)}</a>')
    return ' <span class=sep>/</span> '.join(crumbs)


def render_browser(root, rel: str = "") -> str:
    """HTML page listing the contents of root/rel (confined to root)."""
    root = Path(root).resolve()
    cur = _safe_join(root, rel)
    if cur is None or not cur.exists():
        body = '<p class=empty>path not found (or outside the runs root)</p>'
        return _page(root, rel, body)
    if cur.is_file():  # a file: offer to open it in the dashboard
        href = "/dashboard?path=" + quote(rel)
        body = (f'<p>File <b>{_html.escape(cur.name)}</b> ({_sizeof(cur)}). '
                f'<a class=btn href="{href}">open in dashboard &rarr;</a></p>')
        return _page(root, rel, body)

    try:
        entries = sorted(cur.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        entries = []
    rows = []
    if cur != root:
        up = str(Path(rel).parent) if Path(rel).parent != Path(".") else ""
        rows.append(f'<li class=dir><a href="/browse?path={quote(up)}">'
                    f'<span class=ico>&#8617;</span><span class=nm>..</span></a></li>')
    for e in entries:
        erel = str(e.relative_to(root))
        if e.is_dir():
            actions = []
            if _is_run_dir(e):
                actions.append(f'<a class=act href="/run?dir={quote(str(e))}">view run</a>')
                actions.append(f'<a class=act href="/dashboard?path={quote(erel)}">dashboard</a>')
            n_sub = sum(1 for _ in e.glob("*")) if e.is_dir() else 0
            rows.append(
                f'<li class=dir><a href="/browse?path={quote(erel)}">'
                f'<span class=ico>&#128193;</span><span class=nm>{_html.escape(e.name)}</span>'
                f'<span class=meta>{n_sub} items</span></a>{"".join(actions)}</li>')
        else:
            is_data = e.suffix in _DATA_SUFFIXES
            link = (f'<a class=act href="/dashboard?path={quote(erel)}">dashboard</a>'
                    if is_data else "")
            rows.append(
                f'<li class=file><span class=ico>&#128196;</span>'
                f'<span class=nm>{_html.escape(e.name)}</span>'
                f'<span class=meta>{_sizeof(e)}</span>{link}</li>')
    listing = ("<ul class=fs>" + "".join(rows) + "</ul>" if rows
               else "<p class=empty>empty folder</p>")
    return _page(root, rel, listing)


_CSS = """
.wrap{max-width:980px;margin:0 auto;padding:18px}
.crumb{font-size:17px;margin:0 0 14px;color:var(--dim)}.crumb a{color:var(--cyan)}.crumb .sep{color:var(--line-lt)}
ul.fs{list-style:none;margin:0;padding:0}
ul.fs li{display:flex;align-items:center;gap:10px;padding:7px 10px;border:1px solid var(--line);
  border-bottom:none;background:var(--panel)}
ul.fs li:last-child{border-bottom:1px solid var(--line)}
ul.fs li:hover{background:var(--surface)}
ul.fs a{color:var(--text);text-decoration:none;display:flex;align-items:center;gap:10px;flex:1}
.ico{width:1.3em;text-align:center}.nm{flex:1}.meta{color:var(--dim);font-size:14px}
.act{flex:0 0 auto;color:#1a1206 !important;background:var(--gold);padding:2px 9px;font-size:14px;border:1px solid var(--gold)}
.act:hover{background:var(--cyan);border-color:var(--cyan)}
li.dir .nm{color:var(--cyan)}.btn{color:#1a1206;background:var(--gold);padding:3px 10px;text-decoration:none}
.empty{color:var(--dim)}
"""


def _page(root: Path, rel: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><title>browse · {_html.escape(rel or root.name)}</title>"
            f"<style>{THEME_CSS}{_CSS}</style></head><body><div class=wrap>"
            f"<h1>FILES</h1><div class=crumb>{_breadcrumb(root, rel)}</div>{body}"
            f'<p style="margin-top:18px"><a class=crumb href="/">&#8592; back to runs index</a></p>'
            f"</div></body></html>")


def collect_data_files(root, rel: str) -> list[Path]:
    """Trace/results files for the dashboard: the file itself, or all
    *.ndjson/*.jsonl directly inside a directory."""
    target = _safe_join(Path(root).resolve(), rel)
    if target is None or not target.exists():
        return []
    if target.is_file():
        return [target]
    files: list[Path] = []
    for suf in _DATA_SUFFIXES:
        files.extend(sorted(target.glob(f"*{suf}")))
    return files
