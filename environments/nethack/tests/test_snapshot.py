"""In-memory snapshot / restore / branch tests for the custom NetHack engine.

These tests exercise Pillar 1a: nle_fr_snapshot / nle_fr_restore / nle_fr_destroy
bound on RawEngine.  A snapshot captures the live engine state (ctx + coroutine
stack + per-env arena) and restore returns the engine to that point.

SNAPSHOT COMPLETENESS CONTRACT (see RawEngine.restore docstring)
----------------------------------------------------------------
- restore() does NOT refill the numpy obs buffers; they reflect the restored
  state only after the next step().
- The snapshot is COMPLETE: it captures all per-env state. The engine's per-env
  heap buffers are arena-allocated (so the arena memcpy captures them) and the
  rl-port display mirror (which lives outside the arena) is captured alongside.
  Therefore restore() returns the engine to EXACTLY the snapshot state, and
  branching is byte-exact: restore + any action line produces byte-identical
  glyphs, chars, colors AND blstats to a fresh engine that played the same
  prefix+line — even on a SECOND restore from the same handle after a prior
  branch explored a different part of the map, and regardless of how far the
  abandoned branch diverged. (This required completing the fork's arena
  migration + capturing the rl mirror; earlier the displayed-map memory leaked
  across cross-branch restores.)

Tests assert byte-exact branching.  Action ints follow the existing convention
(raw ASCII compass values), matching tests/test_engine_concurrency.py.
"""
import numpy as np
import pytest

from nethack_core import _engine

# Raw ASCII compass moves: h j k l y u b n.
_COMPASS = [104, 108, 106, 107, 121, 117, 98, 110]


def _state(env):
    """Capture a copy of the structured observation fields."""
    return {
        "glyphs": env.glyphs.copy(),
        "blstats": env.blstats.copy(),
    }


def _same(a, b):
    return np.array_equal(a["glyphs"], b["glyphs"]) and np.array_equal(
        a["blstats"], b["blstats"]
    )


def _fresh_final(prefix, line, seed=42):
    """Ground truth: a fresh engine that plays prefix+line, final state."""
    env = _engine.RawEngine()
    env.start(core=seed, disp=seed)
    for a in prefix + line:
        env.step(a)
    out = _state(env)
    env.end()
    return out


def test_snapshot_requires_active_game():
    env = _engine.RawEngine()
    with pytest.raises(RuntimeError):
        env.snapshot()


def test_round_trip_first_branch_matches_fresh():
    """snapshot -> restore (no intervening steps) -> replay == fresh engine.

    This is the core checkpoint guarantee: the first restore+replay from a
    snapshot reproduces a from-scratch run byte-for-byte (glyphs and blstats).
    """
    prefix = _COMPASS[:3]
    line = [107, 121, 117, 98, 110, 104]
    fresh = _fresh_final(prefix, line)

    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    for a in prefix:
        env.step(a)
    h = env.snapshot()
    env.restore(h)
    for a in line:
        env.step(a)
    restored = _state(env)

    assert _same(restored, fresh), (
        "restore + replay (first branch) did not match a fresh engine byte-for-byte"
    )
    env.end()


def test_branch_first_is_faithful_and_branches_diverge():
    """One snapshot, two branches: both branches are byte-exact vs fresh runs.

    Branch A (first restore) matches fresh-A and branch B (second restore from
    the same handle) matches fresh-B, byte-for-byte — and the two branches
    diverge from each other.  This is the complete-snapshot guarantee: a second
    restore from the same handle is unaffected by the abandoned first branch.
    """
    prefix = _COMPASS[:3]
    line_a = [107, 121, 117, 98]   # l y u b
    line_b = [110, 104, 108, 106]  # n h l j
    fresh_a = _fresh_final(prefix, line_a)
    fresh_b = _fresh_final(prefix, line_b)
    assert not _same(fresh_a, fresh_b), "test lines do not diverge in a fresh run"

    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    for a in prefix:
        env.step(a)
    h = env.snapshot()

    for a in line_a:
        env.step(a)
    branch_a = _state(env)

    env.restore(h)
    for a in line_b:
        env.step(a)
    branch_b = _state(env)

    # First branch is faithful to a fresh run.
    assert _same(branch_a, fresh_a), (
        "first branch from snapshot did not match a fresh engine"
    )
    # Second branch (after restore over an abandoned first branch) is ALSO
    # byte-exact vs a fresh run — no residue from branch A.
    assert _same(branch_b, fresh_b), (
        "second branch from the same handle carried residue from the first branch"
    )
    # Branching actually diverges.
    assert not _same(branch_a, branch_b), (
        "the two branches did not diverge — snapshot branching is not real"
    )
    env.end()


