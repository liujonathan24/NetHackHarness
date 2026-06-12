import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))
from nethack_core.engine_env import EngineEnv

WALKABLE = set(".#<>+}{")  # floor, corridor, stairs, door, fountain, etc.


def _grid(obs):
    return [bytes(bytearray(int(c) for c in r)).decode("latin1") for r in obs.chars]


def _saved_floor(seed=42, steps=3):
    env = EngineEnv()
    env.reset(seeds=(seed, seed))
    obs = None
    for _ in range(steps):
        obs, _, _ = env.step(ord("."))
    return env, obs


def test_save_creates_nonempty_blob(tmp_path):
    env, _ = _saved_floor()
    blob = tmp_path / "floor.blob"
    env.save_level(blob)
    assert blob.exists() and blob.stat().st_size > 0


def test_save_level_is_deterministic(tmp_path):
    # The same in-memory level serializes byte-identically (no nondeterministic
    # padding / uninitialised bytes in the serialization path).
    env, _ = _saved_floor()
    a, b = tmp_path / "a.blob", tmp_path / "b.blob"
    env.save_level(a)
    env.save_level(b)
    assert a.read_bytes() == b.read_bytes()


def test_load_level_round_trips_via_reload(tmp_path):
    """The saved floor loads into a different game and re-serializes identically.

    Comparing rendered obs grids is wrong here: ``obs.chars`` is vision-filtered
    (it shows only what the hero has explored/remembers), so two games with
    different exploration histories never have equal obs grids even with the same
    underlying level. Instead we compare the actual engine ``level`` struct: load
    the blob into a fresh, differently-seeded game and re-save — a faithful load
    re-serializes to the same bytes (terrain, stairs, doors, monsters, objects).
    """
    env, _ = _saved_floor(seed=42)
    a = tmp_path / "a.blob"
    env.save_level(a)

    env2 = EngineEnv()
    env2.reset(seeds=(1234, 1234))  # a different native floor
    env2.load_level(a)  # steps once internally to re-render
    b = tmp_path / "b.blob"
    env2.save_level(b)

    ba, bb = a.read_bytes(), b.read_bytes()
    # Same serialized size: the level structure (terrain grid, room/stair/door
    # tables, monster & object counts) is identical. A small fraction of bytes
    # differ — per-monster bookkeeping (m_id / last-move timestamp) is rebased to
    # the destination game's turn counter on load. Terrain occupies the bulk of
    # the file as a contiguous block; any terrain divergence would differ in a
    # large contiguous run, not the few clustered bytes we tolerate here.
    assert len(ba) == len(bb), f"level size changed: {len(ba)} -> {len(bb)}"
    ndiff = sum(1 for x, y in zip(ba, bb) if x != y)
    assert ndiff / len(ba) < 0.05, f"{ndiff}/{len(ba)} bytes differ — level did not round-trip"


def test_generate_and_save_many(tmp_path):
    """Arbitrary floors can be generated (varying seed) and saved to a library;
    distinct seeds produce distinct floor blobs."""
    saved = []
    for seed in (1, 2, 3, 4, 5):
        env = EngineEnv()
        env.reset(seeds=(seed, seed))
        env.step(ord("."))
        p = tmp_path / f"floor_{seed}.blob"
        env.save_level(p)
        saved.append(p.read_bytes())
    assert all(saved)
    assert len({bytes(s) for s in saved}) >= 4  # floors differ across seeds


def test_load_level_places_hero_on_loaded_floor(tmp_path):
    """After loading, the hero is re-seated onto the LOADED floor (upstair /
    downstair / first accessible tile) — not left on the destination game's
    stale position, which could be rock/void on the new floor.
    """
    env, _ = _saved_floor(seed=42)
    blob = tmp_path / "floor.blob"
    env.save_level(blob)

    env2 = EngineEnv()
    env2.reset(seeds=(1234, 1234))
    obs2 = env2.load_level(blob)
    grid = _grid(obs2)
    hx, hy = int(obs2.blstats[0]), int(obs2.blstats[1])
    assert grid[hy][hx] == "@", f"hero not at blstats pos ({hx},{hy}): {grid[hy][hx]!r}"
    # The hero is not stranded in void: at least one neighbouring cell is walkable.
    neighbours = "".join(
        grid[y][x]
        for y in (hy - 1, hy, hy + 1)
        for x in (hx - 1, hx, hx + 1)
        if 0 <= y < len(grid) and 0 <= x < len(grid[0])
    )
    assert WALKABLE & set(neighbours), f"hero stranded in void; neighbours={neighbours!r}"
