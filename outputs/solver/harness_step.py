#!/usr/bin/env python3
import os, sys, json, argparse
ROOT="/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/.claude/worktrees/ch-curriculum-primitives"
sys.path.insert(0,ROOT); sys.path.insert(0,ROOT+"/environments/nethack")
os.environ["NLE_LIB_PATH"]="/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/third_party/NetHack/src/build/libnethack.so"
GD="/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/.claude/worktrees/ch-curriculum-primitives/outputs/solver/games"
def gd(n): d=f"{GD}/{n}"; os.makedirs(d,exist_ok=True); return d
def replay(cfg):
    from nethack_core.curriculum_primitives_env import CurriculumPrimitivesEnv
    from nethack_core.observations import shape as shape_observation
    from nethack_harness.tools.skills import bootstrap_character
    from nethack_harness.tools.code_mode import run_user_code
    from nethack_core.map_model import build_map_model
    env=CurriculumPrimitivesEnv(max_episode_steps=100000); env.nav_mode=cfg["mode"]
    env.seed(core=cfg["seed"],disp=cfg["seed"]); obs,meta=env.reset(); ch=bootstrap_character(env)
    if cfg.get("start_deep"):
        # Mirror the real DoD3->Gehennom jump: cross-branch goto + grant the
        # invocation kit + apply the stat upgrade.
        env._engine.goto_abs(env._geh_dnum, env._deep_lo - env._geh_start + 1)
        env._engine.grant_invocation_kit()
        obs=env.modify(**env._sample_upgrade())
        if hasattr(env,"on_invocation_level") and env.on_invocation_level(obs):
            obs=env._engine.seat_on_invocation_square(adjacent=True); env._was_on_invocation=True
    last={}; term=trunc=False
    for i,code in enumerate(cfg["turns"]):
        so=shape_observation(obs,ch); cm=run_user_code(code,env,so,raw_obs=obs)
        if getattr(cm,"pre_executed",False):
            obs=cm.final_obs if cm.final_obs is not None else env.last_observation; term=cm.pre_terminated; trunc=cm.pre_truncated
        else:
            def _has_more():
                tc=env.last_observation[env.observation_keys.index('tty_chars')]
                import numpy as _np
                return any(b"--More--" in bytes(int(c) for c in row) for row in _np.asarray(tc)[:3])
            for a in cm.actions_taken:
                # Drain pending --More-- pages first (mirrors the real harness flush
                # loop) so raw-key actions aren't eaten by a prompt.
                for _ in range(8):
                    if not _has_more(): break
                    obs,r,term,trunc,info=env.step(13)
                    if term or trunc: break
                if term or trunc: break
                obs,r,term,trunc,info=env.step(a)
                if term or trunc: break
        last={"turn":i,"stdout":cm.stdout,"error":cm.error,"term":term,"trunc":trunc}
        if term or trunc: break
    so=shape_observation(obs,ch); m=build_map_model(obs); st=so.status
    grid="\n".join(f"{y:2d} {row}" for y,row in enumerate(m.rows))
    cf=env.curriculum_floor(obs) if hasattr(env,'curriculum_floor') else st.get('depth')
    inv=[getattr(it,"description","") for it in (so.inventory or [])]
    ritual=None
    if hasattr(env,"on_invocation_level") and env.on_invocation_level(obs):
        sq=env.invocation_square(obs)
        ritual={"sq":sq}
    return last,{"cf":cf,"dlvl":st.get("depth"),"pos":(st.get("x"),st.get("y")),
                 "hp":f"{st.get('hitpoints')}/{st.get('max_hitpoints')}","under":getattr(so,'under_player',None),
                 "inv":inv,"ritual":ritual,"term":term,"trunc":trunc},grid
def show(last,s,grid,mode):
    print(f"[{mode}] curriculum_floor={s['cf']} dlvl={s['dlvl']} pos={s['pos']} hp={s['hp']} under={s['under']} terminated={s['term']}")
    if last:
        if last['stdout']: print(last['stdout'].rstrip())
        if last['error']: print("ERROR:",last['error'])
    print("INVENTORY:", "; ".join(s['inv']) or "(empty)")
    if s.get("ritual"):
        sq=s["ritual"]["sq"]
        print("*** INVOCATION LEVEL — RITUAL READY ***")
        print(f"  No down-staircase exists here. You carry the lit Candelabrum, charged Bell of Opening, and Book of the Dead,")
        print(f"  and you start ONE tile from the vibrating square at ({sq[0]},{sq[1]}). To open the way to Moloch's Sanctum:")
        print(f"    1) nh.move_to({sq[0]},{sq[1]})        # step onto the vibrating square")
        print(f"    2) nh.apply('bell')          # ring the Bell of Opening")
        print(f"    3) nh.read('Book of the Dead')  # begin the multi-turn recitation")
        print(f"    4) nh.search()  # x2-3, pass turns until 'stairwell leading down' appears")
        print(f"    5) nh.press_down()           # descend to the Sanctum (floor 6)")
    print("--- MAP (rows[y][x]; @=you >=downstair <=up #=corridor .=floor |-=wall +=door letters=monsters) ---"); print(grid)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("--game",default="g"); ap.add_argument("--seed",type=int,default=19); ap.add_argument("--mode",default="step_count"); ap.add_argument("--start-deep",dest="start_deep",action="store_true"); a=ap.parse_args()
    f=f"{gd(a.game)}/cfg.json"
    if a.cmd=="reset": cfg={"seed":a.seed,"mode":a.mode,"turns":[],"start_deep":a.start_deep}; json.dump(cfg,open(f,"w"))
    else:
        cfg=json.load(open(f))
        if a.cmd=="step": cfg["turns"].append(sys.stdin.read()); json.dump(cfg,open(f,"w"))
    last,s,grid=replay(cfg); show(last,s,grid,cfg["mode"]); print(f"[turn {len(cfg['turns'])} played; game={a.game}]")
main()
