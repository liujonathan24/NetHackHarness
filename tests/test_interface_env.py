"""NetHackInterface env wrapper (raw substrate) — reset yields an Observation,
RawAction steps via env.step(int).

Drives a real NetHackCoreEnv (slow, that's fine). The typed ``Action``/skill
path is the Hub's concern and is tested there
(``NetHack-hub`` ``tests/test_typed_interface.py``)."""
from __future__ import annotations

from nethack_interface import NetHackInterface, Observation, RawAction


def test_reset_and_raw_step(make_core_env):
    iface = NetHackInterface(make_core_env())
    obs = iface.reset()
    assert isinstance(obs, Observation)

    obs2, reward, done, info = iface.step(RawAction(0))  # raw escape hatch
    assert isinstance(obs2, Observation)
    assert isinstance(reward, float)
    assert isinstance(done, bool)
    assert isinstance(info, dict)

    obs3, *_ = iface.step(1)  # bare int also steps
    assert isinstance(obs3, Observation)
