"""NetHack web console over the fork engine: Play + Traces in one browser app.

This is the primary interface (the Textual launchpad is legacy). It has two tabs:

  * Play   - live interactive play on EngineEnv, with the difficulty/generation
             knobs grouped into Vision / Stat-based / Dungeon & spawns. Live
             knobs apply immediately (vision refreshes without moving via ctrl-R);
             reset knobs regenerate on Reset. A Record toggle writes the session
             out as a .ndjson trace.
  * Traces - replay recorded .ndjson rollouts (the TraceTurn format the launchpad
             tracer uses): scrub turns, see the map + status + reward + any LLM
             messages. Web recordings show up here too.

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

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

from nethack_core.engine_env import EngineEnv  # noqa: E402

app = Flask(__name__)
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

@app.route("/")
def index():
    return _HTML


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


_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>NetHack console</title>
<style>
  body{background:#0c0c10;color:#ddd;font-family:monospace;margin:0}
  #tabs{display:flex;background:#15151b;border-bottom:1px solid #333}
  #tabs button{background:none;border:0;color:#aaa;padding:10px 18px;cursor:pointer;font-size:14px}
  #tabs button.act{color:#fff;border-bottom:2px solid #2a7;background:#1c1c24}
  .pane{display:none}
  .pane.act{display:flex}
  #main{padding:12px}
  .screen{font-size:15px;line-height:1.15;white-space:pre;letter-spacing:0;outline:1px solid #222}
  #message{height:18px;color:#fff;margin-bottom:4px}
  #status,#t-status{height:18px;margin-top:6px;color:#eee}
  #hint{color:#888;margin-top:8px;font-size:12px}
  #demos img{max-height:300px;border:1px solid #333;background:#000}
  #side{width:360px;padding:12px;border-left:1px solid #333;background:#111;overflow-y:auto;max-height:96vh}
  h3{color:#9c9;margin:14px 0 6px;border-bottom:1px solid #333;padding-bottom:3px}
  .knob{display:flex;align-items:center;flex-wrap:wrap;margin:5px 0;gap:6px}
  .knob .name{width:150px;color:#cc8;font-size:12px}
  .knob .name .rst{color:#e85;font-size:10px}
  .knob input[type=range]{flex:1}
  .knob input.num{width:54px;background:#222;color:#fd0;border:1px solid #444;text-align:right}
  .knob .note{flex-basis:100%;color:#666;font-size:10px;margin-left:150px}
  .sw{position:relative;width:42px;height:20px;display:inline-block}
  .sw input{opacity:0;width:0;height:0}
  .sw span{position:absolute;inset:0;background:#444;border-radius:20px;cursor:pointer;transition:.15s}
  .sw span:before{content:"";position:absolute;height:14px;width:14px;left:3px;top:3px;background:#ddd;border-radius:50%;transition:.15s}
  .sw input:checked + span{background:#2a7}
  .sw input:checked + span:before{transform:translateX(22px)}
  #seedrow{margin:14px 0 8px}
  #seed{width:80px;background:#222;color:#fff;border:1px solid #444}
  button.act-btn{background:#284;color:#fff;border:0;padding:9px 12px;cursor:pointer;width:100%;font-size:14px;margin-top:6px}
  #reset.dirty{background:#a63}
  #recbtn.on{background:#a33}
  #recstat{color:#f88;font-size:12px;height:16px}
  /* traces */
  #t-list{width:300px;border-right:1px solid #333;padding:10px;overflow-y:auto;max-height:96vh}
  #t-list .f{padding:5px;cursor:pointer;font-size:12px;color:#bcb;border-bottom:1px solid #222}
  #t-list .f:hover{background:#1c1c24}
  #t-main{padding:12px;flex:1}
  #scrub{width:100%}
  #t-msgs{color:#ad8;margin:4px 0;min-height:18px}
  #t-llm{margin-top:10px;font-size:12px}
  #t-llm .lbl{color:#9c9}
  #t-llm pre{white-space:pre-wrap;background:#15151b;padding:6px;border:1px solid #2a2a33;max-height:200px;overflow:auto}
</style></head><body>
<div id="tabs">
  <button id="tab-play" class="act" onclick="showTab('play')">Play</button>
  <button id="tab-traces" onclick="showTab('traces')">Traces</button>
</div>

<div id="play" class="pane act">
  <div id="main">
    <div id="message">&nbsp;</div>
    <div id="screen" class="screen" tabindex="0"></div>
    <div id="status">connecting...</div>
    <div id="hint">Click the screen, then type NetHack commands (h j k l y u b n move,
      &gt; &lt; stairs, s search, i inventory). Arrows = movement. Enter / Esc supported.</div>
    <div id="demos"></div>
  </div>
  <div id="side">
    <div id="groups"></div>
    <div id="seedrow">seed <input id="seed" value="42"></div>
    <button id="reset" class="act-btn" onclick="doReset()">Reset / Regenerate floor</button>
    <button id="recbtn" class="act-btn" onclick="toggleRec()">&#9679; Record trace</button>
    <div id="recstat"></div>
  </div>
</div>

<div id="traces" class="pane">
  <div id="t-list">loading...</div>
  <div id="t-main">
    <div id="t-status">pick a trace on the left</div>
    <input type="range" id="scrub" min="0" max="0" value="0" oninput="showTurn(+this.value)">
    <div id="t-turninfo" style="color:#888;font-size:12px"></div>
    <div id="t-msgs"></div>
    <div id="t-map" class="screen"></div>
    <div id="t-llm"></div>
  </div>
</div>

<script>
const PALETTE=['#1a1a1a','#c44','#4b4','#b83','#46c','#b5b','#5bb','#bbb',
               '#666','#f66','#6f6','#fd5','#6af','#f6f','#6ff','#fff'];
const CHARCOL={'@':'#fd5','>':'#6ff','<':'#6ff','$':'#fd5','#':'#777','.':'#556',
               '|':'#bbb','-':'#bbb','+':'#4b4'};
function esc(ch){return ch==='<'?'&lt;':(ch==='>'?'&gt;':ch);}
function colorize(rows,colors){
  let h='';
  for(let y=0;y<rows.length;y++){for(let x=0;x<rows[y].length;x++){
    let ch=rows[y][x]; if(ch===' '){h+=' ';continue;}
    let c=colors?colors[y][x]:-1; let col=(c>=0&&c<16)?PALETTE[c]:(CHARCOL[ch]||(/[a-zA-Z]/.test(ch)?'#d6d':'#aaa'));
    h+='<span style="color:'+col+'">'+esc(ch)+'</span>';
  } h+='\n';} return h;
}
async function post(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json();}
function showTab(t){
  ['play','traces'].forEach(n=>{document.getElementById(n).classList.toggle('act',n===t);
    document.getElementById('tab-'+n).classList.toggle('act',n===t);});
  if(t==='traces') loadTraceList();
  if(t==='play') document.getElementById('screen').focus();
}

/* ---------- Play ---------- */
let curTune={}, META={};
function setDirty(v){document.getElementById('reset').classList.toggle('dirty',v);}
function syncControl(name,val){const m=META[name]; if(!m)return;
  if(m.kind==='bool'){const c=document.getElementById('k_'+name); if(c)c.checked=val>=0.5;}
  else {const r=document.getElementById('k_'+name), n=document.getElementById('n_'+name);
        if(r)r.value=val; if(n)n.value=(+val).toFixed(m.kind==='int'?0:2);}}
function apply(d){
  document.getElementById('screen').innerHTML=colorize(d.map,d.colors);
  document.getElementById('message').textContent=d.message||' ';
  let s=d.status;
  document.getElementById('status').textContent='HP '+s.hp+'/'+s.max_hp+'   AC '+s.ac+'   Dlvl '+s.dlvl+'   $'+s.gold+'   XP-lvl '+s.xp_lvl+(d.done?'   [GAME OVER]':'');
  for(const k in d.tune) syncControl(k,d.tune[k]);
  setDirty(false);
  document.getElementById('recstat').textContent=d.recording?('● recording '+d.recording):'';
  document.getElementById('recbtn').classList.toggle('on',!!d.recording);
}
async function onChange(name,val){curTune[name]=val;
  if(META[name].reset) setDirty(true);
  else {const d=await post('/live',{name:name,value:val}); apply(d);}}
async function doReset(){const seed=+document.getElementById('seed').value||42;
  const d=await post('/reset',{seed:seed,tune:curTune}); apply(d); document.getElementById('screen').focus();}
async function toggleRec(){
  const on=document.getElementById('recbtn').classList.contains('on');
  const r=await post(on?'/record_stop':'/record_start',{});
  document.getElementById('recbtn').classList.toggle('on',!on);
  document.getElementById('recstat').textContent=on?('saved '+(r.name||'')+' ('+(r.turns||0)+' turns)'):('● recording '+r.name);
}
function row(m){const div=document.createElement('div'); div.className='knob';
  const rst=m.reset?' <span class="rst">&#8635;reset</span>':'';
  if(m.kind==='bool'){
    div.innerHTML='<span class="name">'+m.name+rst+'</span><label class="sw"><input type="checkbox" id="k_'+m.name+'" '+(m.default>=0.5?'checked':'')+'><span></span></label>';
    div.querySelector('input').addEventListener('change',e=>onChange(m.name,e.target.checked?1:0));
  } else {const dec=m.kind==='int'?0:2;
    div.innerHTML='<span class="name">'+m.name+rst+'</span><input type="range" id="k_'+m.name+'" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+m.default+'"><input type="number" class="num" id="n_'+m.name+'" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+(+m.default).toFixed(dec)+'">';
    const r=div.querySelector('input[type=range]'),n=div.querySelector('input.num');
    r.addEventListener('input',e=>{n.value=(+e.target.value).toFixed(dec); onChange(m.name,+e.target.value);});
    n.addEventListener('change',e=>{let v=Math.max(m.lo,Math.min(m.hi,+e.target.value)); n.value=v.toFixed(dec); r.value=v; onChange(m.name,v);});}
  if(m.note){const nt=document.createElement('span'); nt.className='note'; nt.textContent=m.note; div.appendChild(nt);} return div;}
async function build(){const cat=await(await fetch('/catalog')).json();
  cat.knobs.forEach(m=>{META[m.name]=m; curTune[m.name]=m.default;});
  const box=document.getElementById('groups');
  cat.groups.forEach(g=>{const h=document.createElement('h3'); h.textContent=g; box.appendChild(h);
    cat.knobs.filter(m=>m.group===g).forEach(m=>box.appendChild(row(m)));});}
async function buildGifs(){const list=await(await fetch('/gifs')).json(); if(!list.length)return;
  const box=document.getElementById('demos'); box.innerHTML='<h3>Knob effect demos</h3>';
  list.forEach(n=>{const w=document.createElement('div'); w.style.cssText='display:inline-block;margin:6px 10px 6px 0;vertical-align:top';
    w.innerHTML='<div style="color:#cc8;font-size:12px">'+n+'</div><img src="/gif/'+n+'">'; box.appendChild(w);});}
const KEYMAP={'ArrowUp':'k','ArrowDown':'j','ArrowLeft':'h','ArrowRight':'l','Enter':'\r','Escape':'\x1b'};
document.getElementById('screen').addEventListener('keydown',async e=>{
  let ch=KEYMAP[e.key]; if(!ch&&e.key.length===1)ch=e.key; if(!ch)return; e.preventDefault();
  apply(await post('/step',{keys:ch}));});

/* ---------- Traces ---------- */
let TURNS=[];
async function loadTraceList(){
  const list=await(await fetch('/traces')).json();
  const box=document.getElementById('t-list');
  if(!list.length){box.innerHTML='<div style="color:#888">no .ndjson traces found.<br>Record one in the Play tab.</div>'; return;}
  box.innerHTML='<h3>Rollouts</h3>';
  list.forEach(f=>{const d=document.createElement('div'); d.className='f';
    d.textContent=f.name+'  ('+f.turns+')'; d.onclick=()=>loadTrace(f.path); box.appendChild(d);});
}
async function loadTrace(path){
  const r=await(await fetch('/trace?path='+encodeURIComponent(path))).json();
  TURNS=r.turns||[];
  const sc=document.getElementById('scrub'); sc.max=Math.max(0,TURNS.length-1); sc.value=0;
  showTurn(0);
}
function showTurn(i){
  if(!TURNS.length)return; const t=TURNS[i]||TURNS[0]; const s=t.status||{};
  document.getElementById('t-status').textContent='HP '+(s.hp??'?')+'/'+(s.max_hp??'?')+'   Dlvl '+(s.dlvl??'?')+'   reward '+(t.reward||0).toFixed(2);
  document.getElementById('t-turninfo').textContent='turn '+t.turn+'  ('+(i+1)+'/'+TURNS.length+')';
  document.getElementById('t-msgs').textContent=(t.messages||[]).join('  ');
  document.getElementById('t-map').innerHTML=colorize(t.raw_grid||[],null);
  let llm=''; if(t.user) llm+='<div class="lbl">user</div><pre>'+t.user.replace(/</g,'&lt;')+'</pre>';
  if(t.assistant) llm+='<div class="lbl">assistant</div><pre>'+t.assistant.replace(/</g,'&lt;')+'</pre>';
  if(t.tool_calls&&t.tool_calls.length) llm+='<div class="lbl">tool_calls</div><pre>'+JSON.stringify(t.tool_calls,null,1).replace(/</g,'&lt;')+'</pre>';
  document.getElementById('t-llm').innerHTML=llm;
}

(async()=>{await build(); await buildGifs(); await doReset();})();
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    print(f"NetHack console on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
