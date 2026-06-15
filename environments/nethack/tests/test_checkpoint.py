import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))
from nethack_core.engine_env import EngineEnv
from nethack_core.observations import BLSTATS_IDX


def bl(o, n):
    return int(o.blstats[BLSTATS_IDX[n]])


def test_player_blob_roundtrip(tmp_path):
    e = EngineEnv()
    e.reset(seeds=(42, 42))
    for _ in range(8):
        obs, _, _ = e.step(ord("s"))
    hp0, gold0 = bl(obs, "hitpoints"), bl(obs, "gold")
    blob = e._engine.save_player()
    # mutate then restore in place (load player only — same level still loaded)
    e.modify(hp=1, gold=9999)
    e._engine.load_player_raw(blob)
    obs2, _, _ = e.step(18)
    assert bl(obs2, "hitpoints") == hp0 and bl(obs2, "gold") == gold0


def test_checkpoint_resume(tmp_path):
    e = EngineEnv()
    e.reset(seeds=(42, 42))
    for _ in range(8):
        obs, _, _ = e.step(ord("s"))
    e.modify(gold=777)
    ck = tmp_path / "floor.ckpt"
    e.checkpoint(ck)
    # resume in a FRESH env
    e2 = EngineEnv()
    obs2 = e2.resume(ck)
    assert bl(obs2, "gold") == 777
    assert bl(obs2, "depth") == bl(obs, "depth")
    # and you can keep playing
    obs3, _, _ = e2.step(ord("."))
    assert obs3 is not None


def test_snapshot_restore_nested_prompt_winproc():
    """Restoring a snapshot taken at a NESTED window prompt used to corrupt the
    libc heap (double-free / SIGSEGV), e.g. the live Monte-Carlo checkpoint demo.

    The rl window port tracks its win-proc call stack in a libc-backed deque
    (nle_ctx_t->s_win_proc_calls), pushed/popped by a ScopedStack per window
    call. A nested prompt (yn_function -> nhgetch) yields with the deque two deep.
    nle_fr_restore swaps the coroutine stack back to the snapshot but the deque
    (outside the snapshot) keeps its shallower live depth, so the restored
    stack's pending ScopedStack dtors pop_back() past empty -> UB walks
    _M_finish into garbage -> the next push_back writes near-null and crashes.
    Fix: ScopedStack guards pop-on-empty + nle_fr_restore clears the deque.
    """
    e = EngineEnv()
    e.reset(seeds=(42, 42))
    for _ in range(3):
        e.step(ord("."))
    # Snapshot while yielded inside a nested yn prompt (deque depth 2), then
    # cancel back to the shallow command-wait state.
    snaps = []
    e.step(ord("S"))                       # "Really save? [yn]"
    snaps.append(e.snapshot())
    e.step(27)                             # ESC -> cancel
    for ch in "pray":
        e.step(ord(ch))
    e.step(13)                             # "Are you sure you want to pray? [yn]"
    snaps.append(e.snapshot())
    e.step(ord("n"))
    # Repeatedly restore the deep-prompt snapshots and redraw (ctrl-R). On the
    # buggy engine this aborts within ~80 cycles; the fix survives all of them.
    for _ in range(100):
        for s in snaps:
            e.restore(s)
            obs, _, _ = e.step(18)         # ctrl-R redraw (the crashing action)
            assert obs is not None
            e.step(27)
            e.step(ord("n"))
    for s in snaps:
        e.free_snapshot(s)
    e.close()


def test_checkpoint_resume_deep_floor(tmp_path):
    """Resuming a checkpoint taken on a DEEP floor used to SIGSEGV.

    nle_load_level stamps the saved (e.g. dlvl-5) level blob over the current
    ledger slot, which after resume()'s reset is dlvl 1. getlev()'s "is this the
    level I expect?" sanity check then fired trickery() -> pline(...), and pline
    routes through the rl window port, which yields the game coroutine
    (jump_fcontext) from the main context -> jump to a dead fcontext -> crash.
    The fix passes pid=0/lev=0 to getlev so a standalone load skips that check.
    """
    e = EngineEnv()
    e.reset(seeds=(21, 21))
    e.modify(goto_depth=5)
    obs, _, _ = e.step(ord("l"))
    assert bl(obs, "depth") == 5
    ck = tmp_path / "deep.ckpt"
    e.checkpoint(ck)
    # resume the deep-floor checkpoint in a fresh env (the crashing path)
    e2 = EngineEnv()
    obs2 = e2.resume(ck)
    assert bl(obs2, "depth") == 5  # correct level restored, not a crash
    # the map is populated (not a corrupt/empty frame) and play continues
    assert sum(1 for r in obs2.chars for c in r if 32 <= int(c) < 127 and int(c) != 32) > 50
    obs3, _, _ = e2.step(ord("."))
    assert obs3 is not None
    # repeated resume of the same deep checkpoint must stay stable
    for _ in range(5):
        o = e2.resume(ck)
        assert bl(o, "depth") == 5
