import os

from nethack_core import _engine


def test_start_step_end_runs():
    env = _engine.RawEngine()
    obs = env.start(core=42, disp=42)
    assert obs.tty_chars.shape == (24, 80)
    assert obs.glyphs.shape == (21, 79)
    assert obs.blstats.shape == (27,)
    obs2 = env.step(0)            # action index 0
    assert obs2.tty_chars.shape == (24, 80)
    env.end()


def test_two_instances_sequential():
    # one engine per process is fine; ensure a fresh start after end works
    env = _engine.RawEngine()
    env.start(core=1, disp=1)
    env.step(0)
    env.end()


def test_start_without_end_does_not_leak():
    """Calling start() a second time without end() must clean up the first game."""
    env = _engine.RawEngine()
    env.start(core=1, disp=1)
    first_hackdir = env._hackdir

    # Re-enter start() without calling end() first.
    env.start(core=2, disp=2)

    # The first temp hackdir must be gone — no leak.
    assert not os.path.exists(first_hackdir), (
        f"First hackdir was not cleaned up on re-entry: {first_hackdir}"
    )

    # Engine must still be functional after re-entry.
    env.step(0)
    second_hackdir = env._hackdir
    env.end()

    # The second hackdir must also be gone after end().
    assert not os.path.exists(second_hackdir), (
        f"Second hackdir was not cleaned up after end(): {second_hackdir}"
    )
