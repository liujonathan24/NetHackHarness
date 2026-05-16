# NetHack as a Mature RL Training Environment

**Author:** Jonathan Lin
**Reviewers:** Alex Zhang
**Status:** First draft, for Monday discussion
**Last updated:** May 2026

---

## 1. Goals and non-goals

### Goals

1. Build a mature, well-engineered training environment around NetHack that is genuinely useful for *training* LM agents (not just evaluating them).
2. Land it on the Prime Intellect Environments Hub as `primeintellect/nethack`, train-ready with `prime-rl`.
3. Make the underlying gymnasium env useful to the non-LM RL community as well — PufferLib, Sample Factory, anyone running PPO on NLE — by keeping the harness layer interface-agnostic and PR'ing improvements upstream to `heiner/nle` and `facebookresearch/minihack` where appropriate.
4. Ship a curriculum: a smooth difficulty ramp from a single room with one monster to the full game, controllable from a single config dict.
5. Get to a first RL training run (Qwen3-4B-Instruct, single-dungeon curriculum, scout reward) within ~4 weeks.

### Non-goals

- A new LLM-NetHack benchmark. BALROG and BRAID already serve that role; we contribute a training env, not a leaderboard.
- Beating BALROG progression with a frontier model. That's a downstream experiment; the deliverable here is the substrate.
- A from-scratch reimplementation of NetHack. We extend `heiner/nle`, which already ships the NetHack 3.6.7 C source as a submodule. Surgical C patches only, behind compile-time flags.
- Replacing MiniHack. We use it as the curriculum backend.

---

## 2. Prior art

**The simulator stack:**

- **NLE** (`github.com/heiner/nle`, `nle==1.2.0`, NetHack 3.6.7). Active maintenance line; the `facebookresearch/nle` repo redirects here. Gymnasium API.
- **MiniHack** (`facebookresearch/minihack`). Probabilistic des-file DSL exposed as a `LevelGenerator` Python wrapper. The curriculum lever.
- **PufferLib** (Suarez et al., RLJ 2025). Reports ~10× synchronous speedup on NetHack via shared-memory vectorization.

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

### 3.1 Two layers

```
                  ┌──────────────────────────────────────┐
                  │ Layer 2: verifiers wrapper           │
                  │ environments/nethack/nethack.py      │
                  │ - vf.StatefulToolEnv subclass        │
                  │ - chat-shaped, OpenAI tool calling   │
                  │ - rubric: scout, descent, ascension  │
                  └────────────────┬─────────────────────┘
                                   │ consumes
                                   ▼
                  ┌──────────────────────────────────────┐
                  │ Layer 1: interface-agnostic core     │
                  │ nethack_core/                        │
                  │ - NetHackCoreEnv (gym.Env)           │
                  │ - skill API / code API               │
                  │ - menu, inventory, attributes        │
                  │ - curriculum, wiki, replay           │
                  └────────────────┬─────────────────────┘
                                   │ wraps
                                   ▼
                  ┌──────────────────────────────────────┐
                  │ heiner/nle + MiniHack                │
                  │ + light C patches (rnd.c tracing)    │
                  └──────────────────────────────────────┘
```

The contract between layers is gymnasium-shaped. Anyone training a CNN-LSTM policy with PPO consumes layer 1 directly; the verifiers wrapper exists purely to bolt on chat-shaped tool calling and an LLM-compatible rubric.

### 3.2 Three action-interface modes

Selected via `load_environment(interface=...)`:

- `"raw"` — Discrete NLE action IDs. For tabula-rasa RL baselines and reproducibility with prior work.
- `"skill"` — NetPlay-style skills: `move(dir)`, `attack(dir)`, `pickup`, `descend`, `look`, `inventory`, `search`, `drink(item)`, `throw(item, dir)`, `wear(item)`, `cast(spell)`. Each compiles to a primitive action sequence. Default for LM agents.
- `"code"` — glyphbox-style. Expose a Python API `nh.*` and let the model write loops in a sandboxed REPL. Single `execute_code` tool. Most token-efficient; arguably the most interesting research direction.

