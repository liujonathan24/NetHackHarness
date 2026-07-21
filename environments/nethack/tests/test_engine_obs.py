from nethack_core import _engine
from nethack_core import CoreObservation


def test_binding_builds_core_observation():
    env = _engine.RawEngine()
    env.start(core=1, disp=1)
    co = env.to_core_observation()
    assert isinstance(co, CoreObservation)
    assert co.tty_chars.shape == (24, 80) and co.tty_chars.dtype.name == "uint8"
    assert co.glyphs.shape == (21, 79) and co.glyphs.dtype.name == "int16"
    assert co.chars.shape == (21, 79)
    assert co.colors.shape == (21, 79)
    assert co.message.shape == (256,)
    assert co.inv_strs.shape == (55, 80)
    assert co.inv_letters.shape == (55,)
    assert co.inv_glyphs.shape == (55,)
    assert co.blstats.shape[0] in (26, 27)
    assert co.tty_cursor.shape == (2,)
    env.end()


def test_core_observation_is_a_snapshot_copy():
    # to_core_observation must copy, not view: stepping after snapshot must
    # not mutate the previously captured observation.
    env = _engine.RawEngine()
    env.start(core=7, disp=7)
    co1 = env.to_core_observation()
    before = co1.tty_chars.copy()
    env.step(0)
    env.step(0)
    # co1 must be unchanged by subsequent steps
    import numpy as np
    assert np.array_equal(co1.tty_chars, before)
    env.end()
