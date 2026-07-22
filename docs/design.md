# NetHack as a Mature RL Training Environment

**Author:** Jonathan Liu
**Reviewers:** Alex Zhang
**Status:** Reconciled with the shipped architecture (originally a first draft for Monday discussion)
**Last updated:** July 2026

---

## 1. Goals and non-goals

### Goals

1. Build a mature, well-engineered training environment around NetHack that is genuinely useful for *training* LM agents (not just evaluating them).
2. Land it on the Prime Intellect Environments Hub as `jonathanliu/nethack`, train-ready with `prime-rl`.
3. Make the underlying gymnasium env useful to the non-LM RL community as well — anyone running PPO/GRPO on NetHack — by keeping the layer-1 core interface-agnostic (a plain `gym.Env` over the fork) so an RL algorithm can consume the bare environment while the LLM harness sits above it. (A PufferLib adapter lives in `legacy/`, parked rather than deleted.)
4. Ship a curriculum: a smooth difficulty ramp from a single room with one monster to the full game, controllable from a single config dict.
5. Get to a first RL training run (Qwen3-4B-Instruct, single-dungeon curriculum, scout reward) within ~4 weeks.

### Non-goals

- A new LLM-NetHack benchmark. BALROG and BRAID already serve that role; we contribute a training env, not a leaderboard.
- Beating BALROG progression with a frontier model. That's a downstream experiment; the deliverable here is the substrate.
- A from-scratch reimplementation of NetHack. We maintain a *custom fork* of the NetHack C source (the `third_party/NetHack` submodule) and drive it directly through our own ctypes binding (`nethack_core/_engine.py`, `RawEngine`) — not `nle`'s Python gym wrapper. The fork adds engine entry points (`nle_start/step/end`, snapshot/restore, `save_level`/`load_level`, `modify`, `tune`); it is not a rewrite of the game.
- Sitting on the `nle` / `minihack` PyPI stack. We started there but abandoned it: there is no `import nle` in the runtime path and MiniHack is not the curriculum backend. The whole point is to control the engine directly — in-memory snapshot/restore, portable level blobs, secure state edits, and live difficulty knobs — none of which the gym wrapper can expose. `numpy` and `gymnasium` are direct dependencies (they used to arrive transitively via `nle`).

---

## 2. Prior art

**The standard simulator stack (our starting point — since abandoned):**

