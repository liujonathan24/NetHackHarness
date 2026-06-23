# Curriculum learning environment

A compressed full-game NetHack curriculum: a fixed **female-neutral Valkyrie**
with **full vision** plays an intro segment, jumps to the deep end of the game
(with a realistic stat upgrade), and climbs back out through the Elemental
Planes — exposing late-game content to a fresh agent without requiring it to
survive the whole dungeon first.

## The dungeon ordering

```
descend:  DoD 1 -> 2 -> 3  --[JUMP + stat upgrade]-->  Gehennom 48 -> 49 -> 50
ascend:   Gehennom 50 -> 49 -> 48  --[JUMP]-->  DoD 3 -> 2 -> 1
          --[JUMP]-->  Elemental Planes: Earth -> Air -> Fire -> Water -> Astral
```

Boundary transitions are **cross-branch jumps** (Gehennom and the planes are
different dungeon branches normal stairs can't reach). The env intercepts the
`>`/`<` keystrokes the `descend`/`ascend` skills emit, so existing agents work
unmodified.

## How it works

| Piece | Where |
|---|---|
| `nle_goto_abs(dnum, dlevel)` cross-branch jump + dungeon-table query + attribute injection | fork `src/src/nle.c`, `include/nle.h` |
| `reveal_map` overlays `tty_chars` (full vision reaches the agent map) | fork `win/rl/winrl.cc` |
| `EngineEnv.goto_abs` / `dungeon_table`; `modify(str=..., ...)`; `character=` threading | `nethack_core/engine_env.py`, `_engine.py`, `env.py` |
| `CurriculumEnv` (play order, boundary jumps, upgrade) | `nethack_core/curriculum_env.py` |
| Valkyrie stat-upgrade model (analytic + NLD-fit) | `nethack_core/curriculum_upgrade.py`, `nethack_core/nld_parse.py`, `tools/build_valkyrie_model.py` |
| `ascend` skill | `nethack_harness/tools/skills.py` |
| `curriculum` tier | `nethack_harness/curriculum/curriculum.py`, wired in `nethack.py` |

Default seed is **19** (its Gehennom reaches absolute depth 50, so 48–50 are all
real levels).

## Run it

Local smoke (no model/API — drives the curriculum with the skill registry):

```bash
ROOT=/scratch/gpfs/ZHUANGL/jl0796/NetHackHarness
$ROOT/.venv/bin/python tools/curriculum_demo.py --seed 19
```

Render the descent + ascent GIFs (→ `videos/`):

```bash
$ROOT/.venv/bin/python tools/curriculum_gifs.py --seed 19
```

Tests:

```bash
cd environments/nethack
$ROOT/.venv/bin/python -m pytest tests/test_curriculum_env.py \
    tests/test_curriculum_traversal.py tests/test_nld_parse.py -q
```

## Experiments (Prime Intellect, free laguna model)

The curriculum is a normal tier, so the existing eval pipeline targets it with
`tier=curriculum`. Go-Explore / Voyager / rlm drive it through the skill
registry (`descend`/`ascend`).

```bash
# local LM eval
vf-eval nethack -m poolside/laguna-m.1 -n 1 -r 1 \
    -a '{"tier":"curriculum"}' --endpoints configs/endpoints.toml

# Prime (results -> app.primeintellect.ai)
prime eval jonathanliu/nethack -m poolside/laguna-m.1 -n 1 -r 1 \
    -a '{"tier":"curriculum"}' --timeout 600
```

Pass env args with `-a '{...}'` (NOT `-x`). For the laguna model recreate the
REFINER creds (`/tmp/ch_env.sh`: `REFINER_API_KEY=<pit_... from ~/.prime/config.json>`,
`REFINER_BASE_URL=https://api.pinference.ai/api/v1`) and set
`REFINER_TIMEOUT_S=120` (laguna is a reasoning model; `max_tokens` must be
≥~1200 or content comes back empty). See `docs/EVAL_RECIPES.md`.

## The NLD upgrade model

`CurriculumEnv` upgrades the hero's **stats only** (XP level, HP, attributes —
no items) on the 3→48 jump, sampled from `ValkyrieUpgradeModel`. It uses a
built-in **analytic** Valkyrie-by-depth table out of the box.

To fit the **data-driven** model from the NLE human dataset (NLD-NAO / alt.org):

```bash
python tools/build_valkyrie_model.py --altorg /path/to/altorg \
    --out environments/nethack/nethack_core/data/valkyrie_model.json
# then construct: CurriculumEnv(upgrade_artifact=".../valkyrie_model.json")
```

`build_valkyrie_model` indexes the altorg ttyrecs with the vendored NLE loader,
filters Valkyrie games, parses each frame's status line
(`nethack_core/nld_parse.py`), and fits a per-depth `(mean, std)` per stat.
**Note:** the nle migration removed the installed `nle` package, so running the
fit requires either rebuilding the vendored ttyrec decoder (`_pyconverter`) or
decoding ttyrecs with a standalone reader + a Python VT emulator (e.g. `pyte`),
plus downloading the altorg corpus. Until then the analytic model is active.
```
