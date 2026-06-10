## ADDED Requirements

### Requirement: Difficulty knob block
The engine SHALL hold a `nle_tune_t` knob sub-struct within `nle_ctx_t`, read at the relevant decision sites, and SHALL expose `nle_get_tune`/`nle_set_tune`. The harness SHALL surface it as `tune.get() -> dict` and `tune.set(**knobs)`. The v1 knob catalog below is canonical; each knob is tagged with its layer, timing (R = reset/generation-time, L = live per-step), type, default, and engine read-site.

**Layer 0 — Start state** (timing R unless noted)

| Knob | Type | Default | Read-site |
| --- | --- | --- | --- |
| `role` / `race` / `gender` / `alignment` | enum | random | `u_init.c` |
| `start_dlvl` | int | 1 | start `goto_level` / `u.uz` |
| `starting_inventory` | list | role default | `nle_settings.wizkit` / `u_init.c` |
| `attr_overrides` (STR..CHA) | int? | none | `attrib.c` / `u.acurr` |
| `luck_override` (L) | int | 0 | `u.uluck` |
| `starting_gold` | int | role default | `u_init.c` |

**Layer 1 — Topology** (timing R)

| Knob | Type | Default | Read-site |
| --- | --- | --- | --- |
| `max_floors` | int | 25±5 | `init_dungeons` / `dungeon.def` clamp |
| `enabled_branches` | set | all | `init_dungeons` / `add_branch` |
| `floor_subset` | list[int] | all | dungeon topology |

**Layer 2 — Parametric generation** (timing R, applied per level in `mklev`)

| Knob | Type | Default | Read-site |
| --- | --- | --- | --- |
| `room_density` | float | 1.0 | `makerooms` (mklev.c) |
| `room_size_scale` | float | 1.0 | `do_room_or_subroom` |
| `corridor_connectivity` | float | 1.0 | `makecorridors` (mklev.c) |
| `locked_door_rate` | float | vanilla | `dosdoor` `D_LOCKED` branch |
| `door_trap_rate` | float | vanilla | `dosdoor` `D_TRAPPED` |
| `secret_door_rate` | float | vanilla | `dosdoor` SDOOR |
| `mob_spawn_scale` | float | 1.0 | `makelevel` populate / `makemon` |
| `object_spawn_scale` | float | 1.0 | `mkobj` density |
| `trap_density` | float | 1.0 | `mktrap` |

**Layer 3 — Engine mechanics** (timing L)

| Knob | Type | Default | Read-site |
| --- | --- | --- | --- |
| `dmg_to_player_scale` | float | 1.0 | `mhitu.c` |
| `dmg_by_player_scale` | float | 1.0 | `uhitm.c` |
| `player_hp_scale` | float | 1.0 | `u.uhpmax` + regen |
| `hp_regen_scale` | float | 1.0 | regen (`allmain.c`) |
| `vision_radius` | int | vanilla | `vision.c` |
| `fog_of_war` | bool | true | vision/display |
| `reveal_map` | bool | false | display (mark seen) |
| `hunger_rate_scale` | float | 1.0 | `eat.c` / `gethungry` |
| `ongoing_spawn_scale` | float | 1.0 | periodic `makemon` |
| `monster_difficulty_scale` | float | 1.0 | `level_difficulty()` (dungeon.c) |
| `monster_speed_scale` | float | 1.0 | `mon.c` movement |
| `xp_gain_scale` | float | 1.0 | experience award |

#### Scenario: Read defaults
- **WHEN** `tune.get()` is called on a fresh game with no overrides
- **THEN** it returns every catalog knob with its default value, and the defaults reproduce vanilla NetHack behavior

#### Scenario: Set a live engine knob and observe effect
- **WHEN** `tune.set(dmg_to_player_scale=0.0)` is applied and the player is attacked
- **THEN** the player takes no damage from that attack, reflected in `blstats` HP

#### Scenario: Fog of war toggle
- **WHEN** `tune.set(fog_of_war=False)` is applied
- **THEN** the observation reveals the level beyond the normal vision/lit area

#### Scenario: Parametric generation knob changes the generator
- **WHEN** `locked_door_rate` is lowered and a new game/level is generated with a fixed seed
- **THEN** the generated level contains proportionally fewer locked doors than the vanilla default at that seed

### Requirement: Knob effect timing is specified
Each knob SHALL honor its catalog timing tag. Reset/generation-time (R) knobs SHALL be applied before game/level generation; live (L) knobs SHALL take effect on the next step after being set. Setting an R knob mid-episode SHALL be accepted and applied at the next reset, and the binding SHALL signal that it is deferred rather than silently partially applied.

#### Scenario: Reset-time knob applied at generation
- **WHEN** `start_dlvl` is set before reset
- **THEN** the new game begins on that dungeon level

#### Scenario: Live knob applied mid-game
- **WHEN** `vision_radius` is changed during play
- **THEN** the next observation reflects the new vision radius without a reset

#### Scenario: Reset-time knob set mid-game defers
- **WHEN** a reset/generation-time knob (e.g. `room_density`) is set mid-game
- **THEN** the binding signals it will apply on the next reset, and the current level is unchanged

### Requirement: Knob extensibility
Adding a new knob SHALL require only adding a field to `nle_tune_t` plus one engine read-site, with no change to the binding's get/set plumbing. The catalog in this spec is the v1 set and is explicitly open-ended.

#### Scenario: New knob round-trips automatically
- **WHEN** a new field is added to `nle_tune_t` and the engine rebuilt
- **THEN** the new knob appears in `tune.get()` and is accepted by `tune.set()` without binding code changes
