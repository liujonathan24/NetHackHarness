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
  * /obs     Observation Creator - compose built-in + custom metrics over
             recorded .ndjson rollouts and render inline SVG charts.

The JSON API (/reset /step /live /set_tune /catalog /record_* /traces /trace
/gif*) is unchanged; this is a presentation/navigation refactor only.

Headless-friendly:

    python tools/play_server.py            # serves on 0.0.0.0:8080
    # from your laptop:  ssh -L 8080:localhost:8080 <node>   then open localhost:8080
"""

from __future__ import annotations

import argparse
import ast
import functools
import json
import math
import pathlib
import sys
import threading
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
STATE: dict = {"env": None, "seed": 42, "tune": {}, "rec": None, "turn": 0,
               "ckpt_dlvl": None, "ckpt_path": None, "resumed": False,
               # "started" is True only after a /reset or /resume actually starts
               # a game. The env alone isn't enough: /catalog lazily constructs an
               # (unstarted) env to read the knob list, and calling engine ops on
               # an unstarted game crashes the C library — so the play routes gate
               # on this, not just `env is not None`.
               "started": False,
               # Undo history: in-memory snapshot handles, one taken BEFORE each
               # /step (snapshot/restore is ~0.04ms and malloc-backed, so no disk
               # or latency cost). Bounded ring; cleared on reset/resume.
               "history": [],
               # A single manual "checkpoint" snapshot the user pins and restores
               # repeatedly (the Monte-Carlo demo: pin, roll out, restore, repeat).
               "mark": None}

_UNDO_CAP = 200
_REC_DIR = _ROOT / "outputs" / "web_play"
_TRACE_DIRS = [_REC_DIR, _ROOT / "outputs", _ROOT / "environments" / "nethack" / "outputs"]
# Serializes /obs/plot's register/render/unregister against the process-global
# custom-metric registry (Flask runs threaded).
_OBS_PLOT_LOCK = threading.Lock()

# The server shares ONE EngineEnv and the C engine is not reentrant, so no two
# engine-touching requests may run at once (e.g. the map open in two tabs, or a
# /step racing a Tracer /resume). Every route that reads or mutates the engine is
# wrapped with @_engine_locked. The client also serializes its own requests, but
# this is the cross-client safety net. RLock so a locked route may call another.
_ENGINE_LOCK = threading.RLock()


def _engine_locked(fn):
    @functools.wraps(fn)
    def _wrapped(*a, **k):
        with _ENGINE_LOCK:
            return fn(*a, **k)
    return _wrapped

_GROUPS = ["Vision", "Stat-based", "Dungeon & spawns"]
_META = {
    "vision_radius":            dict(group="Vision", kind="int",  reset=False, lo=0, hi=15, step=1, default=0, note="0 = vanilla; only matters in the dark"),
    "reveal_map":               dict(group="Vision", kind="bool", reset=False, default=0, note="on = reveal whole map incl. walls + live monsters"),
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
    # Generation knobs (consumed in mklev.c during floor build) — all reset.
    "mob_spawn":                dict(group="Dungeon & spawns", kind="scale", reset=True,  lo=0, hi=3, step=0.25, default=1, note="initial sleeping monsters per room; 0 = none"),
    "trap_density":             dict(group="Dungeon & spawns", kind="scale", reset=True,  lo=0, hi=3, step=0.25, default=1, note="traps per room; 0 = none"),
    "locked_door":              dict(group="Dungeon & spawns", kind="scale", reset=True,  lo=0, hi=3, step=0.25, default=1, note="door-lock chance; 0 = never locked"),
    "corridor_connectivity":    dict(group="Dungeon & spawns", kind="scale", reset=True,  lo=0, hi=3, step=0.25, default=1, note="extra/redundant corridors between rooms"),
    "room_size":                dict(group="Dungeon & spawns", kind="scale", reset=True,  lo=0.25, hi=3, step=0.25, default=1, note="room dimensions"),
}
_DEFAULT_META = dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=3, step=0.25, default=1, note="")


def _env() -> EngineEnv:
    if STATE["env"] is None:
        STATE["env"] = EngineEnv()
    return STATE["env"]


def _need_started():
    """Return a (response, 400) tuple if no game has been started yet, else None.
    Engine ops (step/modify/set_tune) on an env that exists but was never started
    crash the C library, so play routes must gate on this — `env is not None` is
    not enough because /catalog lazily builds an unstarted env."""
    if STATE["env"] is None or not STATE["started"]:
        return jsonify({"error": "call /reset first"}), 400
    return None


def _push_undo():
    """Snapshot the live state onto the undo ring (called BEFORE each step)."""
    try:
        STATE["history"].append(STATE["env"].snapshot())
    except Exception:
        return
    while len(STATE["history"]) > _UNDO_CAP:
        old = STATE["history"].pop(0)
        try:
            STATE["env"].free_snapshot(old)
        except Exception:
            pass


def _clear_undo():
    """Free + drop all undo snapshots (on reset/resume — a new game)."""
    for h in STATE["history"]:
        try:
            if STATE["env"] is not None:
                STATE["env"].free_snapshot(h)
        except Exception:
            pass
    STATE["history"].clear()


def _clear_mark():
    """Free + drop the pinned checkpoint (on reset/resume — a new game)."""
    if STATE["mark"] is not None:
        try:
            if STATE["env"] is not None:
                STATE["env"].free_snapshot(STATE["mark"])
        except Exception:
            pass
        STATE["mark"] = None


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
            "recording": STATE["rec"]["name"] if STATE["rec"] else None,
            "undos": len(STATE["history"]), "marked": STATE["mark"] is not None}


def _record(obs, action_key=None):
    """Append a TraceTurn-format line if recording (compatible with the tracer).

    Checkpoints are taken on floor entry: on the first recorded turn and
    whenever dlvl changes, EngineEnv.checkpoint() writes a resumable
    {seed, level, player} blob alongside the ndjson as
    ``<stem>.ckpt.<dlvl>.json``. Every recorded turn then carries the CURRENT
    floor's entry-checkpoint path in ``turn["checkpoint"]`` so the Tracer can
    resume from ANY selected step via that floor's entry checkpoint.
    """
    rec = STATE["rec"]
    if not rec:
        return
    s = _status(obs)
    dlvl = s["dlvl"]
    # Floor entry (first recorded turn or dlvl changed) -> write a checkpoint.
    if STATE["ckpt_dlvl"] != dlvl:
        stem = rec["name"][:-len(".ndjson")] if rec["name"].endswith(".ndjson") else rec["name"]
        ckpt = _REC_DIR / f"{stem}.ckpt.{dlvl}.json"
        try:
            _env().checkpoint(ckpt)
            STATE["ckpt_path"] = str(ckpt)
        except Exception:  # pragma: no cover - never let a checkpoint failure break recording
            STATE["ckpt_path"] = None
        STATE["ckpt_dlvl"] = dlvl
    msg = bytes(int(c) for c in obs.message).split(b"\x00")[0].decode("latin1", "replace")
    turn = {
        "turn": STATE["turn"], "t_wall": time.time(), "variant": "web_play",
        "raw_grid": _rows(obs), "status": s,
        "dlvl": s["dlvl"], "hp": s["hp"], "max_hp": s["max_hp"],
        "reward": 0.0, "messages": [msg] if msg else [],
        "action_indices": [ord(action_key)] if action_key else [],
        "rendered_user_message": "", "assistant_message": "", "tool_calls": [],
        "checkpoint": STATE["ckpt_path"],
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
@_engine_locked
def catalog():
    out = []
    for name in _env().tune.catalog():
        m = dict(_DEFAULT_META)
        m.update(_META.get(name, {}))
        m["name"] = name
        m.setdefault("note", "")
        out.append(m)
    # Display-order tweak (presentation only): keep the two note-less spawn knobs
    # adjacent so the 2-column knob grid pairs note rows with note rows and the
    # note-less pair shares a row — consistent row heights. Swapping
    # monster_difficulty_scale <-> monster_speed_scale puts monster_speed_scale
    # next to ongoing_spawn_scale (both note-less).
    names = [m["name"] for m in out]
    a, b = "monster_difficulty_scale", "monster_speed_scale"
    if a in names and b in names:
        i, j = names.index(a), names.index(b)
        out[i], out[j] = out[j], out[i]
    return jsonify({"groups": _GROUPS, "knobs": out})


@app.route("/reset", methods=["POST"])
@_engine_locked
def reset():
    data = request.get_json(silent=True) or {}
    # Validate before touching the engine so malformed input is a clean 400,
    # consistent with /live /set_tune /modify (was a 500 from int()/float()).
    try:
        STATE["seed"] = int(data.get("seed", STATE["seed"]))
    except (TypeError, ValueError):
        return jsonify({"error": "seed must be an integer"}), 400
    try:
        STATE["tune"] = {k: float(v) for k, v in (data.get("tune") or {}).items()}
    except (TypeError, ValueError):
        return jsonify({"error": "tune values must be numbers"}), 400
    STATE["resumed"] = False  # an explicit reset supersedes any prior resume
    try:
        # reset applies the tune dict; an unknown knob name raises KeyError ->
        # clean 400 (matches /live /set_tune) instead of an uncaught 500.
        obs, _ = _env().reset(seeds=(STATE["seed"], STATE["seed"]), tune=dict(STATE["tune"]))
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    STATE["started"] = True  # a game is now active; play routes may touch the engine
    _clear_undo()  # a new game; don't undo into the previous one
    _clear_mark()  # drop any pinned checkpoint from the old game
    # Finalize any in-progress recording before the new game proceeds: keeping the
    # same trace across a reset collides checkpoints (a new game at the same dlvl
    # reuses the prior game's <stem>.ckpt.<dlvl>.json), silently corrupting resume.
    # One recording = one game; the client reflects the stop via apply()->syncRec().
    if STATE["rec"]:
        STATE["rec"]["fh"].close()
        STATE["rec"] = None
    for _ in range(2):
        obs, _, _ = _env().step(ord("."))
    obs = _settle(_env(), obs)
    _record(obs)  # no-op now if the reset stopped an active recording
    return jsonify(_payload(obs))


def _settle(env, obs, max_iter=12):
    """Auto-dismiss pending ``--More--`` prompts so the frame settles after a
    step that queues messages (e.g. "You descend the stairs.--More--" on a level
    change, which otherwise leaves the new floor half-drawn until the user
    presses a key). Mimics auto-pressing escape. NEVER auto-answers a real
    question: only acts when waiting-for-space is set and no yn/getlin prompt is
    active (obs.misc = [in_yn_function, in_getlin, waitingforspace])."""
    for _ in range(max_iter):
        misc = getattr(obs, "misc", None)
        if misc is None:
            break
        in_yn, in_getlin, waiting = int(misc[0]), int(misc[1]), int(misc[2])
        if waiting and not in_yn and not in_getlin:
            obs, _, _ = env.step(27)  # ESC flushes the --More-- queue
        else:
            break
    return obs


@app.route("/step", methods=["POST"])
@_engine_locked
def step():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys", "")
    # Validate shape before touching the engine: a non-string `keys` would make
    # `for ch in keys` raise (or ord() choke), a 500 for what is really bad input.
    # Matches the 400-not-500 contract the other mutating routes already honor.
    if not isinstance(keys, str):
        return jsonify({"error": "keys must be a string"}), 400
    if (g := _need_started()):  # stepping an unstarted engine crashes the C lib
        return g
    obs = None
    last = None
    if keys:
        _push_undo()  # snapshot the pre-step state so /undo can return to it
    for ch in keys:
        obs, _d, _i = STATE["env"].step(ord(ch))
        last = ch
    if obs is None:
        return jsonify({"error": "no keys"}), 400
    obs = _settle(STATE["env"], obs)
    _record(obs, last)
    return jsonify(_payload(obs))


@app.route("/undo", methods=["POST"])
@_engine_locked
def undo():
    """Step back: restore the snapshot taken before the last step(s). {n: k}
    undoes k steps at once. Returns the reverted frame (or 400 if nothing to
    undo). Does not rewind an active recording (undo is a live-play affordance)."""
    if (g := _need_started()):
        return g
    data = request.get_json(silent=True) or {}
    try:
        n = int(data.get("n", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "n must be an integer"}), 400
    hist = STATE["history"]
    if not hist:
        return jsonify({"error": "nothing to undo"}), 400
    n = max(1, min(n, len(hist)))
    target = None
    for _ in range(n):  # pop n; free the ones we skip past, keep the n-th back
        if target is not None:
            try:
                STATE["env"].free_snapshot(target)
            except Exception:
                pass
        target = hist.pop()
    STATE["env"].restore(target)
    try:
        STATE["env"].free_snapshot(target)  # consumed by the restore
    except Exception:
        pass
    # A restore only shows up in the observation after the next step, so issue a
    # ctrl-R redraw (action 18 — repaints + vision recalc, takes no game turn) to
    # render the restored frame; mirrors /live and /resume.
    obs, _, _ = STATE["env"].step(18)
    obs = _settle(STATE["env"], obs)
    return jsonify({**_payload(obs), "undos_left": len(hist)})


@app.route("/mark", methods=["POST"])
@_engine_locked
def mark():
    """Pin the current state as the checkpoint (overwrites any prior pin). The
    Monte-Carlo demo: pin here, roll out, /restore_mark, roll out again."""
    if (g := _need_started()):
        return g
    _clear_mark()
    try:
        STATE["mark"] = STATE["env"].snapshot()
    except Exception as e:
        return jsonify({"error": f"could not checkpoint: {e}"}), 400
    return jsonify({"marked": True})


@app.route("/restore_mark", methods=["POST"])
@_engine_locked
def restore_mark():
    """Restore the pinned checkpoint (it stays pinned — restore repeatedly). A
    ctrl-R redraw renders the reverted frame (a restore only shows after a step).
    Snapshots taken before the pin are still undoable; we keep the undo history
    as-is so the timeline stays consistent with what's on screen."""
    if (g := _need_started()):
        return g
    if STATE["mark"] is None:
        return jsonify({"error": "no checkpoint set"}), 400
    STATE["env"].restore(STATE["mark"])
    obs, _, _ = STATE["env"].step(18)
    obs = _settle(STATE["env"], obs)
    return jsonify(_payload(obs))


