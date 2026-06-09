import nle.nethack as N
from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import shape as shape_observation
from nethack_harness.tools.skills import registry


def _floor_id(env):
    bl = env.underlying.unwrapped.last_observation[
        env.underlying.unwrapped._observation_keys.index("blstats")]
    return (int(bl[23]), int(bl[24]))  # DNUM, DLEVEL


def test_search_count_persists_per_floor_across_calls():
    e = NetHackCoreEnv(task_name="NetHackScore-v0"); e.seed(core=6, disp=6); out = e.reset()
    fid = _floor_id(e)
    # two calls on the same starting floor: search_count for that floor accumulates
    registry.call("explore_and_descend", e, shape_observation(out[0], {}), max_game_steps=120)
    sc = getattr(e.underlying.unwrapped, "_explore_search_count", {})
    keys_floor1 = [k for k in sc if k[0] == fid]
    # the persisted dict is keyed by (floor_id, x, y) — floor_id is a (dnum,dlevel) tuple
    assert all(isinstance(k[0], tuple) and len(k[0]) == 2 for k in sc), \
        "search_count must be keyed by the (dnum,dlevel) floor id, not a per-call int"
