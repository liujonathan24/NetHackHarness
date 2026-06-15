"""The deployed env defaults to a standard NetHack game on the fork engine;
difficulty/generation knobs are opt-in overrides, not the default."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))

from nethack_core.env import NetHackCoreEnv


def _visible(obs):
    return sum(1 for r in obs.chars for c in r if 32 < int(c) < 127)


def test_default_is_standard_full_game():
    """No tier => the full ascension game ("full_nle"), not a curriculum tier."""
    import nethack as NH
    env = NH.load_environment(n_examples=2)
    row = env.dataset[0]
    assert row["info"]["tier"] == "full_nle"
    assert "Ascend" in row["prompt"][1]["content"]


def test_setup_overrides_are_stored_and_default_off():
    import nethack as NH
    base = NH.load_environment(n_examples=1)
    assert base._setup_tune is None and base._setup_modify is None and base._setup_level_blob is None
    over = NH.load_environment(n_examples=1, tune={"reveal_map": 1.0}, modify={"gold": 500})
    assert over._setup_tune == {"reveal_map": 1.0}
    assert over._setup_modify == {"gold": 500}
    # curriculum tiers remain available as an explicit override
    cur = NH.load_environment(n_examples=1, tier="corridor_explore")
    assert cur.dataset[0]["info"]["tier"] == "corridor_explore"


def test_engine_is_the_fork():
    """The env runs on our fork engine (EngineEnv), never nle."""
    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    assert env._is_native
    assert type(env._engine).__name__ == "EngineEnv"
    env.close()


def test_tune_override_changes_generation():
    """A tune knob passed to the env actually reaches the engine at reset."""
    base = NetHackCoreEnv(task_name="NetHackScore-v0"); base.seed(42, 42)
    o_base, _ = base.reset(); n_base = _visible(o_base); base.close()

    tuned = NetHackCoreEnv(task_name="NetHackScore-v0", tune={"reveal_map": 1.0}); tuned.seed(42, 42)
    o_tuned, _ = tuned.reset(); n_tuned = _visible(o_tuned); tuned.close()

    assert n_tuned > n_base  # reveal_map exposes the whole floor


def test_modify_override_pokes_state():
    """A modify field passed to the env is applied on reset."""
    from nethack_core.observations import BLSTATS_IDX
    env = NetHackCoreEnv(task_name="NetHackScore-v0", modify={"gold": 777}); env.seed(42, 42)
    obs, _ = env.reset()
    assert int(obs.blstats[BLSTATS_IDX["gold"]]) == 777
    env.close()
