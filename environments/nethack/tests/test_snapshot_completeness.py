"""Differential snapshot-completeness regression test.

Guards the fix for the per-env-state snapshot leaks (fork commit e7197b4):

  * CRASH: nle_pline_state held an arena pointer (`you_buf`) but lived on the
    libc heap, so it escaped the snapshot. After a restore rewound the arena
    that pointer dangled and the next pline wrote a message over a reused arena
    slot (a live monster), SIGSEGV'ing in combat.
  * DIVERGENCE: ~20 other per-env `*_state` structs plus the rl mirror's cached
    inventory_ / WIN_MESSAGE last_msg were likewise uncaptured, so a restore
    left the previous branch's state in place and the observation diverged.

INVARIANT (snapshot completeness): from a snapshot H, replaying a FIXED action
line must yield the SAME observation trace no matter how many divergent
(reseeded, random) branches were restored-and-explored from H in between. Any
difference means state leaked through the restore. A regression also tends to
SIGSEGV mid-run, which fails the test by killing the run.

Kept modest (a few seeds x ~30 rounds) for CI; the fix was validated far wider
(40 seeds x 30 rounds, 0 crashes / 0 divergence).
"""
import hashlib
import random

import pytest

from nethack_core import EngineEnv

_ACT = [ord(c) for c in "hjklyubn"] * 3 + [
    ord("s"), ord(","), ord("."), ord("F"), ord(">"),
]


def _digest(obs):
    h = hashlib.blake2b(digest_size=16)
    for name in ("chars", "colors", "glyphs", "message", "blstats",
                 "inv_strs", "inv_letters", "inv_glyphs"):
        v = getattr(obs, name, None)
        if v is not None:
            h.update(bytes(memoryview(v).tobytes()))
    return h.hexdigest()


def _det_replay(env, handle, actions):
    env.restore(handle)
    trace = []
    for a in actions:
        obs, done, _ = env.step(a)
        trace.append((_digest(obs), done))
        if done:
            break
    return trace


def _divergent_branch(env, handle, rng, steps):
    env.restore(handle)
    env.engine.reseed(core=rng.randint(1, 10 ** 6), disp=rng.randint(1, 10 ** 6))
    for _ in range(steps):
        _, done, _ = env.step(rng.choice(_ACT))
        if done:
            break


@pytest.mark.parametrize("seed", [1, 4, 7, 18])
def test_snapshot_complete_under_divergent_branches(seed):
    rng = random.Random(seed)
    env = EngineEnv()
    env.seed(seed)
    env.reset()
    # Tough hero + a deep level jump: exercises combat (the crash path) and the
    # multi-level / inventory state most prone to leaking through a restore.
    try:
        env.modify(hp=5000, max_hp=5000, goto_depth=rng.randint(2, 6))
    except Exception:
        pass

    try:
        for _rnd in range(30):
            for _ in range(rng.randint(2, 8)):
                _, done, _ = env.step(rng.choice(_ACT))
                if done:
                    break
            if env.done:
                env.seed(seed + 1000 + _rnd)
                env.reset()
                try:
                    env.modify(hp=5000, max_hp=5000,
                               goto_depth=rng.randint(2, 6))
                except Exception:
                    pass
                continue

            handle = env.snapshot()
            fixed = [rng.choice(_ACT) for _ in range(rng.randint(6, 14))]
            try:
                ref = _det_replay(env, handle, fixed)
                for _k in range(rng.randint(2, 5)):
                    _divergent_branch(env, handle, rng, rng.randint(3, 12))
                    got = _det_replay(env, handle, fixed)
                    assert got == ref, (
                        f"snapshot incomplete: replay diverged after a branch "
                        f"(seed={seed}, round={_rnd})"
                    )
            finally:
                env.free_snapshot(handle)
    finally:
        env.close()
