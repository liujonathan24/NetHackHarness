import json, sys, re
from pathlib import Path
from nethack_core import NetHackCoreEnv
from nethack_core import shape as shape_observation
from nethack_interface import NetHackInterface
from nethack_harness.tools.skills import registry
from nethack_harness.helpers import _capture_user_content
from tools.rollout_view.live_server import LiveStepper
try:
    from nethack import _scrub_intro_banner
except Exception:
    _scrub_intro_banner = lambda obs: obs

def run(variant, seed, turns, write=True):
    e = NetHackCoreEnv(task_name="NetHackScore-v0"); e.seed(core=seed, disp=seed)
    itf = NetHackInterface(e); stepper = LiveStepper(itf, variant=variant)
    char = itf._character
    def refresh(raw):
        if raw is not None:
            try: _scrub_intro_banner(raw)
            except Exception: pass
            itf._raw = raw; itf._structured = shape_observation(raw, char)
    refresh(itf._raw)                       # scrub the initial frame too
    stepper.history[0] = stepper._build_turn()
    for _ in range(turns):
        res = registry.call("explore_and_descend", itf._env, itf._structured,
                            max_floors=1, max_game_steps=400)
        refresh(getattr(res, "final_obs", None) or itf._raw)
        stepper._turn += 1; stepper._current = stepper._build_turn()
        stepper.history.append(stepper._current)
    def d(t):
        s=t.get("rendered_user_content") or ""; s=s if isinstance(s,str) else " ".join(map(str,s))
        m=re.findall(r"Dlvl:?\s*(\d+)", s); return int(m[-1]) if m else None
    ds=[x for x in (d(t) for t in stepper.history) if x]
    mx=max(ds) if ds else 0
    if write:
        out=Path("environments/nethack/outputs/web_play")/f"{variant}_seed{seed}"; out.mkdir(parents=True,exist_ok=True)
        rid=f"{variant}_seed{seed}"; lines=[]
        for t in stepper.history:
            c=_capture_user_content(t.get("rendered_user_content"), out, run_id=rid, turn=t["turn"])
            lines.append(json.dumps({**t,"rendered_user_content":c,"variant":variant}))
        (out/f"{rid}.ndjson").write_text("\n".join(lines))
    return mx, ds

if __name__=="__main__":
    if sys.argv[1]=="scan":
        for s in range(1,21):
            mx,ds=run("B1",s,14,write=False)
            print(f"seed {s}: max_dlvl={mx}  {ds[:6]}")
    else:
        mx,ds=run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
        print(f"WROTE B1_seed{sys.argv[2]} max_dlvl={mx} Dlvl={ds}")