All three share the same underlying state. A single training run can swap interfaces via config; ablations across modes are first-class.

### 3.3 Observation extraction (the ICLR 2026 fixes)

Default observations exposed to the agent:

- `map` — full `tty_chars` grid, *with menu region masked out* (menus extracted separately).
- `menu` — when a menu is open: list of `(letter, description, key)` tuples. Detected by anchoring on `"(end)"` in `tty_chars`.
- `inventory` — `inv_strs` decoded into a list of `{letter, description, category, count, blessed}`. Always present, no need to press `i`.
- `inventory_prompt` — when the game asks "What do you want to throw? [abh]", parse the bracket set, cross-reference with inventory, expose as `{action: "throw", choices: [<inv items>]}`. The agent picks by item, not letter.
- `status` — HP, AC, hunger, level, gold, turn count, dungeon level, alignment status.
- `character` — role, race, alignment, gender. Set on reset by auto-invoking `#attributes`, then frozen for the episode.
- `messages` — list of game messages since last action.
- `adjacent` — 8-direction adjacency description (corridor, wall, monster, door, etc.).

The augmented action space exposes `menu_option_k` and `inventory_item_k` so the model picks semantically rather than by letter — same pattern the ICLR blog validated.

### 3.4 Reward design

Composable rubric, default weights configurable per training run:

- `scout` — +1 per newly observed tile this turn. Dense, well-correlated with progress.
- `descend` — +10 on each new max-dungeon-level reached.
- `ascend` — +1000 on successful ascension.
- `survive` — small per-turn bonus (controversial, off by default).
- `death` — 0 or negative; arguably 0 is right since premature death already costs the rest of the episode.

We expose `score` and `balrog_progression` as available reward functions but do not use them as training signal by default, for reasons documented in §2.

### 3.5 Curriculum

Wrap `minihack.LevelGenerator` and expose a `curriculum.py` with named tiers:

| Tier | Name                | Layout                       | Monsters       | Items  | Goal                |
|------|---------------------|------------------------------|----------------|--------|---------------------|
| 0    | `empty_room`        | 5×5 room                     | none           | stairs | descend             |
| 1    | `solo_combat`       | 8×8 room                     | one weak (newt)| sword  | kill + descend      |
| 2    | `multi_combat`      | 10×10 room                   | three weak     | sword  | kill all + descend  |
| 3    | `corridor_explore`  | 3-room maze                  | one weak       | items  | explore + descend   |
| 4    | `mini_dungeon`      | 3 floors                     | mixed          | mixed  | reach dlvl 3        |
| 5    | `full_dungeon_easy` | 5 floors, no Mines branch    | mixed          | mixed  | reach dlvl 5        |
| 6    | `full_nle`          | unmodified `NetHackChallenge`| —              | —      | full game           |

A single training run can either pin a tier or schedule across them (e.g., uniform sampling weighted by historical success rate, à la PLR).

### 3.6 Wiki tool

Two-flavor:

- `wiki_search(query: str, k: int = 3)` — vector search over a NetHackWiki snapshot. ChromaDB index built on first load, persisted at `~/.cache/nethack-rl/wiki.chroma`. Identical pattern to `prime-rl/examples/wiki_search`.
- `wiki_lookup(entity: str)` — direct page fetch for a known entity (e.g., `wiki_lookup("cockatrice")`). When the env detects a new glyph in the agent's view it can optionally surface a "you have not seen a `c` before, you can `wiki_lookup('c')`" hint in observations.

We snapshot the wiki to avoid live HTTP during rollouts. License is CC-BY-SA; we redistribute the snapshot with attribution.

### 3.7 Reproducibility and replay

