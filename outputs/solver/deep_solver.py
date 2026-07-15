import os,sys,re,numpy as np
ROOT="/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/.claude/worktrees/ch-curriculum-primitives"
sys.path.insert(0,ROOT); sys.path.insert(0,ROOT+"/environments/nethack")
os.environ["NLE_LIB_PATH"]="/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/third_party/NetHack/src/build/libnethack.so"
from nethack_core.curriculum_primitives_env import CurriculumPrimitivesEnv
from nethack_core.observations import shape as shape_observation
from nethack_harness.tools.skills import bootstrap_character, registry, _current_chars_and_player
from nethack_harness.navigation.pathfinding import a_star, reachable_set, find_frontiers
from nethack_core.observations import BLSTATS_IDX
_DEPTH=BLSTATS_IDX["depth"]
def depth(env): return int(env._engine.engine.to_core_observation().blstats[_DEPTH])
def stepr(env,obs,ch,res):
    if getattr(res,"pre_executed",False): return res.final_obs if res.final_obs is not None else env.last_observation,res.pre_terminated,res.pre_truncated
    t=tr=False
    for a in res.actions:
        obs,r,t,tr,i=env.step(a)
        if t or tr:break
    return obs,t,tr
def dir_to(px,py,mx,my): return {(0,-1):"N",(1,-1):"NE",(1,0):"E",(1,1):"SE",(0,1):"S",(-1,1):"SW",(-1,0):"W",(-1,-1):"NW"}.get(((mx>px)-(mx<px),(my>py)-(my<py)))
def mv(env,obs,ch,x,y,ms):
    so=shape_observation(obs,ch); res=registry.call("move_to",env,so,x=x,y=y,max_steps=ms); fb=res.feedback or ""
    obs,t,tr=stepr(env,obs,ch,res)
    m=re.search(r"monster '.' at \((\d+),(\d+)\)",fb)
    if m:
        _,p=_current_chars_and_player(env); d=dir_to(p[0],p[1],int(m.group(1)),int(m.group(2)))
        if d: obs,t,tr=stepr(env,obs,ch,registry.call("attack",env,shape_observation(obs,ch),direction=d))
    return obs,t,tr
def press_down(env,obs,ch):
    return stepr(env,obs,ch,registry.call("press_down",env,shape_observation(obs,ch)))
def play(seed,calls=300):
    env=CurriculumPrimitivesEnv(max_episode_steps=200000); env.nav_mode="step_count"
    env.seed(core=seed,disp=seed); obs,meta=env.reset(); ch=bootstrap_character(env)
    # Jump to the deep segment top exactly as the curriculum's DoD3-downstair does.
    env._engine.goto_abs(env._geh_dnum, env._deep_lo-env._geh_start+1)
    obs=env.modify(**env._sample_upgrade())
    d0=depth(env); best=env.curriculum_floor(obs) or 4
    last=None; nomove=0; lastd=d0; visited=set()
    for c in range(calls):
        chars,pos=_current_chars_and_player(env); d=depth(env); f=env.curriculum_floor(obs) or best
        best=max(best,f)
        if d!=lastd: visited=set(); lastd=d; nomove=0
        if best>=6: break
        gs=[(x,y) for y in range(chars.shape[0]) for x in range(chars.shape[1]) if int(chars[y,x])==ord('>')]
        onstair = env._engine.engine.hero_on_stair()==1
        if onstair:
            obs,t,tr=press_down(env,obs,ch)
        elif gs and nomove<3:
            gs.sort(key=lambda g:abs(g[0]-pos[0])+abs(g[1]-pos[1])); obs,t,tr=mv(env,obs,ch,gs[0][0],gs[0][1],120)
        else:
            reach=reachable_set(chars,pos)
            frs=[ff for ff in find_frontiers(chars) if ff in reach and ff!=pos and ff not in visited and a_star(chars,pos,ff)]
            if frs: frs.sort(key=lambda ff:len(a_star(chars,pos,ff))); visited.add(frs[0]); obs,t,tr=mv(env,obs,ch,frs[0][0],frs[0][1],80)
            elif gs: obs,t,tr=mv(env,obs,ch,gs[0][0],gs[0][1],120)
            else:
                so=shape_observation(obs,ch); obs,t,tr=stepr(env,obs,ch,registry.call("autoexplore",env,so,max_steps=40))
        _,p2=_current_chars_and_player(env); nomove=nomove+1 if p2==last else 0; last=p2
        if t or tr or nomove>50: break
    return best, depth(env), d0
if __name__=="__main__":
    for s in [int(x) for x in (sys.argv[1:] or ["19"])]:
        b=4; dd=0; d0=0
        for run in range(4):
            try:
                bb,dep,d0=play(s); b=max(b,bb); dd=max(dd,dep)
            except Exception as e:
                print(f"seed {s} run {run} ERR {type(e).__name__}: {e}",flush=True)
            print(f"seed {s} run {run}: best_floor={b} maxdepth={dd} (start dlvl {d0})",flush=True)
            if b>=6: break
        print(f">>> seed {s}: best floor={b} (6=dlvl50)  {'REACHED 50' if b>=6 else 'stopped at floor '+str(b)}",flush=True)
