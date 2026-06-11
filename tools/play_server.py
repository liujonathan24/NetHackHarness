"""Play NetHack in the browser, on top of the fork engine.

A tiny Flask app that drives EngineEnv: it renders the real NetHack map, takes
keystrokes as game commands, and exposes the difficulty/map-generation knobs as
controls grouped into Vision / Stat-based / Dungeon & spawns. Live knobs apply on
the next step; reset knobs (room_density, monster_difficulty) apply on Reset,
which regenerates the level. Headless-friendly — run on the node and port-forward:

    python tools/play_server.py            # serves on 0.0.0.0:8080
    # from your laptop:  ssh -L 8080:localhost:8080 <node>   then open localhost:8080
"""

from __future__ import annotations

import argparse
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))

from flask import Flask, jsonify, request  # noqa: E402

from nethack_core.engine_env import EngineEnv  # noqa: E402

app = Flask(__name__)
STATE: dict = {"env": None, "seed": 42, "tune": {}}

# Knob UI metadata: group, kind (bool|int|scale), reset (needs regenerate to
# take effect), range (lo, hi, step), default, note.
_GROUPS = ["Vision", "Stat-based", "Dungeon & spawns"]
_META = {
    "vision_radius":            dict(group="Vision", kind="int",  reset=False, lo=0, hi=15, step=1, default=0, note="0 = vanilla; only matters in the dark"),
    "fog_of_war":               dict(group="Vision", kind="bool", reset=False, default=1, note="off = reveal whole floor"),
    "reveal_map":               dict(group="Vision", kind="bool", reset=False, default=0, note="on = reveal whole floor"),

    "dmg_to_player_scale":      dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=4, step=0.25, default=1),
    "dmg_by_player_scale":      dict(group="Stat-based", kind="scale", reset=False, lo=0, hi=4, step=0.25, default=1),
    "player_hp_scale":          dict(group="Stat-based", kind="scale", reset=False, lo=0.25, hi=4, step=0.25, default=1, note="applies to HP gained on level-up"),
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


def _payload(obs) -> dict:
    # Render the clean structured map (21x79) + message + status rather than
    # tty_chars (which this binding overlays with startup-banner residue).
    rows = ["".join(chr(int(c)) if 32 <= int(c) < 127 else " " for c in r) for r in obs.chars]
    color_rows = [[int(c) for c in r] for r in obs.colors]
    msg = bytes(int(c) for c in obs.message).split(b"\x00")[0].decode("latin1", "replace")
    bl = [int(x) for x in obs.blstats]
    status = {
        "hp": bl[10], "max_hp": bl[11], "ac": bl[16],
        "dlvl": bl[12], "gold": bl[13], "xp_lvl": bl[18] if len(bl) > 18 else 0,
    }
    return {"map": rows, "colors": color_rows, "message": msg, "status": status,
            "tune": _env().get_tune(), "done": bool(obs is not None and _env().done)}


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
    for _ in range(2):  # settle vision/reveal
        obs, _, _ = _env().step(ord("."))
    return jsonify(_payload(obs))


@app.route("/step", methods=["POST"])
def step():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys", "")
    if STATE["env"] is None:
        return jsonify({"error": "call /reset first"}), 400
    obs = None
    for ch in keys:
        obs, _done, _info = STATE["env"].step(ord(ch))
    if obs is None:
        return jsonify({"error": "no keys"}), 400
    return jsonify(_payload(obs))


@app.route("/set_tune", methods=["POST"])
def set_tune():
    data = request.get_json(silent=True) or {}
    name, value = data.get("name"), float(data.get("value"))
    if STATE["env"] is not None:
        STATE["env"].set_tune(**{name: value})
    STATE["tune"][name] = value
    return jsonify({"ok": True})


