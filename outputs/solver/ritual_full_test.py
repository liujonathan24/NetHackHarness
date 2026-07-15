"""Full-flow test: curriculum auto-seats the hero adjacent to the vibrating
square on arrival at the Invocation level; the agent then performs the honest
ritual (step onto the square, ring the Bell, read the Book, wait, press_down)
to reach Moloch's Sanctum (dlvl 50 = curriculum floor 6).
"""
import os, sys, numpy as np
ROOT = "/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/.claude/worktrees/ch-curriculum-primitives"
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + "/environments/nethack")
os.environ["NLE_LIB_PATH"] = "/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/third_party/NetHack/src/build/libnethack.so"
from nethack_core.curriculum_primitives_env import CurriculumPrimitivesEnv
from nethack_core.observations import shape as shape_observation
from nethack_harness.tools.skills import bootstrap_character, registry
from nethack_core.observations import BLSTATS_IDX
_D = BLSTATS_IDX["depth"]
_DOWN = ord('>')

def raw(e): return e._engine.engine.to_core_observation()
def hero(e): b = raw(e).blstats; return (int(b[0]), int(b[1]))
def depth(e): return int(raw(e).blstats[_D])
def msg(e):
    m = np.asarray(e.last_observation[e.observation_keys.index('message')]); return bytes(m[m != 0]).decode('latin1')
def tty(e): return ["".join(chr(c) for c in row) for row in np.asarray(e.last_observation[e.observation_keys.index('tty_chars')])]
def drain(e, n=6):
    for _ in range(n):
        if not any("--More--" in r for r in tty(e)[:3]): break
        e.step(13)
def run(e, name, **kw):
    for a in registry.call(name, e, shape_observation(raw(e), "Val-hum-neu-fem"), **kw).actions: e.step(a)
    drain(e)

def main(seed=19):
    e = CurriculumPrimitivesEnv(max_episode_steps=300000); e.nav_mode = "step_count"
    e.seed(core=seed, disp=seed); obs, meta = e.reset(); ch = bootstrap_character(e)
    # Simulate the DoD3->Gehennom48 boundary jump (grants the kit): reach 48.
    e._engine.goto_abs(e._geh_dnum, 48 - e._geh_start + 1)
    e._engine.grant_invocation_kit()
    for _ in range(3): e.step(13)
    # Put the hero on 48's downstair (48-maze nav is unreliable and orthogonal to
    # this test), then descend via the CURRICULUM step so auto-seat-adjacent fires.
    e._engine.engine.seat_on_stair(down=True)
    for _ in range(2): e.step(13)
    assert e._engine.engine.hero_on_stair() == 1, f"not on 48 downstair (at {hero(e)})"
    # Descend through the curriculum env.step (fires the seat-adjacent on arrival).
    e.step(13); e.step(_DOWN)
    for _ in range(3): e.step(13)
    assert depth(e) == 49 and e.on_invocation_level(raw(e)), f"expected invocation level, depth={depth(e)}"
    sq = e.invocation_square(raw(e))            # array coords
    h = hero(e)
    cheb = max(abs(h[0] - sq[0]), abs(h[1] - sq[1]))
    print(f"arrived dlvl49; hero={h} square={sq} chebyshev={cheb}")
    assert cheb == 1, f"auto-seat should be ADJACENT to the square, got chebyshev {cheb}"
    print("AUTO-SEAT: hero staged one tile from the vibrating square  OK")

    # --- Honest ritual (agent) ---
    run(e, "move_to", x=sq[0], y=sq[1], max_steps=8)   # one step onto the square
    assert hero(e) == sq, f"failed to step onto the square: at {hero(e)}, want {sq}"
    print("stepped onto the square at", sq)
    drain(e)                                          # clear step-onto-square messages
    run(e, "apply", item="bell"); print("apply bell:", msg(e))
    run(e, "read", item="Book of the Dead"); print("read book:", msg(e))
    for i in range(12):
        e.step(13); drain(e)                          # pass turns; recitation auto-continues
        if e._engine.engine.hero_on_stair() == 1:
            print(f"stairwell opened after {i+1} waits:", msg(e)); break
    assert e._engine.engine.hero_on_stair() == 1, "ritual did not open a down-stair"
    run(e, "press_down")
    for _ in range(3): e.step(13)
    d, f = depth(e), e.curriculum_floor(raw(e))
    print(f"after press_down: dlvl {d}, curriculum_floor {f}")
    assert d == 50 and f == 6, f"expected dlvl50/floor6, got dlvl{d}/floor{f}"
    print("\n>>> SUCCESS: honest ritual reached Moloch's Sanctum (dlvl 50 = floor 6)")

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 19)
