"""Multi-level snapshot completeness (GATE B / Task 12b).

Off-current dungeon levels are persisted by NetHack to disk as "<lock>.<n>"
files in the hackdir (savelev/getlev); only the level in the arena is captured
by the in-memory snapshot. nle_fr_snapshot now also bundles those level files
into the handle and nle_fr_restore rewrites them, so a snapshot spans the whole
dungeon: travelling back to a level left before the snapshot reads the
snapshot-time level, not a later mutation.

These tests exercise the bundling machinery directly (the new code): a snapshot
captures the "<lock>.*" level files, restore reverts post-snapshot changes to
them, and the static template files (<role>.lev / *.des) are NOT bundled. The
in-game read path (getlev reading those files) is stock NetHack.
"""
import os

from nethack_core import _engine

# Dynamic dungeon-level files are "<s_lock>.<ledger>"; s_lock is empty in this
# build, so they are ".<digits>" (e.g. ".50") in the hackdir.
_LOCK_PREFIX = "."


def _write(path, data: bytes):
    with open(path, "wb") as f:
        f.write(data)


def _read(path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def test_snapshot_bundles_and_restores_level_files():
    """A post-snapshot change to a level file is reverted on restore."""
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    hd = env._hackdir

    # Simulate an off-current dungeon level on disk.
    lvl = os.path.join(hd, _LOCK_PREFIX + "7")
    _write(lvl, b"ORIGINAL-LEVEL-7-CONTENTS")

    h = env.snapshot()  # bundles 1lock.7

    # Mutate the level file after the snapshot (as revisiting + leaving would).
    _write(lvl, b"MUTATED-AFTER-SNAPSHOT-DIFFERENT-LENGTH")
    assert _read(lvl) != b"ORIGINAL-LEVEL-7-CONTENTS"

    env.restore(h)

    assert _read(lvl) == b"ORIGINAL-LEVEL-7-CONTENTS", (
        "restore did not revert the off-current level file from the snapshot"
    )
    env.free_snapshot(h)
    env.end()


def test_static_template_files_are_not_bundled():
    """Only <lock>.<n> files are captured; <role>.lev / *.des templates are not
    (so restore leaves them untouched and the bundle stays small)."""
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    hd = env._hackdir

    template = os.path.join(hd, "Val-strt.lev")  # a static template that exists
    assert os.path.exists(template), "expected prebuilt template in hackdir"

    h = env.snapshot()
    _write(template, b"TOUCHED-TEMPLATE")
    env.restore(h)

    # restore must NOT have reverted the (non-level) template file.
    assert _read(template) == b"TOUCHED-TEMPLATE", (
        "restore unexpectedly reverted a static template file"
    )
    env.free_snapshot(h)
    env.end()


def test_levelfile_created_after_snapshot_is_left_alone():
    """A level file that did not exist at snapshot time is not deleted on
    restore (NetHack regenerates unvisited levels rather than reading them)."""
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    hd = env._hackdir

    h = env.snapshot()  # no 1lock.42 at this point
    newfile = os.path.join(hd, _LOCK_PREFIX + "42")
    _write(newfile, b"CREATED-AFTER-SNAPSHOT")

    env.restore(h)

    assert os.path.exists(newfile) and _read(newfile) == b"CREATED-AFTER-SNAPSHOT", (
        "restore should leave post-snapshot level files untouched"
    )
    env.free_snapshot(h)
    env.end()
