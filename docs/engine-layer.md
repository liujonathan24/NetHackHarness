# Engine layer

Reference for the custom NetHack engine that replaced the `nle` PyPI package.
The harness now drives a NetHack **fork** (the `third_party/NetHack` submodule)
through a ctypes binding. `nle` and `minihack` are no longer dependencies —
numpy/gymnasium, which used to arrive transitively via `nle`, are now direct
deps of the workspace packages.

Layers, bottom to top:

- `nethack_core/_engine.py` — `RawEngine`, the raw ctypes binding over
  `libnethack.so` (`nle_start`/`nle_step`/`nle_end`, snapshot, level blobs,
  tune knobs, state mutation).
- `nethack_core/engine_env.py` — `EngineEnv`, the deterministic env over
  `RawEngine` with snapshot/branch, save/load, modify, and tune.
- `nethack_core/env.py` — `NetHackCoreEnv`, the gym-compatible wrapper
  (5-tuple `step`, swappable reward model) that downstream layers consume.

## Build & install

System toolchain (Debian/Ubuntu): `cmake`, `bison`, `flex`, `libbz2-dev`.

```bash
# 1. fetch the NetHack fork submodule
git submodule update --init --recursive

# 2. build libnethack.so + game data from the submodule
bash nethack_core/build_engine.sh
# -> produces third_party/NetHack/src/build/libnethack.so

# 3. install the uv workspace.
#    --all-packages is REQUIRED: numpy/gymnasium used to come transitively
#    via nle; with nle removed they are direct workspace deps. A bare
#    `uv sync` will under-install.
uv sync --all-packages
```

`build_engine.sh` walks up to the repo root, configures cmake from the
submodule source (deps are vendored under `src/third_party/`), and builds the
`nethack` target. Set `JOBS=N` to control parallelism. The binding locates the
library by walking up from `_engine.py` to `third_party/NetHack/src/build`, or
honours `NLE_LIB_PATH` if set (authoritative — raises `EngineNotBuilt` if that
path is missing). If the library is absent, `RawEngine()` raises
`EngineNotBuilt` with a build hint.

There is no `pip install nle` / `pip install minihack` step anymore — those
packages are gone.

## `EngineEnv` — deterministic env with snapshot + tune

`nethack_core/engine_env.py`. Seed-before-reset is enforced (refusing to reset
without explicit seeds keeps trajectories reproducible by construction).

```python
from nethack_core.engine_env import EngineEnv

env = EngineEnv()                 # optional modify= default applied every reset
env.seed(42)                      # stage (core, disp); disp defaults to core
obs, meta = env.reset(seeds=(42, 42))   # seeds= overrides any staged seed
obs, done, info = env.step(ord("."))    # action is a keystroke byte
env.close()
```

Signatures (verified against source):

- `seed(core, disp=None) -> (core, disp)` — stage seeds for the next reset
  (`disp` defaults to `core`).
- `reset(*, seeds=None, tune=None, modify=None) -> (CoreObservation, EpisodeMetadata)`
  — `tune` applies difficulty-knob overrides **before** the starting level is
  generated (generation knobs reshape the starting floor); `modify` applies
  whitelisted state mutations **after** the game starts. If `modify` is omitted,
  the per-instance `__init__(modify=...)` default is used; pass `modify={}` to
  apply nothing.
- `step(action) -> (CoreObservation, done, info)` — `action` is a keystroke byte
  (e.g. `ord(".")`); `info` carries `how_done` when `done`.
- `modify(**changes) -> CoreObservation` — see *State modification* below.
- `snapshot() -> handle`, `restore(handle) -> CoreObservation`,
  `free_snapshot(handle)` — in-memory checkpoints (below).
- `branch(n, reseed=True, horizon=40, action=ord("s")) -> list[list[bytes]]` —
  divergent continuations (below).
- `save_level(path)`, `load_level(path) -> CoreObservation` — portable floor
  blobs (below).
- `get_tune() -> dict`, `set_tune(**knobs) -> EngineEnv` — difficulty knobs
  (below). Also exposed as `env.tune.get()` / `env.tune.set(**knobs)` /
  `env.tune.catalog()`.
- Properties: `done`, `current_seeds`, `engine` (the raw `RawEngine`),
  `observation_space` (a lazily-built gymnasium Dict).

> Note: the brief listed `reset(*, seeds, character=None, modify=None)` and a
> `get_tune`/`set_tune` pair. The actual `EngineEnv.reset` keyword is **`tune`**,
> not `character` (character is fixed in the engine options string). `EngineEnv`
> has no `character` parameter; `NetHackCoreEnv.reset` is where `character=` lives.