@app.route("/modify", methods=["POST"])
@_engine_locked
def modify():
    data = request.get_json(silent=True) or {}
    # Validate shape + coerce before touching the engine, so malformed input is a
    # clean 400 (and testable without one). A non-dict `changes` would make
    # .items() raise, and int(None)/int([..]) raise TypeError (not ValueError),
    # so without this both were uncaught 500s.
    changes = data.get("changes") or {}
    if not isinstance(changes, dict):
        return jsonify({"error": "changes must be an object"}), 400
    try:
        clean = {k: int(v) for k, v in changes.items()}
    except (TypeError, ValueError):
        return jsonify({"error": "change values must be integers"}), 400
    if (g := _need_started()):
        return g
    # EngineEnv.modify validates names + bounds (secure); unknown name -> KeyError.
    try:
        obs = STATE["env"].modify(**clean)
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    obs = _settle(STATE["env"], obs)
    _record(obs)
    return jsonify(_payload(obs))


def _tune_args(data):
    """Validate a {name, value} tune request. Returns (name, value) on success
    or a (json_response, status) tuple to return directly. A missing/non-numeric
    value or non-string name yields a clean 400 instead of a 500 — the engine's
    set_tune still enforces the knob allow-list + bounds on top of this."""
    name = data.get("name")
    if not isinstance(name, str) or not name:
        return None, (jsonify({"error": "tune name must be a non-empty string"}), 400)
    try:
        value = float(data.get("value"))
    except (TypeError, ValueError):
        return None, (jsonify({"error": "tune value must be a number"}), 400)
    return (name, value), None


