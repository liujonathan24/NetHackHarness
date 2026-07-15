"""End-to-end + unit test for the invocation ritual (floor 6 / Moloch's Sanctum).

Verifies: grant_invocation_kit puts the 3 identified, primed artifacts in the
pack; invocation_pos reveals the vibrating square; and the honest ritual
(move_to square -> apply bell -> read book -> press_down) reaches dlvl 50.
Also a negative check: reading the book without ringing the bell fails.
"""
import os, sys, numpy as np
ROOT = "/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/.claude/worktrees/ch-curriculum-primitives"
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + "/environments/nethack")
os.environ["NLE_LIB_PATH"] = "/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness/third_party/NetHack/src/build/libnethack.so"
from nethack_core.curriculum_primitives_env import CurriculumPrimitivesEnv
from nethack_core.observations import shape as shape_observation
from nethack_harness.tools.skills import bootstrap_character, registry, _current_chars_and_player
from nethack_core.observations import BLSTATS_IDX
import nle.nethack as NH
_D = BLSTATS_IDX["depth"]

def raw(e): return e._engine.engine.to_core_observation()
def depth(e): return int(raw(e).blstats[_D])
def msg(e):
    m = np.asarray(e.last_observation[e.observation_keys.index('message')])
    return bytes(m[m != 0]).decode('latin1')
def inv(e):
    so = shape_observation(raw(e), "Val-hum-neu-fem")
    return [getattr(it, "description", "") for it in (so.inventory or [])]
def run_skill(e, name, **kw):
    so = shape_observation(raw(e), "Val-hum-neu-fem")
    res = registry.call(name, e, so, **kw)
    for a in res.actions:
        e.step(a)
    return res.feedback

def main():
    e = CurriculumPrimitivesEnv(max_episode_steps=300000); e.nav_mode = "step_count"
    e.seed(core=19, disp=19); obs, meta = e.reset(); ch = bootstrap_character(e)

    # --- Simulate the DoD3->Geh48 jump: goto_abs + grant (as step() does) ---
    e._engine.goto_abs(e._geh_dnum, 48 - e._geh_start + 1)
    e._engine.grant_invocation_kit()
    items = inv(e)
    print("KIT inventory:", items)
    has = lambda k: any(k in d.lower() for d in items)
    assert has("candelabrum of invocation") and has("bell of opening") and has("book of the dead"), "kit not identified/present"
    assert any("7 candles" in d and "lit" in d for d in items), "candelabrum not primed (7 candles + lit)"
    print("UNIT: kit granted, identified, primed  OK")
    assert e.invocation_square(raw(e)) is None, "square should be None on dlvl 48"

    # --- Descend to the Invocation level (dlvl 49) ---
    e._engine.goto_abs(e._geh_dnum, 49 - e._geh_start + 1)
    for _ in range(3): e.step(13)
    assert e.on_invocation_level(raw(e)), "should be on invocation level"
    sq = e.invocation_square(raw(e))
    print("Invocation square:", sq, " depth:", depth(e))
    assert sq is not None
    # candelabrum still lit after the jump?
    assert any("lit" in d for d in inv(e)), "candelabrum went out after jump"
    print("UNIT: candelabrum still lit on dlvl 49  OK")

    # --- NEGATIVE: read the book on the square WITHOUT ringing the bell ---
    run_skill(e, "move_to", x=sq[0], y=sq[1], max_steps=300)
    _, pos = _current_chars_and_player(e)
    print("moved to", pos, "(target", sq, ")")
    assert pos == sq, f"did not reach the vibrating square: at {pos}, want {sq}"
    run_skill(e, "read", item="Book of the Dead")
    print("NEG read msg:", msg(e))
    assert depth(e) == 49 and e._engine.engine.hero_on_stair() != 1, "no-bell read must NOT open a stair"
    print("NEGATIVE: book-without-bell did not open a stair  OK")

    # --- HONEST RITUAL: ring bell, then read book ---
    fb = run_skill(e, "apply", item="bell")
    print("apply bell fb:", fb, "| msg:", msg(e))
    run_skill(e, "read", item="Book of the Dead")
    print("read book msg:", msg(e))
    on_stair = e._engine.engine.hero_on_stair()
    print("hero_on_stair after ritual:", on_stair, " depth:", depth(e))
    assert on_stair == 1, "ritual did not create a down-stair under the hero"
    print("RITUAL: down-staircase opened under the hero  OK")

    # --- Descend to the Sanctum (floor 6) ---
    run_skill(e, "press_down")
    for _ in range(3): e.step(13)
    d = depth(e); f = e.curriculum_floor(raw(e))
    print("after press_down: depth", d, " curriculum_floor", f)
    assert d == 50 and f == 6, f"expected dlvl50/floor6, got dlvl{d}/floor{f}"
    print("\n>>> SUCCESS: reached Moloch's Sanctum (dlvl 50 = curriculum floor 6) via the honest ritual")

if __name__ == "__main__":
    main()