- `reseed=False` by default in NLE seeding, removing the anti-TAS periodic reseeding that breaks determinism. (Users opting into TAS-style protection can flip it back.)
- `seed()` always called before `reset()`. Both `core` and `disp` RNGs seeded; `(core, disp)` hash logged on every rollout for audit.
- **Trajectory replay** (cheap path, ships first): record `(seeds, action_sequence)` as the canonical "save". Replay = `env.reset(seeds=...); for a in actions: env.step(a)`. Sufficient for episodes up to ~10⁴ steps at NLE's 14k sps.
- **Save-state** (Tier 3 stretch): expose NetHack's existing C-side `dosave()` / `dorecover()` through the NLE binding. Real C work; pays off for very long episodes and for any planned MCTS work.
- Optional C patch in `nle_patches/rnd_trace.patch`: instrument `rn2`/`rn1`/`Rand` to log subsystem tags behind a `NLE_RNG_TRACE` compile flag. Audit trail when reproducibility breaks.

---

## 4. Feature roadmap and priorities

**Tier 1 — Harness layer (the things flagged in Wed discussion).** All have ICLR 2026 or glyphbox validation.

1. Menu observation extraction + augmented `menu_option_k` action.
2. Inventory item resolution + augmented `inventory_item_k` action.
3. Always-on inventory in observation (via `inv_strs`).
4. Auto-`#attributes` on reset, role/race/alignment in observation.
5. `reseed=False` + seed-before-reset enforcement.
6. Trajectory replay.

**Tier 2 — Action API design.**

7. Skill-mode API (NetPlay-derived).
8. Code-mode API (glyphbox-derived) with sandboxed REPL.
9. Autoexplore — Python implementation on top of NLE (glyphbox approach) OR port NetHack4's autoexplore as a C patch (cleaner but harder).
10. Persistent memory tools (`add_note`, `add_reminder`) from glyphbox.

**Tier 3 — Curriculum, wiki, speed.**

11. `curriculum.py` with the seven named tiers.
12. Wiki tool (search + lookup), ChromaDB index of NetHackWiki.
13. Scout / BALROG / score rewards as a composable rubric.
14. PufferLib `PufferEnv` API for layer 1 (optional, behind extras).
15. Optional `rn2` tracing C patch.
16. Save-state via `dosave`/`dorecover` binding (stretch).

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

1. **Default action interface for the published env: skill or code?** Code is more token-efficient and your group's RLM work makes it a natural fit; skill is more like existing NetHack-LM literature and easier to compare against. Suggest skill as default, code as a flag — but happy to flip.
2. **NLE fork strategy.** Maintain a public `princeton-pli/nle` fork with the C patches, or upstream everything to `heiner/nle`? Maintainer (Heinrich Küttler) is generally responsive but slow-moving.
3. **Compute envelope for the first training run.** 2 GPUs (Wordle-scale) or 8 GPUs (wiki-search-scale)?
4. **Eval protocol.** Match BALROG's exactly so numbers are comparable, or define our own that incorporates token efficiency (glyphbox proposed this and it's reasonable)?
5. **Project framing for write-up.** "A training-grade NetHack env" is the engineering story; "what changes when LM agents have a real training environment for hard games" could be the research story. Which to lean into?
6. **PufferLib collaboration.** Worth reaching out to Joseph Suarez before W4 for the speed pass? He's been responsive in similar situations.

---

## 7. Risks

- **NLE build complexity.** `cmake>=3.18`, system libs, no pre-built wheels for some platforms. May need a Docker image for Hosted Training. Mitigation: ship a Prime Sandbox spec early.
- **Reward hacking on scout.** Scout maximizers might pace back and forth at level boundaries to inflate tile counts. Mitigation: log per-floor unique tiles, not cumulative tiles per step.
- **MiniHack drift.** MiniHack hasn't been actively maintained since ~2023. We may need to vendor the bits we need rather than pip-install. Mitigation: fork it under `princeton-pli/`.
- **Determinism debt.** Even with `reseed=False`, some subsystems (e.g., monster AI in certain edge cases) may not be fully deterministic. Mitigation: the RNG tracing patch in Tier 3 is the diagnostic tool for this.
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
