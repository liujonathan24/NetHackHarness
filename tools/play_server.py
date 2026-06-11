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
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))

from flask import Flask, jsonify, render_template, request, send_from_directory  # noqa: E402

from nethack_core.engine_env import EngineEnv  # noqa: E402

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
    return render_template("obs.html", active="obs")


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    print(f"NetHack console on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
