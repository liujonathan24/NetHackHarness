# Capabilities

A post-processed, aggregated view of what this repository can do — synthesized
from the per-capability specs into one whole-repo reference. For *where* each
piece lives and how a turn flows, see [`REPO_MAP.md`](REPO_MAP.md).

The clean `main` branch is the curated public face. The authoritative
per-capability specs and their change history live under `openspec/` on the
[`experimental`](https://github.com/liujonathan24/NetHackHarness/tree/experimental)
branch; this document is the refined aggregate of them.

---

## Engine & determinism

**Fork engine via ctypes.** The harness drives a custom NetHack fork
(`third_party/NetHack`) directly through a ctypes binding (`RawEngine`), not the
`nle` / `minihack` PyPI gym wrapper. No `import nle` remains; numpy and gymnasium
are direct dependencies. This direct binding is what makes everything below
possible — the gym wrapper exposes none of it.

**In-memory snapshot / restore.** `snapshot() -> handle` captures the complete
game state (engine context, coroutine stack, arena, and display mirror) in
constant time; `restore(handle)` brings it back byte-for-byte across glyphs,
chars, colors, and blstats. Snapshots are bound to their creating engine
instance, span multiple dungeon levels in memory (no disk swapping), and are
build-version tagged so a stale snapshot can never silently corrupt a newer
engine.

**Divergent exploration via branching.** `branch(n, reseed=True|False)` snapshots
once and restores `n` times. With `reseed=True` the RNG is reseeded after each
restore so chance events (spawns, searches, doors) diverge across branches; with
`reseed=False` you get identical replays. This is the basis for Monte-Carlo
lookahead with no action replay.

**Portable level blobs.** `save_level(path)` / `load_level(path)` serialize a
level in NetHack's own `savelev`/`getlev` format (portable across same-build
games, not version-portable). Load is two-phase — a C-side mutation followed by
an internal redraw step.

**Secure state modification.** `modify(**changes)` applies only whitelisted,
bounds-checked edits: `hp` (0–30000), `max_hp` (1–30000), `gold` (0–10M),
`xp_level` (1–30), `hunger` (0–2000), `goto_depth` (1–60), `level_up` (1–29).
Unknown fields and out-of-range values are rejected before any write — no partial
mutations.

## Difficulty & generation tuning

**17 parametric knobs**, verified against the engine catalog and grouped by when
they take effect:

- **Vision (live):** `vision_radius`, `reveal_map`
- **Stat / combat scales (live):** `dmg_to_player_scale`, `dmg_by_player_scale`,
  `player_hp_scale`, `hp_regen_scale`, `hunger_rate_scale`, `ongoing_spawn_scale`,
  `monster_difficulty_scale`, `monster_speed_scale`, `xp_gain_scale`
- **Generation (reset-only):** `room_density`, `mob_spawn`, `trap_density`,
  `locked_door`, `corridor_connectivity`, `room_size`

Live knobs apply on the next step; generation knobs apply on the next
`reset`/regenerate. Unknown knob names raise `KeyError`. The web console and
`tools/knob_gifs.py` exercise these for visual verification.

## Observation & encoding

**Canonical typed map model.** `build_map_model` produces one typed structure —
player position, typed entities (monster species + pet flag, item object class,
stair direction, door state, trap type), and a compact walkable/visible grid —
from the glyph grid, reused by every encoding.

**12+ observation encodings** from a single registry: `B0`/`B1` (uncompressed /
compacted ASCII map + status/inventory/adjacency), `B` (BALROG natural-language
scene), `G` (glyph-box, for code mode), `JSON`/`TOON` (the canonical model as
structured text, `map_detail` full/minimal), `IMG` (rendered tiles),
`IMG_TTY` (tty-text raster), `ND`/`FD` (descent-salience blocks), `E1`/`E2`
(frontier-surface), `R` (summarize-and-reset compaction), `P`/`CH` (continual
harness). TOON is implemented in-repo with no external package. Image paths fail
fast on missing dependencies rather than silently degrading.

**Code-interpretable map.** In code mode, `nh.map` is a read-only view exposing
the player position, the full entity list, `nh.map.at(x, y)` lookup, and
convenience accessors (`nh.map.monsters`, `nh.map.stairs`).

