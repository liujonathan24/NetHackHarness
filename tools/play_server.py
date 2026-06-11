"""Play NetHack in the browser, on top of the fork engine.

A tiny Flask app that drives EngineEnv: it renders the real NetHack tty screen,
takes keystrokes as game commands, and exposes the difficulty/map-generation
knobs as sliders with a Reset button that regenerates the level (so you can see
room_density etc. reshape the floor). Headless-friendly — run it on the node and
port-forward:

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

# Per-knob slider ranges (lo, hi, step); default for any unlisted knob.
_RANGES = {
    "reveal_map": (0.0, 1.0, 1.0),
    "fog_of_war": (0.0, 1.0, 1.0),
    "vision_radius": (0.0, 15.0, 1.0),
    "room_density": (0.0, 1.5, 0.05),
}
_DEFAULT_RANGE = (0.0, 3.0, 0.25)


def _env() -> EngineEnv:
    if STATE["env"] is None:
        STATE["env"] = EngineEnv()
    return STATE["env"]


def _payload(obs) -> dict:
    # Render the clean structured map (21x79) + message + status rather than
    # tty_chars (which this binding overlays with startup-banner residue).
    chars = obs.chars
    colors = obs.colors
    rows = ["".join(chr(int(c)) if 32 <= int(c) < 127 else " " for c in r) for r in chars]
    color_rows = [[int(c) for c in r] for r in colors]
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
        lo, hi, step = _RANGES.get(name, _DEFAULT_RANGE)
        out.append({"name": name, "lo": lo, "hi": hi, "step": step})
    return jsonify(out)


@app.route("/reset", methods=["POST"])
def reset():
    data = request.get_json(silent=True) or {}
    STATE["seed"] = int(data.get("seed", STATE["seed"]))
    STATE["tune"] = {k: float(v) for k, v in (data.get("tune") or {}).items()}
    obs, _ = _env().reset(seeds=(STATE["seed"], STATE["seed"]), tune=dict(STATE["tune"]))
    # settle vision/reveal
    for _ in range(2):
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


_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>NetHack — play</title>
<style>
  body{background:#0c0c10;color:#ddd;font-family:monospace;margin:0;display:flex}
  #main{padding:12px}
  #screen{font-size:15px;line-height:1.15;white-space:pre;letter-spacing:0}
  #message{height:18px;color:#fff;margin-bottom:4px}
  #status{height:18px;margin-top:6px;color:#eee}
  #hint{color:#888;margin-top:8px;font-size:12px}
  #side{width:330px;padding:12px;border-left:1px solid #333;background:#111}
  .knob{margin:6px 0}
  .knob label{display:inline-block;width:160px;color:#cc8}
  .knob .val{color:#fd0;width:44px;display:inline-block;text-align:right}
  input[type=range]{width:100%}
  #seedrow{margin:10px 0}
  #seed{width:80px;background:#222;color:#fff;border:1px solid #444}
  button{background:#284;color:#fff;border:0;padding:8px 12px;cursor:pointer;width:100%;font-size:14px}
  h3{color:#9c9;margin:4px 0 8px}
</style></head><body>
<div id="main">
  <div id="message">&nbsp;</div>
  <div id="screen" tabindex="0"></div>
  <div id="status">connecting…</div>
  <div id="hint">Click the screen, then type NetHack commands (h j k l y u b n move, &gt; &lt; stairs,
   s search, i inventory, , pickup). Arrows = movement. Enter / Esc supported.</div>
</div>
<div id="side">
  <h3>Difficulty / generation knobs</h3>
  <div id="knobs"></div>
  <div id="seedrow">seed <input id="seed" value="42"></div>
  <button onclick="doReset()">Reset / Regenerate floor</button>
</div>
<script>
const PALETTE=['#1a1a1a','#c44','#4b4','#b83','#46c','#b5b','#5bb','#bbb',
               '#666','#f66','#6f6','#fd5','#6af','#f6f','#6ff','#fff'];
function colorize(rows, colors){
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
function apply(d){
  document.getElementById('screen').innerHTML=colorize(d.map,d.colors);
  document.getElementById('message').textContent=d.message||' ';
  let s=d.status;
  document.getElementById('status').textContent=
    `HP ${s.hp}/${s.max_hp}   AC ${s.ac}   Dlvl ${s.dlvl}   $${s.gold}   XP-lvl ${s.xp_lvl}`+(d.done?'   [GAME OVER]':'');
  // sync slider values to engine state
  for(const k in d.tune){ const el=document.getElementById('k_'+k); if(el){el.value=d.tune[k]; const v=document.getElementById('v_'+k); if(v)v.textContent=(+d.tune[k]).toFixed(2);} }
}
let curTune={};
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json();}
async function doReset(){
  const seed=+document.getElementById('seed').value||42;
  const d=await post('/reset',{seed,tune:curTune}); apply(d);
  document.getElementById('screen').focus();
}
async function buildKnobs(){
  const cat=await (await fetch('/catalog')).json();
  const box=document.getElementById('knobs');
  cat.forEach(k=>{
    const div=document.createElement('div'); div.className='knob';
    const init=(k.name==='reveal_map')?1.0:((k.name==='vision_radius')?0:1.0);
    curTune[k.name]=init;
    div.innerHTML=`<label>${k.name}</label><span class="val" id="v_${k.name}">${init.toFixed(2)}</span>
      <input type="range" id="k_${k.name}" min="${k.lo}" max="${k.hi}" step="${k.step}" value="${init}">`;
    box.appendChild(div);
    const inp=div.querySelector('input');
    inp.addEventListener('input',async e=>{
      const v=+e.target.value; curTune[k.name]=v;
      document.getElementById('v_'+k.name).textContent=v.toFixed(2);
      await post('/set_tune',{name:k.name,value:v}); // live knobs apply next step
    });
  });
}
const KEYMAP={'ArrowUp':'k','ArrowDown':'j','ArrowLeft':'h','ArrowRight':'l','Enter':'\r','Escape':'\x1b'};
document.getElementById('screen').addEventListener('keydown',async e=>{
  let ch=KEYMAP[e.key]; if(!ch&&e.key.length===1)ch=e.key;
  if(!ch)return; e.preventDefault();
  const d=await post('/step',{keys:ch}); apply(d);
});
(async()=>{await buildKnobs(); await doReset();})();
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
