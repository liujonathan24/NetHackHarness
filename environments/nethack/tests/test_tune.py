"""Difficulty-knob (nle_tune_t) tests for the custom NetHack engine.

The knob catalog is defined once in the fork via the NLE_TUNE_FIELDS X-macro;
the binding discovers it generically (nle_tune_count/name + nle_get_tune as a
flat double[]), so get_tune()/set_tune() need no per-knob code.

v1 wires Layer 3 "live" (per-step) knobs.  hunger_rate_scale is the end-to-end
effect test: hunger ticks every step, so the effect is deterministic without
needing organic combat.  Knob defaults are vanilla (all scales 1.0), guarded at
each read-site by `!= 1.0` so the default path stays byte-identical to vanilla
(covered separately by tests/test_golden_parity.py).
"""
import pytest

from nethack_core import _engine

# u.uhunger (raw nutrition counter) is surfaced at internal[7] by the rl port.
_UHUNGER = 7


def _uhunger_after(scale, nsteps=150):
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    if scale is not None:
        env.set_tune(hunger_rate_scale=scale)
    acts = [104, 108, 106, 107, 121, 117, 98, 110]
    for i in range(nsteps):
        env.step(acts[i % len(acts)])
    h = int(env._internal[_UHUNGER])
    env.end()
    return h


def test_catalog_is_discoverable():
    env = _engine.RawEngine()
    catalog = env.tune_catalog()
    # v1 = the 12 Layer-3 live knobs.
    assert "dmg_to_player_scale" in catalog
    assert "hunger_rate_scale" in catalog
    assert "monster_difficulty_scale" in catalog
    assert len(catalog) == env._lib.nle_tune_count()
    # Names are unique and stable.
    assert len(set(catalog)) == len(catalog)


def test_defaults_are_vanilla():
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    tune = env.get_tune()
    # Every scale knob defaults to 1.0; the two non-scale knobs to their sentinels.
    for name, value in tune.items():
        if name in ("vision_radius", "reveal_map"):
            assert value == 0.0, f"{name} default expected 0.0, got {value}"
        else:
            assert value == 1.0, f"{name} default expected 1.0, got {value}"
    env.end()


def test_set_get_roundtrip():
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    env.set_tune(dmg_to_player_scale=0.0, hunger_rate_scale=2.5, reveal_map=1.0)
    tune = env.get_tune()
    assert tune["dmg_to_player_scale"] == 0.0
    assert tune["hunger_rate_scale"] == 2.5
    assert tune["reveal_map"] == 1.0
    # Untouched knobs keep their defaults.
    assert tune["xp_gain_scale"] == 1.0
    env.end()


def test_unknown_knob_raises():
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    with pytest.raises(KeyError):
        env.set_tune(does_not_exist=1.0)
    env.end()


def test_tune_requires_active_game():
    env = _engine.RawEngine()
    with pytest.raises(RuntimeError):
        env.get_tune()
    with pytest.raises(RuntimeError):
        env.set_tune(hunger_rate_scale=2.0)


def test_hunger_rate_scale_effect():
    """hunger_rate_scale linearly scales per-turn nutrition consumption."""
    start = _uhunger_after(0.0, nsteps=0)  # uhunger at game start, no steps
    none_set = _uhunger_after(None)        # not setting tune == default
    default = _uhunger_after(1.0)
    off = _uhunger_after(0.0)
    triple = _uhunger_after(3.0)

    spent_default = start - default
    spent_triple = start - triple

    # scale=0 -> no nutrition consumed at all.
    assert off == start, f"hunger_rate_scale=0 should not consume nutrition (got {off} vs start {start})"
    # default consumes a positive amount, and equals not setting the knob.
    assert spent_default > 0
    assert default == none_set, "explicit 1.0 differs from leaving the knob unset"
    # 3x consumes ~3x the default amount (exact: rate scaled per turn).
    assert spent_triple == 3 * spent_default, (
        f"expected 3x consumption {3 * spent_default}, got {spent_triple}"
    )


def _visible_cells(nsteps=5, **knobs):
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    if knobs:
        env.set_tune(**knobs)
    for _ in range(nsteps):
        env.step(106)  # j (move; triggers vision recalc)
    n = int((env.chars != ord(" ")).sum())
    env.end()
    return n


def test_reveal_map_reveals_the_level():
    """reveal_map expands the observed level.

    Default obs shows only the explored area; reveal_map=1 reveals the whole
    level's terrain (the single 'show whole map incl. walls + live monsters'
    knob now that fog_of_war is gone).
    """
    base = _visible_cells()
    revealed = _visible_cells(reveal_map=1.0)
    assert revealed > base, "reveal_map did not reveal additional cells"


def test_all_knobs_are_settable_and_safe():
    """Every catalog knob accepts a non-default value and the engine keeps
    stepping without crashing (smoke coverage for knobs whose effect needs a
    combat/exploration scenario to observe deterministically)."""
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    stress = {
        "dmg_to_player_scale": 0.0,
        "dmg_by_player_scale": 5.0,
        "player_hp_scale": 3.0,
        "hp_regen_scale": 4.0,
        "vision_radius": 3.0,
        "reveal_map": 1.0,
        "hunger_rate_scale": 2.0,
        "ongoing_spawn_scale": 4.0,
        "monster_difficulty_scale": 6.0,
        "monster_speed_scale": 2.0,
        "xp_gain_scale": 10.0,
        "room_density": 0.5,
        # generation knobs (level-replay) — include the 0.0 edge (guarded in C)
        "mob_spawn": 3.0,
        "trap_density": 0.0,
        "locked_door": 2.0,
        "corridor_connectivity": 0.0,
        "room_size": 2.0,
    }
    # Stress every knob in the catalog (fails loudly if a knob is missing here).
    assert set(stress) == set(env.tune_catalog())
    env.set_tune(**stress)
    for i in range(60):
        env.step([104, 108, 106, 107][i % 4])
    assert env.get_tune()["xp_gain_scale"] == 10.0
    env.end()


def test_tune_is_captured_by_snapshot():
    """Knobs live on the engine ctx, so a snapshot captures them: changing a
    knob after snapshotting and then restoring reverts it to the snapshot value.
    """
    env = _engine.RawEngine()
    env.start(core=42, disp=42)
    env.set_tune(hunger_rate_scale=2.0)
    h = env.snapshot()

    env.set_tune(hunger_rate_scale=5.0)
    assert env.get_tune()["hunger_rate_scale"] == 5.0

    env.restore(h)
    assert env.get_tune()["hunger_rate_scale"] == 2.0, (
        "snapshot/restore did not capture the difficulty knobs"
    )
    env.end()
