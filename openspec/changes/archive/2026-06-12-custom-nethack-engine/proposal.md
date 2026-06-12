## Why

The harness currently drives NetHack through the `nle>=1.3.0` PyPI package, which gives us no control over the game internals: we cannot snapshot/restore game state in O(1), we cannot tune difficulty, and we cannot customize levels beyond the MiniHack des-file path. We now have a custom struct-based NetHack fork (https://github.com/liujonathan24/NetHack) that moves all process-global game state into a per-env `nle_ctx_t` struct (~75 KB, reached via initial-exec TLS `current_nle_ctx`) and builds to `libnethack.so`. Because the whole game lives in one struct, we can finally get cheap state cloning (replay), expose tunable difficulty knobs, and load custom levels — capabilities the eval/research roadmap needs. The fork is developed by the same user, so the required engine-side C entry points are in scope.

## What Changes

- **BREAKING**: Remove the `nle>=1.3.0` PyPI dependency and drive the game through the fork's `libnethack.so` instead. Full cutover — no `nle` fallback retained.
- Add the fork (`liujonathan24/NetHack`) as a **git submodule** with a documented build path producing `libnethack.so` + game data; wire it into the Python build/install and `Dockerfile.prime`.
- Add a **standalone ctypes/cffi binding** in this repo (a new `_engine` module). No PufferLib or NLE-Python dependency. The binding fills raw observation buffers; the existing `observations.py` `shape()` pipeline is reused by constructing `CoreObservation` from those buffers instead of from an NLE obs dict.
- Add **O(1) struct snapshot/restore**: `snapshot() -> bytes` and `restore(bytes)` over `nle_ctx_t`, replacing/superseding the O(n) action-replay in `legacy/replay.py`.
- Add **difficulty tuning**: a new `nle_tune_t` knob sub-struct read at engine decision sites, exposed to Python as runtime-settable knobs (`mob_spawn_rate`, `dmg_to_player_scale`, `player_hp_scale`, `vision_radius`, `fog_of_war` on/off, `floor_subset`/`start_dlvl`, `locked_door_rate`, `luck_override`, per-attribute overrides, …). Designed to be extensible: a new knob = one struct field + one engine read site.
- Add **level customization**: an engine entry point to load a custom level/scenario (des-file or struct-prep), so curriculum scenarios no longer depend on the separate MiniHack package.
- Define the **new fork-side C API**: `nle_get_obs`, `nle_set_seed` (deterministic, `reseed=false`), `nle_snapshot`/`nle_restore`, `nle_get_tune`/`nle_set_tune`, `nle_load_level` (atop the existing `nle_start`/`nle_step`/`nle_end`). These land in the submodule but are specified here.
- Migrate harness touch points: `NetHackCoreEnv` seed/reset/step, `observations.py` `shape()`, `skills.py` action-index mapping and `last_observation` reads, curriculum tiers' MiniHack usage, `pyproject.toml`, `Dockerfile.prime`.

## Capabilities

### New Capabilities
- `nethack-engine`: How the harness obtains, builds, and binds the custom NetHack engine (submodule, `libnethack.so`, ctypes/cffi binding, observation buffer extraction, deterministic seeding, action stepping) — the contract that replaces the `nle` dependency.
- `state-snapshot`: O(1) struct snapshot/restore of game state for replay and branching, including how snapshot completeness is guaranteed (in-memory ctx + any on-disk level state).
- `difficulty-tuning`: The `nle_tune_t` knob block and its Python surface — which knobs exist, their semantics/ranges, when they take effect (reset-time vs live), and how new knobs are added.
- `level-customization`: Loading custom levels/scenarios into the engine, and how curriculum tiers move off MiniHack onto this path.

### Modified Capabilities
<!-- No existing OpenSpec specs in openspec/specs/ yet; this is the first formal capability set for the engine layer. -->

## Impact

- **Dependencies**: Removes `nle>=1.3.0`; removes/loosens the MiniHack git dependency once level-customization replaces it. Adds a git submodule + native build toolchain (cmake/bison/flex/libbz2) already present in `Dockerfile.prime`.
- **Code**: `environments/nethack/nethack_core/env.py` (`NetHackCoreEnv` seed/reset/step), `environments/nethack/nethack_core/observations.py` (`shape()` source), `environments/nethack/nethack_harness/tools/skills.py` (action-index mapping, `last_observation`/`_observation_keys` reads), `legacy/replay.py` (action-replay → struct-snapshot), `environments/nethack/nethack_harness/curriculum/curriculum.py` (MiniHack tiers), `pyproject.toml` files, `Dockerfile.prime`.
- **Engine (submodule)**: New C API surface and `nle_tune_t` struct in `liujonathan24/NetHack`; tracked as submodule work but specified by this change.
- **Determinism/replay**: Replay model changes from action-sequence replay to struct snapshot/restore. Leading risk: `nle_ctx_t` (~75 KB) is smaller than a full multi-level dungeon (NetHack swaps inactive levels to disk), so a true clone may require capturing ctx + on-disk level files — this gates the snapshot/replay API shape and is the first spike.
- **Platforms**: Native build moves from pip-installed `nle` wheel to a locally built `.so`; CI/Docker and local dev install paths change.