- **NLE** (`github.com/heiner/nle`, NetHack 3.6.7, gymnasium API). The usual substrate for NetHack RL. We began here but hit its ceiling: the gym wrapper exposes a step/observation loop and nothing underneath it — no state capture, no generator control. We now fork the NetHack source directly and bind it with ctypes instead.
- **MiniHack** (`facebookresearch/minihack`). Probabilistic des-file DSL exposed as a `LevelGenerator` wrapper — the standard curriculum lever. We do not use it as the curriculum backend: difficulty is instead a continuous dial on the *real* dungeon generator (17 knobs) rather than a fixed des-file per variant. (MiniHack's tile assets are still borrowed, optionally, for the tile-image encodings.)
- **PufferLib** (Suarez et al., RLJ 2025). Reports ~10× synchronous speedup on NetHack via shared-memory vectorization. Our divergent-rollout story is instead O(1) in-memory snapshot/restore/branch on the fork; the PufferLib gym adapter is parked in `legacy/`.

**Harness research (what to learn from / build on):**

- **NetPlay** (Jeurissen et al., CoG 2024). Skill-mode API (`move_to`, `explore_level`, `drink`, `pickup`, `press_key`). Event tracker to interrupt skills when monsters appear.
- **BALROG** (Paglieri et al., ICLR 2025). Data-driven progression metric replacing score (which is gameable: you can score-farm forever on dlvl 1 by killing respawns). Uses Dungeons-and-Data trajectories to map (xp, dlvl) → ascension probability.
- **glyphbox** (Jan 2026, `github.com/kenforthewin/glyphbox`). Code-execution action API: one `execute_code` tool, model writes Python loops against a `nh.*` API. Token-efficient. Got GPT 5.2 to dlvl 10 / 12.56% BALROG.
- **Revisiting the NLE** (ICLR 2026 blogpost). Identifies the specific deficiencies in the standard NLE interface — menus, inventory letter resolution, role/race observability, score-as-reward — and validates fixes via Sample Factory PPO on MiniHack probes. Single most useful piece of prior work for this project.
- **Motif** (Klissarov et al., 2023). LLM-as-reward-model for NetHack playstyles.
- **Dungeons and Data** (Hambro et al., NeurIPS 2022). 100B+ tokens of human NetHack trajectories. SFT warmup substrate.

**Reproducibility:**

- **Predicting and controlling NetHack's randomness** (Sartak, 2009). The canonical write-up of NetHack's PRNG and the seed-time exploit.
- **SWAGGINZZZ** (pellsson, 2018). 7m15s ascension via RNG manipulation. Documents the wall-bump RNG-advance trick relevant to any "preview action" design.

---

## 3. Architecture

### 3.1 The layers

The project is a `uv` workspace deliberately split so an RL algorithm can consume the bare environment while a chat-based LLM agent uses the full harness — both over the *same* deterministic fork engine.

```
                  ┌──────────────────────────────────────┐
                  │ Layer 3: verifiers wrapper           │
                  │ environments/nethack/nethack.py      │
                  │ - verifiers env + tool dispatch      │
                  │ - chat-shaped, OpenAI tool calling   │
                  │ - rubric: scout, descent, ascension  │
                  └────────────────┬─────────────────────┘
                                   │ consumes
                                   ▼
                  ┌──────────────────────────────────────┐
                  │ Layer 2: harness (nethack_harness/)  │
                  │ - prompt / encoding registry         │
                  │ - skills, curriculum, navigation     │
                  │ - memory, refiner                    │
                  └────────────────┬─────────────────────┘
                                   │ over
                                   ▼
                  ┌──────────────────────────────────────┐
                  │ Layer 1: interface-agnostic core     │
                  │ nethack_interface/ (typed specs)     │
                  │ nethack_core/                        │
                  │ - NetHackCoreEnv (gym.Env)           │
                  │ - EngineEnv: snapshot/restore/branch,│
                  │   level blobs, modify(), 17 knobs    │
                  │ - canonical typed map model          │
                  └────────────────┬─────────────────────┘
                                   │ ctypes
                                   ▼
                  ┌──────────────────────────────────────┐
                  │ Layer 0: custom NetHack fork (C)     │
                  │ third_party/NetHack + libnethack.so  │
                  │ nle_start/step/end, snapshot/restore,│
                  │ save/load_level, modify, tune        │
                  └──────────────────────────────────────┘
```

The key inversion versus standard NetHack RL: we do **not** sit on the `nle` / `minihack` gym wrapper. `nethack_core` drives the fork directly through the `RawEngine` ctypes binding, which is what makes in-memory snapshot/restore/branch, portable level blobs, secure state edits, and live difficulty knobs possible at all. The contract between the RL-facing layer and everything above it is still gymnasium-shaped: anyone training a CNN-LSTM policy with PPO consumes layer 1 directly; the verifiers wrapper exists purely to bolt on chat-shaped tool calling and an LLM-compatible rubric.

### 3.2 Action interfaces

Selected via `load_environment(interface=...)`. Two interfaces shipped, sharing one skill registry (`nethack_harness/tools/skills.py`) so the advertised action set cannot drift from the implemented one:

- `"skill"` (default) — one OpenAI function-calling tool per skill: NetPlay-style `move`/`attack`/`descend`/`search`/`pickup`/`move_to` plus higher-level skills and a closed-loop `explore_and_descend` mega-skill. `skill_set` selects a profile (`full`, `move`, `dir8`, `netplay`, or an allowlist).
- `"code"` — glyphbox-style: a single `code(source=...)` tool running sandboxed Python against an `nh` namespace (all skills, a queryable read-only `nh.map`, and sub-LM tools `nh.summarize`/`nh.plan`/`nh.recall_lm`). Most token-efficient.

A **raw action-index escape hatch** (stepping the engine with primitive keystroke bytes) is always available underneath both interfaces, rather than being a separate top-level mode. Both interfaces share the same underlying state, so ablations across them are first-class.

### 3.3 Observation extraction and encoding

The fork fills ctypes buffers each step (`glyphs`, `chars`, `colors`, `blstats`, inventory, `tty_chars`). `NetHackCoreEnv` shapes those into a `CoreObservation`, and `StructuredObservation` extracts the structured pieces:

- `map` — the glyph/char grid.
- `menu` — when a menu is open, the `(letter, description)` options.
- `inventory` — `inv_strs` decoded into typed items (letter, description, category, count, BUC), always present.
- `status` — HP, AC, hunger, level, gold, turn count, dungeon level, alignment.
- `character` — role, race, alignment, gender.
- `messages` — game messages since the last action.
- `adjacent` — 8-direction adjacency (corridor, wall, monster, door, …).

The load-bearing piece is the **canonical typed map model** (`map_model.py`, `build_map_model`): one typed structure — player position, typed entities (monster species + pet flag, item object class, stair direction, door state, trap type), and a compact walkable/visible grid. *Every* observation encoding reads from this single model, so encodings cannot drift. A registry then renders it in 12+ variants — `B0`/`B1` (uncompressed / compacted ASCII), `B` (BALROG natural-language), `G` (glyph-box, for code mode), `JSON`/`TOON` (structured text), `IMG` (rendered tiles), `IMG_TTY` (tty raster), `ND`/`FD` (descent-salience), `E1`/`E2` (frontier-surface), `R` (summarize-and-reset), `P`/`CH` (continual harness). This encoding matrix — comparing what the model "sees" on matched seeds — is the project's active research axis.

### 3.4 Reward design

A composable `vf.Rubric`. The shipped default sums four functions:

- `scout_reward` — per newly observed tile. Dense, well-correlated with progress.
- `descent_reward` — on each new max-dungeon-level reached.
- `success_reward` — on hitting the active curriculum tier's success milestone.
- `ascension_reward` — on a successful ascension.

Score and BALROG progression are computed for *evaluation* (the encoding-eval harness reports BALROG progression), but are deliberately not the training signal — score is gameable, per §2.

### 3.5 Curriculum and difficulty knobs

The env defaults to the standard NetHack ascension game (`full_nle`); the curriculum is opt-in and is built *in-repo* on the fork engine — not on MiniHack des-files. `curriculum.py` defines **13 named tiers**, each with a step budget, a description, and a success milestone checked every step to drive goal-conditioned early termination:

`empty_room`, `solo_combat`, `multi_combat`, `corridor_explore`, `mini_dungeon`, `mines_to_minetown`, `sokoban_complete`, `oracle_consult`, `full_dungeon_easy`, `full_nle` (default), `dynamic_subgoal` (mid-episode subgoal assignment), `quest_complete`, `castle_reached`. Milestones are composable; pass `tier=None` to sample uniformly across tiers.

The smooth difficulty ramp comes from the fork's **17 parametric knobs** (`EngineEnv.tune`), a continuous dial on the *real* dungeon generator rather than a fixed level per variant:

- **Vision (live):** `vision_radius`, `reveal_map`.
- **Stat/combat scales (live):** `dmg_to_player_scale`, `dmg_by_player_scale`, `player_hp_scale`, `hp_regen_scale`, `hunger_rate_scale`, `ongoing_spawn_scale`, `monster_difficulty_scale`, `monster_speed_scale`, `xp_gain_scale`.
- **Generation (reset-only):** `room_density`, `room_size`, `mob_spawn`, `trap_density`, `locked_door`, `corridor_connectivity`.

These are opt-in `load_environment` overrides (`tune={...}`), alongside `modify={...}` (whitelisted, bounds-checked starting-state pokes — `hp`/`max_hp`/`gold`/`xp_level`/`hunger`/`goto_depth`/`level_up`) and `level_blob=<path>` (start on a custom saved level). All default to vanilla.

### 3.6 Wiki tool

Two-flavor:

- `wiki_search(query: str, k: int = 3)` — vector search over a NetHackWiki snapshot. ChromaDB index built on first load, persisted at `~/.cache/nethack-rl/wiki.chroma`. Identical pattern to `prime-rl/examples/wiki_search`.
- `wiki_lookup(entity: str)` — direct page fetch for a known entity (e.g., `wiki_lookup("cockatrice")`). When the env detects a new glyph in the agent's view it can optionally surface a "you have not seen a `c` before, you can `wiki_lookup('c')`" hint in observations.

We snapshot the wiki to avoid live HTTP during rollouts. License is CC-BY-SA; we redistribute the snapshot with attribution.

### 3.7 Reproducibility, snapshot/restore, and replay

- `seed()` is always called before `reset()`; both the `core` and `disp` RNGs are seeded and the seed hash is logged on every rollout for audit.
- **In-memory snapshot / restore / branch** (the shipped headline, on the fork). `snapshot() -> handle` captures the complete game state — engine context, coroutine stack, arena, and display mirror — in constant time; `restore(handle)` brings it back byte-for-byte across glyphs/chars/colors/blstats. Snapshots are bound to their creating engine, span multiple dungeon levels in memory (no disk swapping), and are build-version tagged so a stale snapshot can't corrupt a newer engine. `branch(n, reseed=True|False)` snapshots once and restores `n` times — with `reseed=True` each branch reseeds after restore so chance events diverge — giving O(1) Monte-Carlo lookahead with *no action replay*. This is what replaced the originally-planned `dosave`/`dorecover` save-file path.
- **Trajectory replay** (still available, parked in `legacy/replay.py`): record `(seeds, action_sequence)` and replay `reset(seeds=...)` then the actions. Sufficient for shorter episodes; snapshot/restore covers the cases where replay would be too slow.
- **Portable level blobs.** `save_level(path)` / `load_level(path)` serialize a level in NetHack's own `savelev`/`getlev` format (portable across same-build games, not version-portable) — a concrete level, not a scripted description.

---

## 4. Feature roadmap and priorities

**Tier 1 — Harness layer (the things flagged in Wed discussion).** All have ICLR 2026 or glyphbox validation.

1. Menu observation extraction + augmented `menu_option_k` action.
2. Inventory item resolution + augmented `inventory_item_k` action.
3. Always-on inventory in observation (via `inv_strs`).
4. Auto-`#attributes` on reset, role/race/alignment in observation.
5. Seed-before-reset enforcement + deterministic RNG capture in snapshots.
6. Trajectory replay.

**Tier 2 — Action API design.**

7. Skill-mode API (NetPlay-derived).
8. Code-mode API (glyphbox-derived) with sandboxed REPL.
9. Autoexplore — A* pathfinding + frontier-based exploration in `nethack_harness/navigation/`, wrapped by the closed-loop `explore_and_descend` skill.
10. Persistent memory tools (`add_note`, `add_reminder`) from glyphbox.

**Tier 3 — Curriculum, wiki, speed.**

11. `curriculum.py` with the seven named tiers.
12. Wiki tool (search + lookup), ChromaDB index of NetHackWiki.
13. Scout / BALROG / score rewards as a composable rubric.
14. PufferLib adapter for layer 1 — implemented but parked in `legacy/puffer_env.py` (divergent-rollout throughput is instead served by in-memory snapshot/branch).
15. RNG determinism via seed-before-reset + snapshot capture of RNG state (a standalone `rn2` tracing patch proved unnecessary once snapshot/restore landed).
16. Save-state — shipped as **in-memory** snapshot/restore/branch on the fork (plus portable `save_level`/`load_level` blobs), instead of the originally-planned C-side `dosave`/`dorecover` save files.

**Tier 4 — Research bets (not in scope for v1 but worth flagging).**

17. Motif-style LLM-as-reward auxiliary signal.
18. Dungeons-and-Data SFT warmup pipeline integrated with the env.
19. Multi-task EnvGroup combining NetHack curricula with other roguelikes (Crafter, Baba Is AI) for generalist eval.

---

## 5. Milestones

| Week | Deliverable |
|------|-------------|
| 0 (this week) | Repo skeleton; layer 1 `NetHackCoreEnv` running; v0 verifiers env on Hub; `vf-eval` smoke test passes against `gpt-4.1-mini` |
| 1 | Menu + inventory + character observation fixes (Tier 1 #1–4). Reproducibility (#5–6). |
| 2 | Skill API (#7) and curriculum (#11). First training run on `solo_combat` tier with Qwen3-1.7B. |
| 3 | Code API (#8), wiki tool (#12), full rubric (#13). |
| 4 | Scale to `mini_dungeon` tier with Qwen3-4B. Run BALROG eval as sanity check. PufferLib wrapper (#14). |
| 5+ | Save-state, RNG tracing, possible publication / blog post. |

---

## 6. Open questions for Alex

1. **Default action interface for the published env: skill or code?** *(Resolved: `skill` shipped as the default, `code` as a flag.)* Code is more token-efficient and your group's RLM work makes it a natural fit; skill is closer to existing NetHack-LM literature and easier to compare against.
2. **Engine strategy.** *(Resolved: we abandoned `nle`/`minihack` entirely and now maintain our own NetHack fork — the `third_party/NetHack` submodule — driven through the `RawEngine` ctypes binding, rather than layering C patches on `heiner/nle`. This is what unlocked snapshot/restore, level blobs, state edits, and the knob catalog.)*
3. **Compute envelope for the first training run.** 2 GPUs (Wordle-scale) or 8 GPUs (wiki-search-scale)?
4. **Eval protocol.** Match BALROG's exactly so numbers are comparable, or define our own that incorporates token efficiency (glyphbox proposed this and it's reasonable)?
5. **Project framing for write-up.** "A training-grade NetHack env" is the engineering story; "what changes when LM agents have a real training environment for hard games" could be the research story. Which to lean into?
6. **PufferLib collaboration.** Worth reaching out to Joseph Suarez before W4 for the speed pass? He's been responsive in similar situations.

---

## 7. Risks

- **Fork build complexity.** The engine builds from source (`cmake`, `bison`, `flex`, `libbz2`) into `libnethack.so`; there are no pre-built wheels, and it does not build natively on macOS (AppleClang/Mach-O vs. the fork's GNU-toolchain arena interposition). Mitigation: `Dockerfile.prime` for hosted training and `Dockerfile.console` for macOS; the Hub wheel bundles a prebuilt `.so` via `tools/bundle_for_hub.py`.
- **Reward hacking on scout.** Scout maximizers might pace back and forth at level boundaries to inflate tile counts. Mitigation: log per-floor unique tiles, not cumulative tiles per step.
- **Fork maintenance burden.** Owning a NetHack fork means carrying our own engine entry points and rebasing on upstream NetHack ourselves — no `nle`/`minihack` maintainers to lean on. Mitigation: keep the C surface small (a handful of `nle_*` entry points) and pin the submodule.
- **Determinism debt.** Some subsystems (e.g., monster AI in certain edge cases) may not be fully deterministic. Mitigation: snapshots capture RNG state, so snapshot/restore gives an exact-reproduction diagnostic when a divergence is suspected.
- **Context bloat in code mode.** The full game state is ~50 lines per turn; a 500-turn episode is 25k tokens of observations alone. Mitigation: observation masking + sliding window à la glyphbox, sliding-window length is a tunable.

---

## Appendix A: References

- Küttler et al., *The NetHack Learning Environment*, NeurIPS 2020.
- Samvelyan et al., *MiniHack the Planet*, NeurIPS 2021.
- Hambro et al., *Dungeons and Data*, NeurIPS 2022.
- Jeurissen et al., *Playing NetHack with LLMs (NetPlay)*, CoG 2024.
- Klissarov et al., *Motif*, 2023.
- Paglieri et al., *BALROG*, ICLR 2025.
- Suarez, *PufferLib 2.0*, RLJ 2025.
- *Revisiting the NetHack Learning Environment*, ICLR Blogposts 2026.
- Brown et al., *Verifiers*, github.com/PrimeIntellect-ai/verifiers, 2025–2026.
- Sartak, *Predicting and controlling NetHack's randomness*, 2009.
- pellsson, *SWAGGINZZZ*, 2018.
- kenforthewin, *It's 2026. Can LLMs Play Nethack Yet? (glyphbox)*, Jan 2026.
- Zhang, Kraska, Khattab, *Recursive Language Models*, arXiv 2512.24601, 2026.