## Agent interfaces & skills

**Two action interfaces.** `interface="skill"` (default) exposes one OpenAI
function-calling tool per skill. `interface="code"` exposes a single
`code(source=...)` tool running sandboxed Python against the `nh` namespace —
all skills plus a queryable `nh.map` plus sub-LM tools (`nh.summarize`,
`nh.plan`, `nh.recall_lm`).

**Skill registry.** A typed, schema'd registry (`nethack_harness/tools/skills.py`)
provides move/attack/descend/search/pickup/move_to plus high-level NetPlay-style
skills, with a raw NLE action-index escape hatch always available. Common
hallucinated tool names are auto-aliased to the canonical skill.

**Closed-loop `explore_and_descend`.** A mega-skill that explores a floor, opens
doors, searches dead-ends and the perimeter for hidden passages (unbounded,
NetPlay-prioritized `sc² − prio·100`, persistent per-floor search count), melees
adjacent hostiles while HP is healthy, applies pet tactics, finds and paths to
the down-staircase, descends, and returns control per floor.

## Curriculum

**13 named tiers** (`nethack_harness/curriculum/curriculum.py`): `empty_room`,
`solo_combat`, `multi_combat`, `corridor_explore` (default, reach dlvl 2),
`mini_dungeon`, `mines_to_minetown`, `sokoban_complete`, `oracle_consult`,
`full_dungeon_easy`, `full_nle`, `dynamic_subgoal`, `quest_complete`,
`castle_reached`. Each tier sets a step budget, a description, and a success
milestone checked every step to drive early termination. Milestones are
composable; `dynamic_subgoal` assigns mid-episode subgoals. Pass `tier=None` to
sample uniformly across tiers.

## Memory & context management

A per-rollout **journal** (`memory/journal.py`) stores observations, tactics, and
death logs. **Belief-state summarization** (`belief_state_interval`) folds prior
levels into the journal on a cadence. History retention is configurable
(`history_keep_full`, `history_drop_after`, `journal_render_max_chars`), and
`continual` + `continual_lives` auto-reset on death while preserving the
journal/belief state.

## Continual self-refinement

Under `variant=CH`, a **separate teacher model** refines the policy mid-episode
every `refine_interval` turns, emitting CRUD edits across prompt / sub-agents /
skills / memory, each interval recorded in the trace. The teacher is required and
distinct from the policy (credentials resolved from the environment; fails loud
if missing). A refiner error is logged and swallowed rather than aborting the
rollout, and a `run_macro` tool makes refiner-authored skills invocable. CH is
evaluated against the `B1` baseline on matched seeds over a ≥500-turn horizon.

## Evaluation & replay tooling

**Encoding-comparison harness** (`tools/encoding_eval/`) runs the same task across
encoding × model matrices and reports per-encoding metrics: progression
score/tier, max dungeon level, descent rate with Wilson confidence interval,
scout coverage, steps-to-first-descent, and tokens/turn. Aggregation reuses
`tools/eval_instrument.py` and the BALROG progression scorer.

**In-browser rollout viewer** (`tools/rollout_view/live_server`) renders each turn
in two panes — the game state the human sees and the exact LLM input for the
chosen encoding — with a scrubbable timeline, live stepping, a file browser, and a
stats dashboard. **Post-hoc metrics** (`stats.py`) compute time series over saved
traces; `register_metric(name, fn)` adds a custom metric from any per-turn record.

**Web console** (`tools/play_server.py`) is a Flask app over a shared `EngineEnv`:
a `/map` page for live interactive play with live/reset difficulty knobs and
snapshot-backed **undo** and **checkpoint/restore** (the live Monte-Carlo demo),
an `/obs` page for building observations and plotting metrics, and a `/traces`
page that scrubs recorded rollouts.

## Reproducibility

`seed()` is always called before `reset()`; both the core and display RNGs are
seeded and the seed hash is logged for audit. A trajectory is replayable as just
`(seeds, action_sequence)` — `reset(seeds=...)` then replay the actions —
sufficient for episodes up to ~10⁴ steps, while snapshot/restore covers the cases
where replay would be too slow.
