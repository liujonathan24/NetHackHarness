"""Static HTML stats dashboard over saved rollout traces.

Self-contained page (inline SVG charts, retro theme) that reads per-turn NDJSON
traces, applies the post-hoc metrics in `stats.py`, and renders:
  - a cross-run aggregate table (mean max dlvl, death rate, kills, dlvl>=3 count)
  - one time-series chart per metric, overlaying every run

No external chart deps. Custom metrics registered via `stats.register_metric`
appear automatically if passed in `metrics`.
"""
from __future__ import annotations

import html as _html
from pathlib import Path

from . import stats
from .theme import CANDY, THEME_CSS

DEFAULT_METRICS = ("dlvl", "hp_frac", "xp", "kills_cum")

# Per-run line dash patterns so runs are distinguishable WITHOUT relying on colour
# alone (WCAG 1.4.1) — important for colour-blind users. Length 6 vs the 5-colour
# palette so the (colour, dash) combo cycles with period LCM(5,6)=30 rather than
# repeating every 5 runs — each of up to 5 runs still gets a distinct dash, and
# runs 6..30 stay distinct combos instead of exactly reusing run 1's.
_DASHES = ("", "6 3", "2 3", "8 3 2 3", "1 3", "10 4")


def _svg_linechart(title: str, series_by_run: list[tuple[str, list[tuple[int, float]]]],
                   *, w: int = 560, h: int = 180) -> str:
    """One chart: x=turn, y=value, one polyline per run. series_by_run = [(label, [(x,y)..])]."""
    pad_l, pad_b, pad_t, pad_r = 38, 22, 14, 12
    xs = [x for _, s in series_by_run for x, _ in s]
    ys = [y for _, s in series_by_run for _, y in s]
    if not xs or not ys:
        return f'<div class="chart"><div class="ctitle">{_html.escape(title)}</div><div class="dim">no data</div></div>'
    # NB: no `or 1` on xmax — px()'s divisor has its own zero guard, and bumping
    # a single-point-at-turn-0 series to xmax=1 would mislabel its x-axis range.
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if ymax == ymin:
        # Flat series (constant metric, common in short recordings): pad the
        # range symmetrically so the line sits mid-chart instead of pinned to
        # the bottom axis where it reads as "no data".
        pad = abs(ymin) * 0.5 or 1
        ymin, ymax = ymin - pad, ymax + pad
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b

    def px(x):
        return pad_l + (x - xmin) / (xmax - xmin or 1) * iw

    def py(y):
        return pad_t + ih - (y - ymin) / (ymax - ymin) * ih

    # Accessible name for the chart: a bare role="img" is announced as just
    # "image". Describe the metric, the runs plotted, and the value range so a
    # screen reader conveys the chart's content. The <title> is the SVG-native
    # accessible name; aria-label backs it up for engines that don't map <title>.
    runs_txt = ", ".join(lbl for lbl, s in series_by_run if s) or "no runs"
    desc = f"Line chart: {title} over turns. Runs: {runs_txt}. Range {ymin:g} to {ymax:g}."
    parts = [f'<svg viewBox="0 0 {w} {h}" class="svgchart" role="img" '
             f'aria-label="{_html.escape(desc)}"><title>{_html.escape(desc)}</title>']
    # axes
    parts.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t+ih}" class="axis"/>')
    parts.append(f'<line x1="{pad_l}" y1="{pad_t+ih}" x2="{pad_l+iw}" y2="{pad_t+ih}" class="axis"/>')
    # y gridlines + labels (min, max)
    for yy in (ymin, (ymin + ymax) / 2, ymax):
        Y = py(yy)
        parts.append(f'<line x1="{pad_l}" y1="{Y:.1f}" x2="{pad_l+iw}" y2="{Y:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_l-5}" y="{Y+4:.1f}" class="ytick" text-anchor="end">{yy:g}</text>')
    # x-axis labels at both ends so the turn range is explicit (the left end isn't
    # always turn 0 — a trace may start partway through), and to match the y-axis
    # which labels min/mid/max.
    parts.append(f'<text x="{pad_l}" y="{pad_t+ih+18}" class="xtick" text-anchor="start">turn {xmin:g}</text>')
    if xmax != xmin:  # single-point series sits at the left edge — one label only
        parts.append(f'<text x="{pad_l+iw}" y="{pad_t+ih+18}" class="xtick" text-anchor="end">{xmax:g}</text>')
    for i, (label, s) in enumerate(series_by_run):
        if not s:
            continue
        color = CANDY[i % len(CANDY)]
        dash = _DASHES[i % len(_DASHES)]
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in s)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"'
                     + (f' stroke-dasharray="{dash}"' if dash else '') + '/>')
        # Dot markers per point. Crucial for a single-point series, where a
        # one-vertex <polyline> draws no segment and is otherwise invisible —
        # so plotting a single short trace would show "nothing". Also makes
        # flat series legible. Cheap for multi-point series.
        for x, y in s:
            parts.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="2.5" fill="{color}"/>')
    parts.append("</svg>")
    # Legend swatch is a short line sample showing the run's colour AND dash
    # pattern, so it stays distinguishable for colour-blind users (matches the
    # chart line). The label colour is left to CSS (readable on the panel bg).
    def _swatch(i):
        c = CANDY[i % len(CANDY)]
        d = _DASHES[i % len(_DASHES)]
        da = f' stroke-dasharray="{d}"' if d else ''
        return (f'<svg width="20" height="8" style="vertical-align:middle" aria-hidden="true">'
                f'<line x1="0" y1="4" x2="20" y2="4" stroke="{c}" stroke-width="2"{da}/></svg>')
    legend = " ".join(
        f'<span class="lg">{_swatch(i)} {_html.escape(lbl)}</span>'
        for i, (lbl, _) in enumerate(series_by_run))
    return (f'<div class="chart"><div class="ctitle">{_html.escape(title)}</div>'
            f'{"".join(parts)}<div class="legend">{legend}</div></div>')