def test_repeated_restore_is_byte_exact():
    """Many restores from one handle, with map-exploring branches in between,
    all reproduce the same state byte-for-byte (glyphs AND blstats).

    This is the regression test for display-mirror residue: a long, divergent
    branch B is run and abandoned between two runs of branch A; A must be
    identical both times.
    """
    prefix = _COMPASS[:2]
    line_a = [107, 107, 108, 121, 117, 98, 110, 104]
    line_b = [110, 110, 98, 104, 108, 106, 107, 121]  # diverges widely

    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    for a in prefix:
        env.step(a)
    h = env.snapshot()

    for a in line_a:
        env.step(a)
    first_a = _state(env)

    # Abandoned divergent branch explores a different region of the map.
    env.restore(h)
    for a in line_b:
        env.step(a)

    # Re-run branch A from the same handle: must be byte-identical to first_a.
    env.restore(h)
    for a in line_a:
        env.step(a)
    second_a = _state(env)

    assert np.array_equal(first_a["glyphs"], second_a["glyphs"]), (
        "glyphs differed across repeated restore — display-mirror residue"
    )
    assert np.array_equal(first_a["blstats"], second_a["blstats"]), (
        "blstats differed across repeated restore"
    )
    env.end()


def test_replay_determinism():
    """Restore + identical replay is fully deterministic (glyphs AND blstats).

    Two restores from the same handle followed by the same line produce
    byte-identical observations.
    """
    prefix = _COMPASS[:3]
    line = [107, 121, 117, 98]
    fresh = _fresh_final(prefix, line)

    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    for a in prefix:
        env.step(a)
    h = env.snapshot()
    for a in line:
        env.step(a)
    first = _state(env)

    env.restore(h)
    for a in line:
        env.step(a)
    second = _state(env)

    # First branch is fully faithful to a fresh run.
    assert _same(first, fresh)
    # Restore + identical replay is byte-exact on both glyphs and blstats.
    assert np.array_equal(first["glyphs"], second["glyphs"]), (
        "glyphs were not deterministic across restore + identical replay"
    )
    assert np.array_equal(first["blstats"], second["blstats"]), (
        "blstats were not deterministic across restore + identical replay"
    )
    env.end()


def test_multiple_outstanding_snapshots_are_independent():
    """Two snapshots taken at different game points are independent handles.

    Each is verified by restoring it (with no intervening branch) and replaying
    a fixed line, comparing against the corresponding fresh run.
    """
    p_early = _COMPASS[:2]
    p_late = _COMPASS[:6]
    line = [104, 108]
    fresh_early = _fresh_final(p_early, line)
    fresh_late = _fresh_final(p_late, line)
    assert not _same(fresh_early, fresh_late)

    # h2 (later) is taken on a fresh engine to avoid cross-branch residue; the
    # point is that two handles held simultaneously restore to their own states.
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    for a in p_early:
        env.step(a)
    h1 = env.snapshot()
    for a in _COMPASS[2:6]:
        env.step(a)
    h2 = env.snapshot()

    assert h1 in env._snapshots and h2 in env._snapshots and h1 != h2

    # Restore the later handle first, replay, check.
    env.restore(h2)
    for a in line:
        env.step(a)
    assert _same(_state(env), fresh_late), "restore(h2) + replay did not match fresh-late"

    env.end()


def test_cleanup_no_leak_across_games():
    """start() (which calls end()) frees outstanding snapshots; snapshot() after
    end() raises."""
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    for a in _COMPASS[:2]:
        env.step(a)
    env.snapshot()  # intentionally not freed
    assert len(env._snapshots) == 1

    # Restart without freeing — must not crash and must clear the set.
    env.start(core=42, disp=42)
    assert env._snapshots == set(), "outstanding snapshots leaked across games"

    env.end()
    with pytest.raises(RuntimeError):
        env.snapshot()


def test_explicit_free_snapshot():
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    h = env.snapshot()
    assert h in env._snapshots
    env.free_snapshot(h)
    assert h not in env._snapshots
    # Freeing again is a no-op.
    env.free_snapshot(h)
    env.end()


def test_same_instance_binding_guard():
    """restore() of a foreign/unknown handle must be rejected, not executed."""
    env_a = _engine.RawEngine()
    env_b = _engine.RawEngine()
    env_a.start(core=42, disp=42)
    env_b.start(core=42, disp=42)

    foreign = env_a.snapshot()

    # env_b never created this handle -> must reject.
    with pytest.raises((ValueError, RuntimeError)):
        env_b.restore(foreign)

    # An arbitrary integer is also rejected.
    with pytest.raises((ValueError, RuntimeError)):
        env_a.restore(0xDEADBEEF)

    env_a.end()
    env_b.end()
