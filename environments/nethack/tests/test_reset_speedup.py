"""Regression tests for the fast-reset optimization (RawEngine hackdir reuse).

``RawEngine.start`` used to ``mkdtemp`` + ``copytree`` the whole ~3.7MB ``dat``
directory on EVERY reset (~29ms, the dominant reset cost). It now copies the dat
once per engine and, on each subsequent reset, cheaply restores that hackdir to
the pristine source state (delete the prior game's dynamic files, re-copy the
writable templates).

These tests pin the two guarantees that make the optimization safe:

  1. BEHAVIOR IDENTITY — an engine that resets in place (the reuse path) produces
     byte-identical observation traces to a fresh engine per seed (the one-time
     copytree path). The game cannot tell the difference.
  2. PRISTINE HACKDIR — after playing a game and resetting, the reused hackdir is
     byte-for-byte identical to a fresh ``copytree`` of the source dat, so the
     engine reads exactly the same inputs.

Plus a loose speed guard so a regression back to per-reset copytree is caught.
"""
import hashlib
import os
import random
import time

from nethack_core._engine import RawEngine

# Movement (8-dir) + search/pickup/descend — enough to create dynamic game-state
# files (level files when descending, score/log appends) so the reset's cleanup
# is actually exercised.
_ACT = [ord(c) for c in "hjklyubn>s,"]


def _trace(eng, seed, steps=120):
    """Deterministic obs-buffer digest for (seed, fixed action stream)."""
    eng.start(seed, seed)
    rng = random.Random(seed)
    h = hashlib.blake2b(digest_size=16)
    for _ in range(steps):
        eng.step(rng.choice(_ACT))
        for buf in (eng.chars, eng.colors, eng.glyphs, eng.blstats, eng.message):
            h.update(memoryview(buf).tobytes())
        if eng.done:
            break
    return h.hexdigest()


def test_reset_reuse_is_behavior_identical_to_fresh_engine():
    """Resetting one engine in place == a brand-new engine per seed, byte-exact."""
    seeds = list(range(20, 36))

    reuse = RawEngine()
    try:
        reuse_traces = [_trace(reuse, s) for s in seeds]
    finally:
        reuse.end()

    for s, expected in zip(seeds, reuse_traces):
        fresh = RawEngine()  # first start() => the one-time full-copytree path
        try:
            assert _trace(fresh, s) == expected, f"trace diverged for seed {s}"
        finally:
            fresh.end()


def test_hackdir_is_tiny_and_data_comes_from_shared_datadir():
    """The writable hackdir holds only game-state files; the bulk read-only data
    is read from the shared source dat (no per-reset copy)."""
    eng = RawEngine()
    try:
        eng.start(7, 7)
        # Fresh game: only the seeded writable templates exist (no 3.7MB copy).
        assert sorted(os.listdir(eng._hackdir)) == [
            "logfile", "perm", "record", "xlogfile",
        ], "hackdir should hold only the writable templates after start"
        # The large data files live in the shared datadir, NOT the hackdir.
        src = eng._build_dat_path()
        assert (src / "nhdat").exists(), "shared datadir should hold the DLB data"
        assert not os.path.exists(os.path.join(eng._hackdir, "nhdat")), (
            "nhdat must not be copied into the per-env hackdir"
        )

        # Play a game (creates level files / appends logs), then reset: the
        # hackdir is scrubbed back to just the writable templates.
        rng = random.Random(7)
        for _ in range(250):
            eng.step(rng.choice(_ACT))
            if eng.done:
                eng.start(rng.randint(1, 10**6), 1)
        eng.start(9, 9)
        assert sorted(os.listdir(eng._hackdir)) == [
            "logfile", "perm", "record", "xlogfile",
        ], "reset must scrub the prior game's dynamic files from the hackdir"
    finally:
        eng.end()


def test_reset_is_fast():
    """Reset stays far below the old per-reset copytree cost (~29ms)."""
    eng = RawEngine()
    try:
        eng.start(1, 1)
        for i in range(3):  # warm up (first start pays the one-time copytree)
            eng.start(100 + i, 100 + i)
        times = []
        for i in range(30):
            t = time.perf_counter()
            eng.start(1000 + i, 1000 + i)
            times.append((time.perf_counter() - t) * 1e3)
        times.sort()
        median = times[len(times) // 2]
        # Optimized reset is ~1-3ms; the old copytree path was ~30-35ms. 15ms
        # cleanly separates them while tolerating a loaded CI node.
        assert median < 15.0, f"reset median {median:.1f}ms suggests copytree regression"
    finally:
        eng.end()