## `NetHackCoreEnv` — gym-compatible wrapper

`nethack_core/env.py`. Wraps `EngineEnv` and presents the gymnasium-style API
the rest of the harness expects.

```python
from nethack_core.env import NetHackCoreEnv
from nethack_core.rewards import DeltaReward

env = NetHackCoreEnv(task_name="NetHackScore-v0", reward_model=DeltaReward())
env.seed(42)
obs, meta = env.reset(seeds=(42, 42))
obs, reward, done, truncated, info = env.step(ord("."))   # gym 5-tuple
```

Signatures:

- `__init__(task_name="NetHackScore-v0", ..., reward_model=None, modify=None)` —
  `reward_model` defaults to `ScoreDepthXPReward`; `modify` is a default applied
  on every reset and pass-through `modify()`.
- `seed(core, disp=None)`, `reset(*, seeds=None, character=None)` —
  `character` is accepted but not yet wired into the engine (logs a warning);
  it is stamped onto the returned `EpisodeMetadata`.
- `step(action) -> (obs, reward, done, truncated, info)` — the gym 5-tuple.
  Reward comes from the reward model (the fork engine has no gym reward);
  `truncated` is `False` unless `info` provides one.
- `modify(**changes) -> CoreObservation` — pass-through to `EngineEnv.modify`
  (native path only; raises on a non-native task).
- Properties: `action_space` (`Discrete(256)` — raw keystroke bytes),
  `observation_keys` (ordered field names), `last_observation` (a list ordered
  by `observation_keys`, so `last_observation[observation_keys.index("chars")]`
  works), `current_seeds`, `underlying` (the `EngineEnv`).

The former MiniHack/`des_file` gym backend has been removed. Any `task_name`
containing `"MiniHack"` now raises loudly at construction (`_is_native` guard)
instead of silently mis-routing. Only native tasks (`NetHackScore-v0`,
`NetHackChallenge-v0`) and saved-level blobs remain.

## Reward models

`nethack_core/rewards.py`. The env and engine are reward-agnostic; a
`RewardModel` maps the observation stream to a per-step scalar.

- `RewardModel` — base class. `reset(obs)` seeds the previous observation;
  `step(obs)` returns the reward and advances the stored previous obs.
  Subclasses override `_reward(obs, prev)` (`prev` is `None` on the first step
  after a reset).
- `ScoreDepthXPReward` — **default**. Progress potential
  `score + depth*50 + experience_level*50`, read straight from `blstats`.
- `DeltaReward` — per-step delta of a potential model
  (`potential(obs_t) - potential(obs_{t-1})`, `0.0` on the first step); wraps
  `ScoreDepthXPReward` by default.

Swap via the constructor: `NetHackCoreEnv(reward_model=DeltaReward())`.

## State modification (`modify`)

`EngineEnv.modify(**changes)` (and `NetHackCoreEnv.modify`) apply whitelisted,
bounds-checked state mutations. The **whole call is validated first** — unknown
fields or out-of-range values raise before any engine write, so no
partial/arbitrary writes happen. Whitelist and inclusive bounds:

| field      | bounds          |
|------------|-----------------|
| `hp`       | `0 .. 30000`    |
| `max_hp`   | `1 .. 30000`    |
| `gold`     | `0 .. 10000000` |
| `xp_level` | `1 .. 30`       |
| `hunger`   | `0 .. 2000`     |
| `goto_depth` | `1 .. 60` (dungeon-level jump, handled separately) |

After writing the fields, `modify` either runs the deferred `goto_depth` jump or
issues a ctrl-R redraw (so `blstats` refresh without consuming a game turn),
then returns the refreshed `CoreObservation`. Applies live, or at reset via
`reset(modify=...)` / `EngineEnv(modify=...)`.

```python
# skip to dungeon level 4 with full-ish HP
obs = env.modify(goto_depth=4, hp=200, max_hp=200)
# or at reset:
obs, meta = env.reset(seeds=(42, 42), modify={"goto_depth": 4, "hp": 200})
```

## Difficulty / generation knobs (`tune`)

The knob catalog is read from `libnethack.so` (fixed per build), so a new knob
in the engine appears with no binding change. `1.0` is the vanilla baseline for
every knob. **Generation knobs only take effect at reset** (pass `tune=` to
`reset`); the rest apply live on the next step.

