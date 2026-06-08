"""Task 4: NetHackInterface env wrapper — typed step via skill dispatch + raw.

Drives a real NetHackCoreEnv (slow, that's fine). Asserts reset() yields an
Observation, a typed Action steps via the skill registry, and a RawAction
steps via env.step(int)."""
from __future__ import annotations

from nethack_interface import NetHackInterface, Observation, Action, RawAction


def test_reset_and_step(make_core_env):
    iface = NetHackInterface(make_core_env())
    obs = iface.reset()
    assert isinstance(obs, Observation)

    obs2, reward, done, info = iface.step(Action("search"))
    assert isinstance(obs2, Observation)
    assert isinstance(reward, float)
    assert isinstance(done, bool)
    assert isinstance(info, dict)

    obs3, *_ = iface.step(RawAction(0))  # raw escape hatch steps too
    assert isinstance(obs3, Observation)
