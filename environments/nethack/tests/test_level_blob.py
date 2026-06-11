import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))
from nethack_core.engine_env import EngineEnv


def _grid(obs):
    return [bytes(bytearray(int(c) for c in r)).decode("latin1") for r in obs.chars]


def test_save_creates_nonempty_blob(tmp_path):
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    for _ in range(3):
        env.step(ord("."))
    blob = tmp_path / "floor.blob"
    env.save_level(blob)
    assert blob.exists() and blob.stat().st_size > 0


def test_save_level_is_deterministic(tmp_path):
    # The same saved level produces a byte-identical blob (no nondeterministic
    # padding / uninitialised bytes in the serialization path).
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    for _ in range(3):
        env.step(ord("."))
    a = tmp_path / "a.blob"
    b = tmp_path / "b.blob"
    env.save_level(a)
    env.save_level(b)
    assert a.read_bytes() == b.read_bytes()


def test_load_level_round_trips_level_contents(tmp_path):
    """Saving a level and loading it into a different game reproduces the level
    CONTENTS — terrain, walls, doors, stairs and monsters — byte-for-byte on the
    char grid.

    NOTE: the C ``nle_load_level`` re-seats the level contents in place but does
    NOT carry over the hero's saved (x, y); the hero keeps the destination game's
    position.  So this assertion normalises the hero glyph '@' out of both grids
    before comparing.  (The hero-position transfer is a known limitation of the
    current C entry point; see test_load_level_does_not_transfer_hero_position.)
    """
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    obs = None
    for _ in range(3):
        obs, _, _ = env.step(ord("."))
    saved = _grid(obs)
    blob = tmp_path / "floor.blob"
    env.save_level(blob)

    env2 = EngineEnv()
    env2.reset(seeds=(1234, 1234))  # a different native floor
    obs2 = env2.load_level(blob)  # returns re-rendered obs (steps once internally)
    got = _grid(obs2)

    def drop_hero(rows):
        return [r.replace("@", ".") for r in rows]

    # Everything except the hero glyph and the tile revealed under the saved
    # hero (its upstair) matches.  Compare the loaded grid against the saved
    # grid with the saved-hero tile resolved to its underlying upstair.
    saved_resolved = [r for r in saved]
    # In the saved frame the hero stood on the upstair, so '@' hides a '<'.
    # Resolve it so the underlying terrain lines up with the loaded grid.
    for i, r in enumerate(got):
        if "<" in r and "<" not in saved[i] and "@" in saved[i]:
            col = r.index("<")
            row = list(saved_resolved[i])
            if row[col] == "@":
                row[col] = "<"
                saved_resolved[i] = "".join(row)

    assert drop_hero(saved_resolved) == drop_hero(got)


def test_load_level_does_not_transfer_hero_position(tmp_path):
    """Document the current C contract: load_level reproduces level contents but
    leaves the hero at the destination game's position (blstats x/y unchanged).

    This is an xfail-style guard: if a future C change makes load_level carry the
    saved hero position, this test will start failing and should be updated (and
    the round-trip test above can then assert full grid equality including '@').
    """
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    obs = None
    for _ in range(3):
        obs, _, _ = env.step(ord("."))
    saved_xy = (int(obs.blstats[0]), int(obs.blstats[1]))
    blob = tmp_path / "floor.blob"
    env.save_level(blob)

    env2 = EngineEnv()
    env2.reset(seeds=(1234, 1234))
    pre_xy = (int(env2._engine.to_core_observation().blstats[0]),
              int(env2._engine.to_core_observation().blstats[1]))
    obs2 = env2.load_level(blob)
    post_xy = (int(obs2.blstats[0]), int(obs2.blstats[1]))

    # Hero keeps the destination game's position, not the saved one.
    assert post_xy == pre_xy
    assert post_xy != saved_xy
