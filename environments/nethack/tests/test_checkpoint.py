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
