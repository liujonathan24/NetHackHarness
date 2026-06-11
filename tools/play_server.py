"""NetHack web console over the fork engine: a multi-page browser app.

This is the primary interface (the Textual launchpad is legacy). Pages
(Jinja templates under tools/webconsole/templates, assets under static/):

  * /        landing - README/description + GIF gallery + nav cards.
  * /map     Map Viewer - live interactive play on EngineEnv, with the
             difficulty/generation knobs grouped into Vision / Stat-based /
             Dungeon & spawns. Live knobs apply immediately (vision refreshes
             without moving via ctrl-R); reset knobs regenerate on Reset. A
             Record toggle writes the session out as a .ndjson trace.
  * /traces  Tracer - replay recorded .ndjson rollouts (the TraceTurn format the
             launchpad tracer uses): scrub turns, see the map + status + reward +
             any LLM messages. Web recordings show up here too.
  * /obs     Observation Creator - placeholder (filled in by a later task).

The JSON API (/reset /step /live /set_tune /catalog /record_* /traces /trace
/gif*) is unchanged; this is a presentation/navigation refactor only.

Headless-friendly:

    python tools/play_server.py            # serves on 0.0.0.0:8080
    # from your laptop:  ssh -L 8080:localhost:8080 <node>   then open localhost:8080
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))
sys.path.insert(0, str(_ROOT))  # so `tools.rollout_view` imports when run as a script

from flask import Flask, jsonify, render_template, request, send_from_directory  # noqa: E402

from nethack_core.engine_env import EngineEnv  # noqa: E402

from tools.rollout_view import dashboard, stats  # noqa: E402

_WEB = _ROOT / "tools" / "webconsole"
app = Flask(
    __name__,
    template_folder=str(_WEB / "templates"),
    static_folder=str(_WEB / "static"),
)
STATE: dict = {"env": None, "seed": 42, "tune": {}, "rec": None, "turn": 0}
_REC_DIR = _ROOT / "outputs" / "web_play"
_TRACE_DIRS = [_REC_DIR, _ROOT / "outputs", _ROOT / "environments" / "nethack" / "outputs"]

_GROUPS = ["Vision", "Stat-based", "Dungeon & spawns"]
_META = {
    "vision_radius":            dict(group="Vision", kind="int",  reset=False, lo=0, hi=15, step=1, default=0, note="0 = vanilla; only matters in the dark"),
    "fog_of_war":               dict(group="Vision", kind="bool", reset=False, default=1, note="off = reveal whole floor"),
    "reveal_map":               dict(group="Vision", kind="bool", reset=False, default=0, note="on = reveal whole floor"),
    "dmg_to_player_scale":      dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=4, step=0.25, default=1),
    "dmg_by_player_scale":      dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=4, step=0.25, default=1),
    "player_hp_scale":          dict(group="Stat-based", kind="scale", reset=False, lo=0.25, hi=4, step=0.25, default=1, note="HP gained on level-up"),
    "hp_regen_scale":           dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=8, step=0.5, default=1),
    "hunger_rate_scale":        dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=5, step=0.25, default=1),
    "xp_gain_scale":            dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=10, step=0.5, default=1),
    "room_density":             dict(group="Dungeon & spawns", kind="scale", reset=True,  lo=0.0, hi=1.5, step=0.05, default=1, note="RESET to regenerate the floor"),
    "monster_difficulty_scale": dict(group="Dungeon & spawns", kind="scale", reset=True,  lo=0, hi=10, step=0.5, default=1, note="RESET to reshape this floor; live for new spawns"),
    "ongoing_spawn_scale":      dict(group="Dungeon & spawns", kind="scale", reset=False, lo=0, hi=20, step=0.5, default=1),
    "monster_speed_scale":      dict(group="Dungeon & spawns", kind="scale", reset=False, lo=0, hi=4, step=0.25, default=1),
}
_DEFAULT_META = dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=3, step=0.25, default=1, note="")


def _env() -> EngineEnv:
    if STATE["env"] is None:
        STATE["env"] = EngineEnv()
    return STATE["env"]


def _rows(obs):
    return ["".join(chr(int(c)) if 32 <= int(c) < 127 else " " for c in r) for r in obs.chars]


def _status(obs):
    b = [int(x) for x in obs.blstats]
    return {"hp": b[10], "max_hp": b[11], "ac": b[16], "dlvl": b[12], "gold": b[13],
            "xp_lvl": b[18] if len(b) > 18 else 0}


def _payload(obs) -> dict:
    msg = bytes(int(c) for c in obs.message).split(b"\x00")[0].decode("latin1", "replace")
    return {"map": _rows(obs), "colors": [[int(c) for c in r] for r in obs.colors],
            "message": msg, "status": _status(obs),
            "tune": _env().get_tune(), "done": bool(obs is not None and _env().done),
            "recording": STATE["rec"]["name"] if STATE["rec"] else None}


def _record(obs, action_key=None):
    """Append a TraceTurn-format line if recording (compatible with the tracer)."""
    rec = STATE["rec"]
    if not rec:
        return
    s = _status(obs)
    msg = bytes(int(c) for c in obs.message).split(b"\x00")[0].decode("latin1", "replace")
    turn = {
        "turn": STATE["turn"], "t_wall": time.time(), "variant": "web_play",
        "raw_grid": _rows(obs), "status": s,
        "dlvl": s["dlvl"], "hp": s["hp"], "max_hp": s["max_hp"],
        "reward": 0.0, "messages": [msg] if msg else [],
        "action_indices": [ord(action_key)] if action_key else [],
        "rendered_user_message": "", "assistant_message": "", "tool_calls": [],
    }
    rec["fh"].write(json.dumps(turn) + "\n")
    rec["fh"].flush()
    STATE["turn"] += 1


# --------------------------------------------------------------------------
# Play routes
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Page routes (HTML). The JSON API below is unchanged.
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("landing.html", active="home")


@app.route("/map")
def page_map():
    return render_template("map.html", active="map")


@app.route("/obs")
def page_obs():
    # dashboard._CSS styles the embedded SVG chart fragments (.chart .ctitle
    # .svgchart .legend .agg .kpis ...) returned by /obs/plot; inject it so they
    # render correctly inside the page (console.css already supplies the vars).
    return render_template("obs.html", active="obs", dash_css=dashboard._CSS)


@app.route("/catalog")
def catalog():
    out = []
    for name in _env().tune.catalog():
        m = dict(_DEFAULT_META)
        m.update(_META.get(name, {}))
        m["name"] = name
        m.setdefault("note", "")
        out.append(m)
    return jsonify({"groups": _GROUPS, "knobs": out})


@app.route("/reset", methods=["POST"])
def reset():
    data = request.get_json(silent=True) or {}
    STATE["seed"] = int(data.get("seed", STATE["seed"]))
    STATE["tune"] = {k: float(v) for k, v in (data.get("tune") or {}).items()}
    obs, _ = _env().reset(seeds=(STATE["seed"], STATE["seed"]), tune=dict(STATE["tune"]))
    for _ in range(2):
        obs, _, _ = _env().step(ord("."))
    _record(obs)
    return jsonify(_payload(obs))


@app.route("/step", methods=["POST"])
def step():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys", "")
    if STATE["env"] is None:
        return jsonify({"error": "call /reset first"}), 400
    obs = None
    last = None
    for ch in keys:
        obs, _d, _i = STATE["env"].step(ord(ch))
        last = ch
    if obs is None:
        return jsonify({"error": "no keys"}), 400
    _record(obs, last)
    return jsonify(_payload(obs))


@app.route("/set_tune", methods=["POST"])
def set_tune():
    data = request.get_json(silent=True) or {}
    name, value = data.get("name"), float(data.get("value"))
    if STATE["env"] is not None:
        STATE["env"].set_tune(**{name: value})
    STATE["tune"][name] = value
    return jsonify({"ok": True})


@app.route("/live", methods=["POST"])
def live():
    data = request.get_json(silent=True) or {}
    name, value = data.get("name"), float(data.get("value"))
    if STATE["env"] is None:
        return jsonify({"error": "call /reset first"}), 400
    STATE["env"].set_tune(**{name: value})
    STATE["tune"][name] = value
    obs, _, _ = STATE["env"].step(18)  # ctrl-R redraw -> vision_recalc, no move
    return jsonify(_payload(obs))


@app.route("/record_start", methods=["POST"])
def record_start():
    if STATE["rec"]:
        return jsonify({"name": STATE["rec"]["name"]})
    _REC_DIR.mkdir(parents=True, exist_ok=True)
    name = f"web_{int(time.time())}.ndjson"
    STATE["rec"] = {"name": name, "fh": open(_REC_DIR / name, "w")}
    STATE["turn"] = 0
    if STATE["env"] is not None:
        _record(_env().engine.to_core_observation())  # capture current as turn 0
    return jsonify({"name": name})


@app.route("/record_stop", methods=["POST"])
def record_stop():
    rec = STATE["rec"]
    if rec:
        rec["fh"].close()
        STATE["rec"] = None
        return jsonify({"name": rec["name"], "turns": STATE["turn"]})
    return jsonify({"name": None})


@app.route("/gifs")
def gifs():
    return jsonify([p.name[4:-4] for p in sorted((_ROOT / "videos").glob("gif_*.gif"))])


@app.route("/gif/<name>")
def gif(name):
    return send_from_directory(_ROOT / "videos", f"gif_{name}.gif")


# --------------------------------------------------------------------------
# Traces routes
# --------------------------------------------------------------------------

@app.route("/traces")
def traces():
    # Serve the Tracer page to browser navigations (Accept: text/html);
    # return the JSON rollout list to fetch() / API clients (unchanged shape).
    accept = request.accept_mimetypes
    if accept["text/html"] and accept["text/html"] >= accept["application/json"]:
        return render_template("traces.html", active="traces")
    seen, out = set(), []
    for d in _TRACE_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.ndjson")):
            rp = str(p.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            try:
                n = sum(1 for _ in open(p))
            except OSError:
                n = 0
            out.append({"path": rp, "name": str(p.relative_to(_ROOT)), "turns": n})
    return jsonify(out)


@app.route("/trace")
def trace():
    path = request.args.get("path", "")
    rp = pathlib.Path(path).resolve()
    if not any(str(rp).startswith(str(d.resolve())) for d in _TRACE_DIRS) or not rp.is_file():
        return jsonify({"error": "not allowed"}), 400
    turns = []
    for line in open(rp):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        turns.append({
            "turn": o.get("turn", len(turns)),
            "raw_grid": o.get("raw_grid", []),
            "status": o.get("status", {}),
            "reward": o.get("reward", 0.0),
            "messages": o.get("messages", []),
            "user": o.get("rendered_user_message", ""),
            "assistant": o.get("assistant_message", ""),
            "tool_calls": o.get("tool_calls", []),
            "actions": o.get("action_indices", []),
        })
    return jsonify({"turns": turns})


# --------------------------------------------------------------------------
# Observation Creator routes (/obs)
#
# Load web-recorded .ndjson rollouts via rollout_view.stats.load_trace, compose
# custom metrics over the EXISTING built-in series with a RESTRICTED, SAFE
# expression evaluator (AST whitelist — no eval/exec), then render embeddable SVG
# charts via rollout_view.dashboard so they sit inline on the retro /obs page.
# --------------------------------------------------------------------------

# AST node types the composed-metric expression evaluator accepts. Anything else
# (calls, attribute access, subscripts, comprehensions, names that aren't a known
# metric, ...) is rejected — this whitelist is the security boundary; NO eval/exec.
_SAFE_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
_SAFE_UNARYOPS = {ast.USub: lambda a: -a, ast.UAdd: lambda a: +a}


def _trace_allowed(path: str) -> pathlib.Path | None:
    """Resolve `path` and return it only if it sits under the _TRACE_DIRS
    allow-list and is a real file (same check the /trace route enforces)."""
    rp = pathlib.Path(path).resolve()
    if rp.is_file() and any(str(rp).startswith(str(d.resolve())) for d in _TRACE_DIRS):
        return rp
    return None


def _normalize_records(records: list[dict]) -> list[dict]:
    """Web traces (_record) store status with `xp_lvl`, but stats.py's `xp`
    metric reads status['xp']. Map xp_lvl -> xp when xp is absent so the series
    isn't empty for web recordings. Traces that already carry `xp` (or parse it
    from rendered text) are untouched, so other tools' traces keep working."""
    for r in records:
        st = r.get("status") or {}
        if "xp" not in st and "xp_lvl" in st:
            st["xp"] = st["xp_lvl"]
    return records


