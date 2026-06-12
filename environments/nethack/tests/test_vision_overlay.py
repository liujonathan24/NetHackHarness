"""
Tests for the reveal_map knob as a *render-time observation overlay* rather
than a permanent mutation of the hero's remembered map.

The fork engine fills any still-unknown map cell from the actual level terrain
(``back_to_glyph``) directly into the emitted observation in
``NetHackRL::fill_obs`` -- never touching ``gbuf`` / ``levl[][].seenv`` / calling
``newsym``. That makes the knobs:

  * reversible: turning the knob back to its default instantly re-hides the
    previously-shown terrain on the next emitted obs (the old behavior could
    never un-reveal, because the terrain had been written into hero memory);
  * side-effect-free: a reveal-on/reveal-off cycle leaves game state -- and the
    remembered map -- byte-identical to a run that never touched the knob.

``step(18)`` is ctrl-R (redraw): it re-emits the observation without advancing
game time, so it applies the current knob value to the existing frame.
"""

from __future__ import annotations

from nethack_core.engine_env import EngineEnv


def _visible(env) -> int:
    return int((env.engine.chars != ord(" ")).sum())


def test_reveal_map_is_reversible():
    """reveal_map on expands the obs; turning it back off restores the base."""
    env = EngineEnv()
    env.seed(42, 42)
    env.reset()
    base = _visible(env)

    env.set_tune(reveal_map=1.0)
    env.step(18)  # ctrl-R redraw: re-emit obs with the overlay applied
    on = _visible(env)

    env.set_tune(reveal_map=0.0)
    env.step(18)  # re-emit obs with overlay disabled
    off = _visible(env)
    env.close()

    assert on > base + 50, f"reveal_map=1 should reveal much more (base={base}, on={on})"
    # The whole point of the overlay: turning it back off un-reveals instantly.
    assert off < on - 50, f"reveal_map=0 failed to un-reveal (on={on}, off={off})"
    assert off == base, f"off should return to the base obs (base={base}, off={off})"


def _wall_count(env) -> int:
    """Count wall glyphs ('-' and '|') in the emitted map obs."""
    chars = env.engine.chars
    return int(((chars == ord("-")) | (chars == ord("|"))).sum())


def test_reveal_map_reveals_walls():
    """reveal_map=1 reveals the level's walls (the bug we fixed: reveal_map is
    now the single 'show whole map incl. walls + live monsters' knob).

    The base obs after a few steps shows only the walls the hero has explored;
    reveal_map=1 + a ctrl-R redraw fills in the rest of the floor's walls, so the
    '-'/'|' count jumps substantially (observed ~32 -> ~201).
    """
    env = EngineEnv()
    env.seed(42, 42)
    env.reset()
    for _ in range(3):
        env.step(ord("l"))  # move east to explore a little
    base_walls = _wall_count(env)

    env.set_tune(reveal_map=1.0)
    env.step(18)  # ctrl-R redraw: re-emit obs with the overlay applied
    on_walls = _wall_count(env)
    env.close()

    assert on_walls > base_walls * 2, (
        f"reveal_map=1 should reveal substantially more walls "
        f"(base={base_walls}, on={on_walls})"
    )


def test_reveal_does_not_leak_into_game_state():
    """A reveal-on/reveal-off cycle must not pollute the remembered map.

    Control run: never set reveal_map, take a movement step.
    Test run: reveal_map=1, step, reveal_map=0, step -- the same movement.
    The remembered terrain (visible-cell count) must match the control exactly;
    if reveal had written into gbuf, the test run would show extra cells.
    """
    move = ord("l")  # move east; triggers a vision recompute

    control = EngineEnv()
    control.seed(42, 42)
    control.reset()
    control.step(move)
    control_count = _visible(control)
    control.close()

    leaky = EngineEnv()
    leaky.seed(42, 42)
    leaky.reset()
    leaky.set_tune(reveal_map=1.0)
    leaky.step(move)
    leaky.set_tune(reveal_map=0.0)
    leaky.step(move)
    leaky_count = _visible(leaky)
    leaky.close()

    # The control took one move; the leaky run took the same first move plus a
    # second identical move. To compare apples to apples, replay the control's
    # second move too.
    control2 = EngineEnv()
    control2.seed(42, 42)
    control2.reset()
    control2.step(move)
    control2.step(move)
    control2_count = _visible(control2)
    control2.close()

    assert leaky_count == control2_count, (
        "reveal-on/off polluted the remembered map: "
        f"leaky={leaky_count} vs control={control2_count}"
    )
    # Sanity: the control actually explored something.
    assert control_count > 0
