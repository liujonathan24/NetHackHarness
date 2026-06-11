## ADDED Requirements

### Requirement: Engine sourced from the fork submodule
The harness SHALL obtain the NetHack engine from the `liujonathan24/NetHack` fork pinned as a git submodule, and SHALL build it to `libnethack.so` as part of install. The `nle` PyPI package SHALL NOT be a dependency.

#### Scenario: Fresh checkout builds the engine
- **WHEN** the repo is cloned with `--recurse-submodules` and the documented build command is run
- **THEN** `libnethack.so` and the game data files are produced and discoverable by the binding

#### Scenario: nle dependency removed
- **WHEN** the project dependencies are inspected after migration
- **THEN** `nle` does not appear in any `pyproject.toml`, lockfile, or runtime import path

#### Scenario: Missing engine fails fast
- **WHEN** the binding initializes and `libnethack.so` cannot be located
- **THEN** it raises a clear error naming the expected path and the build command, rather than failing obscurely

### Requirement: Standalone ctypes/cffi binding
The harness SHALL drive the engine through a standalone `_engine` ctypes/cffi binding in this repo that calls the fork's C API (`nle_start`, `nle_step`, `nle_end`, and the new entry points). The binding SHALL NOT depend on PufferLib or any NLE Python layer.

#### Scenario: Rollout without external engine packages
- **WHEN** a rollout runs in an environment with neither `nle` nor `pufferlib` installed
- **THEN** the game starts, steps, and ends successfully through the `_engine` binding

### Requirement: Observation buffer parity
The binding SHALL fill observation buffers (`tty_chars`, `tty_colors`, `tty_cursor`, `glyphs`, `chars`, `colors`, `message`, `blstats`, `inv_strs`, `inv_letters`, `inv_glyphs`) via `nle_get_obs`, and `NetHackCoreEnv` SHALL construct `CoreObservation` from them so that `observations.py` `shape()` and downstream consumers operate unchanged.

#### Scenario: Golden-trace parity with the prior nle path
- **WHEN** the same seed and action sequence are run through a previously-recorded `nle` trace and the new binding for N steps
- **THEN** `tty_chars`, `blstats`, and `message` are byte-identical at every step

#### Scenario: Structured observation unchanged
- **WHEN** `shape()` is given a `CoreObservation` built from the binding's buffers
- **THEN** it returns a `StructuredObservation` with the same fields and types as before the migration

### Requirement: Deterministic seeding
The binding SHALL expose deterministic seeding via `nle_set_seed(core, disp)` applied before game start with `reseed=false`, preserving the harness's seed-before-reset invariant.

#### Scenario: Same seed is reproducible
- **WHEN** two rollouts use the same `(core, disp)` seed and identical actions
- **THEN** every step's observation is identical between the two rollouts

#### Scenario: Reset requires explicit seed
- **WHEN** `reset()` is called without a staged seed
- **THEN** the env raises an error rather than starting a nondeterministic game

### Requirement: Action stepping parity
The binding SHALL accept the integer actions the harness already emits and map them to the engine's action table, preserving the semantics of the existing compass/misc-direction actions.

#### Scenario: Compass move produces expected movement
- **WHEN** a known compass-direction action index is stepped from a known position
- **THEN** the player moves in the corresponding direction as reflected in the observation