_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>NetHack - play</title>
<style>
  body{background:#0c0c10;color:#ddd;font-family:monospace;margin:0;display:flex}
  #main{padding:12px}
  #screen{font-size:15px;line-height:1.15;white-space:pre;letter-spacing:0;outline:1px solid #222}
  #message{height:18px;color:#fff;margin-bottom:4px}
  #status{height:18px;margin-top:6px;color:#eee}
  #hint{color:#888;margin-top:8px;font-size:12px}
  #side{width:360px;padding:12px;border-left:1px solid #333;background:#111;overflow-y:auto;max-height:100vh}
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
  button#reset{background:#284;color:#fff;border:0;padding:9px 12px;cursor:pointer;width:100%;font-size:14px}
  button#reset.dirty{background:#a63}
</style></head><body>
<div id="main">
  <div id="message">&nbsp;</div>
  <div id="screen" tabindex="0"></div>
  <div id="status">connecting...</div>
  <div id="hint">Click the screen, then type NetHack commands (h j k l y u b n move,
   &gt; &lt; stairs, s search, i inventory). Arrows = movement. Enter / Esc supported.</div>
</div>
<div id="side">
  <div id="groups"></div>
  <div id="seedrow">seed <input id="seed" value="42"></div>
  <button id="reset" onclick="doReset()">Reset / Regenerate floor</button>
</div>
<script>
const PALETTE=['#1a1a1a','#c44','#4b4','#b83','#46c','#b5b','#5bb','#bbb',
               '#666','#f66','#6f6','#fd5','#6af','#f6f','#6ff','#fff'];
function colorize(rows,colors){
  let html='';
  for(let y=0;y<rows.length;y++){
    for(let x=0;x<rows[y].length;x++){
      let ch=rows[y][x]; if(ch===' '){html+=' ';continue;}
      let c=colors[y][x]; let col=(c>=0&&c<16)?PALETTE[c]:'#bbb';
      html+='<span style="color:'+col+'">'+ch.replace('<','&lt;').replace('>','&gt;')+'</span>';
    }
    html+='\n';
  }
  return html;
}
let curTune={}, META={};
function setDirty(v){document.getElementById('reset').classList.toggle('dirty',v);}
function syncControl(name,val){
  const m=META[name]; if(!m)return;
  if(m.kind==='bool'){const c=document.getElementById('k_'+name); if(c)c.checked=val>=0.5;}
  else {const r=document.getElementById('k_'+name), n=document.getElementById('n_'+name);
        if(r)r.value=val; if(n)n.value=(+val).toFixed(m.kind==='int'?0:2);}
}
function apply(d){
  document.getElementById('screen').innerHTML=colorize(d.map,d.colors);
  document.getElementById('message').textContent=d.message||' ';
  let s=d.status;
  document.getElementById('status').textContent=
    'HP '+s.hp+'/'+s.max_hp+'   AC '+s.ac+'   Dlvl '+s.dlvl+'   $'+s.gold+'   XP-lvl '+s.xp_lvl+(d.done?'   [GAME OVER]':'');
  for(const k in d.tune){ syncControl(k,d.tune[k]); }
  setDirty(false);
}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json();}
async function onChange(name,val){
  curTune[name]=val;
  if(META[name].reset){ setDirty(true); }                 // staged; applies on Reset
  else { await post('/set_tune',{name:name,value:val}); }  // live; effect next step
}
async function doReset(){
  const seed=+document.getElementById('seed').value||42;
  const d=await post('/reset',{seed:seed,tune:curTune}); apply(d);
  document.getElementById('screen').focus();
}
function row(m){
  const div=document.createElement('div'); div.className='knob';
  const rst=m.reset?' <span class="rst">&#8635;reset</span>':'';
  if(m.kind==='bool'){
    div.innerHTML='<span class="name">'+m.name+rst+'</span>'+
      '<label class="sw"><input type="checkbox" id="k_'+m.name+'" '+(m.default>=0.5?'checked':'')+'><span></span></label>';
    div.querySelector('input').addEventListener('change',e=>onChange(m.name, e.target.checked?1:0));
  } else {
    const dec=m.kind==='int'?0:2;
    div.innerHTML='<span class="name">'+m.name+rst+'</span>'+
      '<input type="range" id="k_'+m.name+'" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+m.default+'">'+
      '<input type="number" class="num" id="n_'+m.name+'" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+(+m.default).toFixed(dec)+'">';
    const r=div.querySelector('input[type=range]'), n=div.querySelector('input.num');
    r.addEventListener('input',e=>{n.value=(+e.target.value).toFixed(dec); onChange(m.name,+e.target.value);});
    n.addEventListener('change',e=>{let v=+e.target.value; v=Math.max(m.lo,Math.min(m.hi,v)); n.value=v.toFixed(dec); r.value=v; onChange(m.name,v);});
  }
  if(m.note){const nt=document.createElement('span'); nt.className='note'; nt.textContent=m.note; div.appendChild(nt);}
  return div;
}
async function build(){
  const cat=await (await fetch('/catalog')).json();
  cat.knobs.forEach(m=>{META[m.name]=m; curTune[m.name]=m.default;});
  const box=document.getElementById('groups');
  cat.groups.forEach(g=>{
    const h=document.createElement('h3'); h.textContent=g; box.appendChild(h);
    cat.knobs.filter(m=>m.group===g).forEach(m=>box.appendChild(row(m)));
  });
}
const KEYMAP={'ArrowUp':'k','ArrowDown':'j','ArrowLeft':'h','ArrowRight':'l','Enter':'\r','Escape':'\x1b'};
document.getElementById('screen').addEventListener('keydown',async e=>{
  let ch=KEYMAP[e.key]; if(!ch&&e.key.length===1)ch=e.key;
  if(!ch)return; e.preventDefault();
  const d=await post('/step',{keys:ch}); apply(d);
});
(async()=>{await build(); await doReset();})();
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    print(f"NetHack play server on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