@app.route("/set_tune", methods=["POST"])
@_engine_locked
def set_tune():
    data = request.get_json(silent=True) or {}
    parsed, err = _tune_args(data)
    if err:
        return err
    name, value = parsed
    # set_tune persists to STATE["tune"] for the next reset; only push it to the
    # live engine if a game is actually started (gate on "started", not just a
    # non-None env, since /catalog leaves an unstarted env that would crash).
    if STATE["started"]:
        try:
            STATE["env"].set_tune(**{name: value})
        except (KeyError, ValueError) as e:
            return jsonify({"error": str(e)}), 400
    STATE["tune"][name] = value
    return jsonify({"ok": True})


@app.route("/live", methods=["POST"])
@_engine_locked
def live():
    data = request.get_json(silent=True) or {}
    if (g := _need_started()):  # set_tune + redraw-step crash on an unstarted engine
        return g
    parsed, err = _tune_args(data)
    if err:
        return err
    name, value = parsed
    try:
        STATE["env"].set_tune(**{name: value})
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    STATE["tune"][name] = value
    obs, _, _ = STATE["env"].step(18)  # ctrl-R redraw -> vision_recalc, no move
    obs = _settle(STATE["env"], obs)
    return jsonify(_payload(obs))


@app.route("/record_start", methods=["POST"])
@_engine_locked
def record_start():
    if STATE["rec"]:
        return jsonify({"name": STATE["rec"]["name"]})
    _REC_DIR.mkdir(parents=True, exist_ok=True)
    # Millisecond precision: a second-resolution stamp collides if you stop one
    # recording and start another within the same second (the new file would
    # overwrite the just-saved .ndjson + its checkpoints).
    name = f"web_{int(time.time() * 1000)}.ndjson"
    STATE["rec"] = {"name": name, "fh": open(_REC_DIR / name, "w")}
    STATE["turn"] = 0
    STATE["ckpt_dlvl"] = None  # force a floor-entry checkpoint on the first turn
    STATE["ckpt_path"] = None
    if STATE["started"]:  # only capture turn 0 if a game is live (not just /catalog's env)
        _record(_env().engine.to_core_observation())  # capture current as turn 0
    return jsonify({"name": name})