```python
env.reset(seeds=(7, 7), tune={"room_density": 1.5, "mob_spawn": 2.0})  # at start
env.set_tune(vision_radius=3, fog_of_war=0)                            # live
knobs = env.get_tune()                                                 # current values
```

Catalog (verified from the engine, 18 knobs):

- **Vision** — `vision_radius`, `fog_of_war`, `reveal_map`.
- **Stat / combat scales** — `dmg_to_player_scale`, `dmg_by_player_scale`,
  `player_hp_scale`, `hp_regen_scale`, `hunger_rate_scale`,
  `ongoing_spawn_scale`, `monster_difficulty_scale`, `monster_speed_scale`,
  `xp_gain_scale`.
- **Generation (reset only)** — `room_density`, plus the five later knobs
  `mob_spawn`, `trap_density`, `locked_door`, `corridor_connectivity`,
  `room_size`.

Unknown knob names raise `KeyError`.

## Snapshot / restore / branch

In-memory checkpoints for replay and divergent exploration. A snapshot is a
self-contained C-side copy of `(ctx + coroutine stack + arena + display
mirror)`, restorable repeatedly with byte-exact fidelity (glyphs/chars/colors
**and** blstats reproduce a from-scratch run, even across repeated restores).

A handle is bound to the `RawEngine` instance that created it; restoring a
foreign handle raises `ValueError`. After `restore`, the numpy observation
buffers reflect the restored state only after the **next** `step` (callers
normally step after restoring).

```python
h = env.snapshot()
# ... explore ...
env.restore(h)            # back to the captured point
env.free_snapshot(h)      # or rely on close()/__del__ to reap leaked handles
```

`branch(n, reseed=True, horizon=40, action=ord("s"))` snapshots once, then
restores `n` times. With `reseed=True` each branch reseeds the gameplay RNG
**after** restore (order matters — the snapshot captures the RNG), so
random-chance events diverge; with `reseed=False` branches replay identically.
Each branch is rolled out `horizon` steps of `action` and returned as a per-step
trace of the map `chars` (one `bytes` per step) for divergence comparison.

## Level blobs (`save_level` / `load_level`)

`save_level`/`load_level` use NetHack's concrete `savelev`/`getlev` level-file
format — a self-contained snapshot of the *current* floor. Unlike a `snapshot`
(bound to the live ctx), a blob can be loaded into a fresh game. Blobs are
portable across fresh **same-build** games but are **not version-portable**. On
load the hero is re-seated on the level.

Load is **two-phase**: the C call mutates state without rendering; the binding
steps once (ctrl-R) internally to redraw, so the `CoreObservation` returned by
`load_level` already reflects the loaded floor. (`goto_depth` is two-phase the
same way — handled internally.)

```python
# generate -> save a floor -> later select a subset to replay
env.reset(seeds=(123, 123))
env.save_level("floors/dlvl1_seed123.blob")
# ...
obs = env.load_level("floors/dlvl1_seed123.blob")   # re-rendered obs
```

## Action vocabulary

`nethack_core/actions.py` — semantic named-keystroke `IntEnum`s, self-contained
(no `nle` import). Each member's int value **is** the keystroke byte the engine
consumes, so `env.step(Command.SEARCH)` works directly:

- `CompassDirection` (`N`=`ord('k')`, …) and `CompassDirectionLonger`
  (run/`shift` variants).
- `MiscDirection` (`UP`/`DOWN`/`WAIT`).
- `MiscAction` (`MORE` = 13).
- `Command` — the full command set (`SEARCH`, `PRAY`, `KICK`, `CAST`, …).
- `TextCharacters` — digits and punctuation (`PLUS`, `DOLLAR`, `NUM_0`…).

These mirror `nle.nethack`'s enums verbatim (stable public API) so the harness
drives the engine without importing `nle`.

## Glyph classification

`nethack_core/glyphs.py` — pure-Python glyph predicates (`glyph_is_monster`,
`glyph_is_object`, `glyph_is_trap`, `glyph_is_pet`, `glyph_is_statue`,
`glyph_is_invisible`, `glyph_to_mon`, …), derived directly from the fork's
`display.h` offset chain and counts (`NUMMONS`=381, `NUM_OBJECTS`=453,
`MAXPCHARS`=96). Each predicate accepts an int or numpy array and returns a
Python `bool` or bool array. The values are exact parity with `nle.nethack`'s
shared glyph numbering (asserted over the full glyph range in `tests`). Also
ships `cmap_clean_char_lut()` and the baked `MONSTER_NAMES` table
(`monster_name(idx)`).
