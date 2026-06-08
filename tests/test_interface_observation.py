import numpy as np, nle.nethack as N
from nethack_interface.observation import Observation, observation_spec


class _Raw:
    def __init__(self):
        g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32); g[5,10] = N.GLYPH_MON_OFF+20
        self.glyphs=g; self.tty_chars=np.full((24,80),32,np.uint8)
        b=np.zeros((27,),np.int64); b[0]=40; b[1]=10; self.blstats=b


def test_observation_from_raw_carries_map_and_status():
    obs = Observation.from_raw(_Raw(), status={"hitpoints": 12, "depth": 1},
                               inventory=[], character={"role": "Val"})
    assert obs.player == (40, 10)
    assert any(e.kind == "monster" for e in obs.entities)
    assert obs.status["hitpoints"] == 12


def test_observation_spec_declares_fields():
    spec = observation_spec()
    assert {"player", "entities", "grid", "status", "inventory", "character"} <= set(spec)