def _agg_table(labels: list[str], runs: list[list[dict]]) -> str:
    rows = []
    for lbl, recs in zip(labels, runs):
        s = stats.run_summary(recs)
        died = '<span class="bad">DIED</span>' if s["died"] else '<span class="ok">—</span>'
        rows.append(
            f"<tr><td>{_html.escape(lbl)}</td><td>{s['max_dlvl']:g}</td><td>{s['max_xp']:g}</td>"
            f"<td>{s['kills']}</td><td>{s['min_hp'] if s['min_hp'] is not None else '?'}</td>"
            f"<td>{s['n_turns']}</td><td>{died}</td></tr>")
    agg = stats.aggregate(runs)
    head = (f'<div class="kpis">'
            f'<div class="kpi"><b>{agg["mean_max_dlvl"]:.2f}</b><span>mean max dlvl</span></div>'
            f'<div class="kpi"><b>{agg["mean_max_xp"]:.2f}</b><span>mean max XP</span></div>'
            f'<div class="kpi"><b>{agg["mean_kills"]:.2f}</b><span>mean kills</span></div>'
            f'<div class="kpi"><b>{agg["death_rate"]*100:.0f}%</b><span>death rate</span></div>'
            f'<div class="kpi"><b>{agg["reached_dlvl3"]}/{agg["n_runs"]}</b><span>reached dlvl 3</span></div>'
            f'</div>')
    return (head + '<table class="agg"><thead><tr><th>run</th><th>max dlvl</th><th>max XP</th>'
            '<th>kills</th><th>min HP</th><th>turns</th><th>outcome</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


_CSS = """
.wrap{max-width:1180px;margin:0 auto;padding:18px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin:0 0 16px}
.kpi{background:var(--panel);border:1px solid var(--line);padding:10px 16px;min-width:120px}
.kpi b{display:block;font-family:'Press Start 2P',monospace;font-size:18px;color:var(--gold)}
.kpi span{color:var(--dim);font-size:14px}
table.agg{width:100%;border-collapse:collapse;margin:0 0 26px;background:var(--panel)}
table.agg th,table.agg td{border:1px solid var(--line);padding:5px 10px;text-align:left}
table.agg th{color:var(--cyan);font-size:14px}
.bad{color:#ff6b6b}.ok{color:var(--mint)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:18px}
.chart{background:var(--panel);border:1px solid var(--line);padding:12px}
.ctitle{font-family:'Press Start 2P',monospace;font-size:11px;color:var(--cyan);margin-bottom:8px}
.svgchart{width:100%;height:auto}
.axis{stroke:var(--line-lt);stroke-width:1}.grid{stroke:var(--line);stroke-width:1;stroke-dasharray:2 3}
.ytick,.xtick{fill:var(--dim);font-family:ui-monospace,monospace;font-size:11px}
.legend{margin-top:6px}.lg{font-size:14px;margin-right:12px}
"""


def render_dashboard(runs: list[tuple[str, list[dict]]], *,
                     metrics: tuple[str, ...] = DEFAULT_METRICS, title: str = "ROLLOUT STATS") -> str:
    """runs = [(label, records)]. Returns a self-contained HTML dashboard."""
    labels = [lbl for lbl, _ in runs]
    recs = [r for _, r in runs]
    charts = []
    for metric in metrics:
        series_by_run = []
        for lbl, r in runs:
            try:
                series_by_run.append((lbl, stats.series(r, metric)))
            except KeyError:
                series_by_run.append((lbl, []))
        charts.append(_svg_linechart(metric, series_by_run))
    body = (f'<div class="wrap"><h1>{_html.escape(title)}</h1>'
            f'{_agg_table(labels, recs)}'
            f'<div class="charts">{"".join(charts)}</div></div>')
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{_html.escape(title)}</title><style>{THEME_CSS}{_CSS}</style></head>"
            f"<body>{body}</body></html>")


def dashboard_from_paths(paths, *, metrics: tuple[str, ...] = DEFAULT_METRICS,
                         title: str = "ROLLOUT STATS") -> str:
    """Convenience: load NDJSON trace paths, label by filename stem, render.
    A path ending in `.jsonl` is treated as a verifiers results file (one run
    per row); `.ndjson` paths are single per-turn traces."""
    runs = []
    for p in paths:
        p = Path(p)
        if p.suffix == ".jsonl":
            for i, recs in enumerate(stats.load_results_jsonl(p)):
                runs.append((f"{p.stem}#{i}", recs))
        else:
            runs.append((p.stem, stats.load_trace(p)))
    return render_dashboard(runs, metrics=metrics, title=title)


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Static stats dashboard over saved rollout traces.")
    ap.add_argument("paths", nargs="+", help="NDJSON trace files and/or verifiers results.jsonl files")
    ap.add_argument("-o", "--out", default="dashboard.html", help="output HTML path")
    ap.add_argument("-m", "--metrics", default=",".join(DEFAULT_METRICS),
                    help="comma-separated metric names (see stats.metric_names())")
    ap.add_argument("-t", "--title", default="ROLLOUT STATS")
    a = ap.parse_args(argv)
    html = dashboard_from_paths(a.paths, metrics=tuple(a.metrics.split(",")), title=a.title)
    Path(a.out).write_text(html)
    print(f"wrote {a.out} ({len(html)} bytes) from {len(a.paths)} path(s)")


if __name__ == "__main__":
    _main()