def _compile_metric_expr(expr: str, known: set[str]):
    """Parse a composed-metric expression into a per-record fn via an AST
    whitelist. Only +,-,*,/ , unary +/- , numeric literals, parentheses and
    bare metric names (must be in `known`) are allowed. A referenced metric that
    is None at a turn makes the whole composed value None for that turn.
    Raises ValueError on anything outside the whitelist."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"could not parse expression: {e}") from None

    # _Missing propagates None: any sub-expression touching a missing metric is None.
    class _Missing:
        pass
    MISSING = _Missing()

    def _ev(node, rec):
        if isinstance(node, ast.Expression):
            return _ev(node.body, rec)
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
            a, b = _ev(node.left, rec), _ev(node.right, rec)
            if a is MISSING or b is MISSING:
                return MISSING
            if isinstance(node.op, ast.Div) and b == 0:
                return MISSING
            return _SAFE_BINOPS[type(node.op)](a, b)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARYOPS:
            a = _ev(node.operand, rec)
            return MISSING if a is MISSING else _SAFE_UNARYOPS[type(node.op)](a)
        # numeric literal only (reject str/bytes/bool constants)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("only numeric literals are allowed")
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in known:
                raise ValueError(f"unknown metric {node.id!r}; known: {sorted(known)}")
            v = stats.series([rec], node.id)
            return v[0][1] if v else MISSING
        raise ValueError(f"disallowed expression element: {type(node).__name__}")

    # Validate the whole tree once (with a dummy record) so bad exprs fail fast,
    # before any metric is registered.
    _ev(tree, {"status": {}, "text": "", "raw_grid": None, "raw": {}, "turn": 0})

    def fn(rec):
        v = _ev(tree, rec)
        return None if v is MISSING else float(v)
    return fn


@app.route("/obs/metrics")
def obs_metrics():
    return jsonify({"metrics": stats.metric_names()})


@app.route("/obs/plot", methods=["POST"])
def obs_plot():
    data = request.get_json(silent=True) or {}
    paths = data.get("paths") or []
    metrics = list(data.get("metrics") or [])
    custom = data.get("custom") or []

    # 1) register custom composed metrics over the existing series (safe eval).
    known = set(stats.metric_names())
    for c in custom:
        name, expr = (c.get("name") or "").strip(), (c.get("expr") or "").strip()
        if not name or not expr:
            return jsonify({"error": "custom metric needs a name and an expr"}), 400
        try:
            fn = _compile_metric_expr(expr, known)
        except ValueError as e:
            return jsonify({"error": f"metric {name!r}: {e}"}), 400
        stats.register_metric(name, fn)
        known.add(name)
        if name not in metrics:
            metrics.append(name)
    if not metrics:
        return jsonify({"error": "no metrics selected"}), 400

    # 2) load each allow-listed trace into normalized records.
    runs: list[tuple[str, list[dict]]] = []
    for p in paths:
        rp = _trace_allowed(p)
        if rp is None:
            return jsonify({"error": f"path not allowed: {p}"}), 400
        runs.append((rp.stem, _normalize_records(stats.load_trace(rp))))
    if not runs:
        return jsonify({"error": "no traces selected"}), 400

    # 3) render embeddable SVG fragments (one chart per metric) + an aggregate
    # table, so they sit inline on the /obs page (no iframe / full doc).
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
        charts.append(dashboard._svg_linechart(metric, series_by_run))
    html = (dashboard._agg_table(labels, recs) +
            f'<div class="charts">{"".join(charts)}</div>')
    return jsonify({"charts_html": html})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    print(f"NetHack console on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