@app.route("/record_stop", methods=["POST"])
@_engine_locked
def record_stop():
    rec = STATE["rec"]
    if rec:
        rec["fh"].close()
        STATE["rec"] = None
        return jsonify({"name": rec["name"], "turns": STATE["turn"]})
    return jsonify({"name": None})


@app.route("/resume", methods=["POST"])
@_engine_locked
def resume():
    """Resume play from a recorded floor-entry checkpoint.

    The checkpoint path is validated against the trace-dirs allow-list (same
    safety check as /trace), so arbitrary paths are rejected with 400. On
    success the env is restored to the checkpoint state; the user then keeps
    playing through the normal /step. Sets STATE["resumed"] so the Map Viewer's
    initial load renders this state instead of auto-resetting (see /current).
    """
    data = request.get_json(silent=True) or {}
    rp = _trace_allowed(data.get("checkpoint") or "")
    if rp is None:
        return jsonify({"error": "checkpoint not allowed"}), 400
    try:
        obs = _env().resume(rp)
    except Exception as e:  # malformed/incompatible checkpoint -> clean 400
        return jsonify({"error": f"could not resume: {e}"}), 400
    STATE["started"] = True  # resume starts a live game
    _clear_undo()  # resumed into a different game; clear prior undo history
    _clear_mark()  # drop any pinned checkpoint from the prior game
    # Like /reset: a resume loads a different game, so finalize any in-progress
    # recording rather than append the resumed game to it (checkpoint collision).
    if STATE["rec"]:
        STATE["rec"]["fh"].close()
        STATE["rec"] = None
    obs = _settle(_env(), obs)
    # Reflect the resumed game in the Map Viewer's state: the env now owns its
    # seed/tune; mirror them so the seed box + knob panel match what's playing.
    seeds = _env().current_seeds
    if seeds is not None:
        STATE["seed"] = int(seeds[0])
    STATE["tune"] = dict(_env().get_tune())
    STATE["resumed"] = True
    return jsonify(_payload(obs))


@app.route("/current", methods=["GET"])
@_engine_locked
def current():
    """Return the current live env frame WITHOUT stepping or resetting.

    The Map Viewer calls this on load: if a resume just happened (or any live
    env exists) it renders that frame; otherwise it signals the page to do a
    normal /reset. Consumes the one-shot ``resumed`` flag so a later manual
    reload behaves normally."""
    if STATE["env"] is None:
        return jsonify({"live": False})
    resumed = STATE["resumed"]
    STATE["resumed"] = False  # one-shot: only the first post-resume load skips reset
    # The env can exist without a started game: /catalog lazily constructs one
    # (to read the knob list) before the page's first /reset. Reading a frame
    # then raises ("requires an active game"). Treat that like no live game and
    # let the page do its normal reset, instead of 500-ing on every cold load.
    try:
        obs = _env().engine.to_core_observation()
        payload = _payload(obs)
    except Exception:
        return jsonify({"live": False})
    payload["live"] = bool(resumed)
    payload["seed"] = STATE["seed"]
    return jsonify(payload)


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
                with open(p) as fh:
                    n = sum(1 for _ in fh)
            except OSError:
                n = 0
            out.append({"path": rp, "name": str(p.relative_to(_ROOT)), "turns": n})
    return jsonify(out)


@app.route("/trace")
def trace():
    path = request.args.get("path", "")
    rp = pathlib.Path(path).resolve()
    if not _under_trace_dirs(rp) or not rp.is_file():
        return jsonify({"error": "not allowed"}), 400
    turns = []
    with open(rp) as fh:  # context-managed so the fd is closed deterministically
        for line in fh:   # streamed line-by-line (don't slurp a huge trace into memory)
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):  # valid-JSON but non-object line (bad export) -> skip, don't 500
                continue
            # Coerce field types: the Tracer loads ANY .ndjson under the trace
            # dirs (not just web-recorded ones), so a foreign trace might carry
            # e.g. a string `reward` or non-list `messages`. The client does
            # reward.toFixed() and messages.join(), which throw on the wrong
            # type and break scrubbing — so normalize at this boundary.
            try:
                reward = float(o.get("reward", 0.0))
            except (TypeError, ValueError):
                reward = 0.0
            def _list(key):
                v = o.get(key)
                return v if isinstance(v, list) else []
            turns.append({
                "turn": o.get("turn", len(turns)),
                "raw_grid": _list("raw_grid"),
                "status": o.get("status") if isinstance(o.get("status"), dict) else {},
                "reward": reward,
                "messages": _list("messages"),
                "user": o.get("rendered_user_message", ""),
                "assistant": o.get("assistant_message", ""),
                "tool_calls": _list("tool_calls"),
                "actions": _list("action_indices"),
                "checkpoint": o.get("checkpoint"),
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


def _under_trace_dirs(rp: pathlib.Path) -> bool:
    """True iff `rp` (already resolved) sits inside one of the _TRACE_DIRS.
    Uses proper path containment (is_relative_to) rather than a prefix-string
    check, so a sibling like `outputs_evil/` does NOT match `outputs/`."""
    return any(rp.is_relative_to(d.resolve()) for d in _TRACE_DIRS)


def _trace_allowed(path) -> pathlib.Path | None:
    """Resolve `path` and return it only if it sits under the _TRACE_DIRS
    allow-list and is a real file (same check the /trace route enforces).

    Callers pass untrusted values: /resume forwards a checkpoint string from a
    trace file (a foreign trace could carry a non-string), and /obs/plot forwards
    client-supplied paths. A non-string would make pathlib.Path() raise, turning
    bad input into a 500 — so reject non-string/empty here and return None."""
    if not isinstance(path, str) or not path:
        return None
    rp = pathlib.Path(path).resolve()
    if rp.is_file() and _under_trace_dirs(rp):
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
            try:
                return float(node.value)  # huge int literals raise OverflowError
            except OverflowError:
                raise ValueError("numeric literal is too large") from None
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
        if v is MISSING:
            return None
        v = float(v)
        # overflow (e.g. 1e308*1e308 -> inf) / nan must not poison chart coords;
        # treat non-finite like a missing value (same as div-by-zero -> None).
        return v if math.isfinite(v) else None
    return fn


@app.route("/obs/metrics")
def obs_metrics():
    return jsonify({"metrics": stats.metric_names()})


@app.route("/obs/plot", methods=["POST"])
def obs_plot():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):  # non-dict body (e.g. [1,2] / "hi") -> clean 400
        return jsonify({"error": "request body must be a JSON object"}), 400
    paths = data.get("paths") or []
    metrics = list(data.get("metrics") or [])
    custom = data.get("custom") or []

    # Custom metrics are registered process-wide in stats._CUSTOM_METRICS, so we
    # track the names WE add this request and unregister them in a finally —
    # otherwise they leak into later /obs/metrics responses and a reused name
    # silently overwrites the previous one across requests. Serialize the whole
    # register->render->unregister section: Flask is threaded, so two concurrent
    # plots would otherwise race on the shared registry (one's unregister yanking
    # the other's metric, or a KeyError on unregister).
    registered: list[str] = []
    _OBS_PLOT_LOCK.acquire()
    try:
        # 1) register custom composed metrics over the existing series (safe eval).
        # Built-in names are resolved custom-first by stats.series, so a custom
        # metric named e.g. `dlvl` would permanently shadow the built-in — reject.
        known = set(stats.metric_names())
        for c in custom:
            if not isinstance(c, dict):
                return jsonify({"error": "each custom metric must be an object"}), 400
            name, expr = (c.get("name") or "").strip(), (c.get("expr") or "").strip()
            if not name or not expr:
                return jsonify({"error": "custom metric needs a name and an expr"}), 400
            if name in stats.BUILTIN_METRICS:
                return jsonify({"error": f"custom metric {name!r} collides with a "
                                         f"built-in metric; pick another name"}), 400
            if name in registered:
                return jsonify({"error": f"duplicate custom metric name {name!r}"}), 400
            try:
                fn = _compile_metric_expr(expr, known)
            except (ValueError, OverflowError) as e:
                return jsonify({"error": f"metric {name!r}: {e}"}), 400
            stats.register_metric(name, fn)
            registered.append(name)
            known.add(name)
            if name not in metrics:
                metrics.append(name)
        if not metrics:
            return jsonify({"error": "no metrics selected"}), 400

        # 2) load each allow-listed trace into normalized records. Label each run
        # by filename stem, but disambiguate collisions (two traces with the same
        # filename in different dirs) so the legend + agg table aren't ambiguous.
        runs: list[tuple[str, list[dict]]] = []
        label_counts: dict[str, int] = {}
        for p in paths:
            rp = _trace_allowed(p)
            if rp is None:
                return jsonify({"error": f"path not allowed: {p}"}), 400
            label = rp.stem
            label_counts[label] = label_counts.get(label, 0) + 1
            if label_counts[label] > 1:
                label = f"{label} ({label_counts[label]})"
            runs.append((label, _normalize_records(stats.load_trace(rp))))
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
    finally:
        for name in registered:
            stats.unregister_metric(name)
        _OBS_PLOT_LOCK.release()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    print(f"NetHack console on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
