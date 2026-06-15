# Repository Map

A post-processed, whole-repo orientation: every layer, what lives where, and how
a single turn flows from engine bytes to an LLM action and back. Pair this with
[`CAPABILITIES.md`](CAPABILITIES.md) (what the repo can do) and
[`design.md`](design.md) (why it is built this way).

> The clean `main` branch carries the code, the GIF demos, and these curated
> docs. Internal process artifacts — the OpenSpec change history, per-fix
> onboarding walkthroughs, the experiment suite, and scratch logs — live on the
> [`experimental`](https://github.com/liujonathan24/NetHackHarness/tree/experimental)
> branch (and on disk locally), kept out of the public tree.

## The layers

The project is a `uv` workspace deliberately split so that a reinforcement-learning
algorithm can consume the bare environment while a chat-based LLM agent uses the
full harness — both over the *same* deterministic engine.

```
LLM agent (chat / tool-calling)            RL algorithm (PPO, GRPO, …)
        │                                            │
        ▼                                            │
environments/nethack/  ── Layer 3: verifiers wrapper │
  nethack.py            (Hub-deployable env, rubric, │
                         chat loop, tool dispatch)    │
  nethack_harness/     ── Layer 2: harness           │
                        (prompts/encodings, skills,   │
                         curriculum, navigation,      │
                         memory, refiner)             │
        │                                            │
        ▼                                            ▼
nethack_interface/     ── Layer 1a: typed pysc2-style interface
                        (Observation/Action specs, skill-derived schema)
        │
        ▼
nethack_core/          ── Layer 1b: interface-agnostic substrate
  env.py                (NetHackCoreEnv gym wrapper, seed-before-reset)
  observations.py       (StructuredObservation shaping)
  map_model.py          (canonical typed map model — one source for every encoding)
  engine_env.py         (EngineEnv: snapshot/restore/branch, level blobs,
                         modify(), 17 difficulty knobs)
  _engine.py            (RawEngine: the ctypes binding)
        │
        ▼  ctypes
third_party/NetHack/src/build/libnethack.so   ── Layer 0: the custom fork (C)
  nle_start/step/end, nle_*snapshot/restore,
  nle_save/load_level, nle_modify, nle_tune
```

The key inversion versus standard NetHack RL: we do **not** sit on the `nle` /
`minihack` PyPI gym wrapper. `nethack_core` drives a custom fork directly through
a ctypes binding, which is what makes in-memory snapshot/restore, portable level
blobs, secure state edits, and live difficulty knobs possible at all.

## One turn, end to end

1. **Engine step** — `RawEngine.step(byte)` runs the fork and fills ctypes
   buffers (`glyphs`, `chars`, `colors`, `blstats`, inventory, `tty_chars`).
2. **Shaping** — `NetHackCoreEnv` wraps those into a `CoreObservation`;
   `StructuredObservation` extracts menu / inventory / status / message.
3. **Canonical map model** — `build_map_model` turns the glyph grid into typed
   entities (monsters with species + pet flag, items with object class, stairs
   with direction, doors, traps) plus the player position and a compact grid.
   *Every* observation encoding reads from this one model, so they cannot drift.
4. **Encoding** — the selected `variant` renders the model: ASCII (`B0`/`B1`),
   BALROG natural language (`B`), structured text (`JSON`/`TOON`), tiles (`IMG`),
   tty raster (`IMG_TTY`), descent-salience (`ND`/`FD`), frontier (`E1`/`E2`).
5. **LLM input** — verifiers wraps the rendered observation into a chat message
   (multimodal for the image encodings).
6. **Tool dispatch** — `env_response` resolves the tool call through the skill
   registry: `interface="skill"` calls one function-tool per skill;
   `interface="code"` runs sandboxed Python against the `nh` namespace.
7. **Action → engine** — the skill returns keystroke bytes (or runs a closed
   loop like `explore_and_descend`), which step the engine; the rubric scores the
   delta. If `trace_dir` is set, the whole turn is appended to an NDJSON trace for
   the rollout viewer.

## Where things live

| Path | Layer | Responsibility |
|------|-------|----------------|
| `nethack_core/_engine.py` | 0 | ctypes binding to `libnethack.so` (`RawEngine`) |
| `nethack_core/engine_env.py` | 0/1 | `EngineEnv`: deterministic seed/reset/step + snapshot/restore/branch, `save_level`/`load_level`, `modify()`, `tune` catalog |
| `nethack_core/env.py` | 1b | `NetHackCoreEnv` gym wrapper, seed-before-reset |
| `nethack_core/observations.py` | 1b | `StructuredObservation` shaping |
| `nethack_core/map_model.py` | 1b | canonical typed map model |
| `nethack_core/glyphs.py` | 1b | glyph classifiers (monster/object/trap/cmap) |
| `nethack_core/build_engine.sh` | — | builds `libnethack.so` from the fork submodule |
| `nethack_interface/` | 1a | typed pysc2-style `Observation`/`Action` + `NetHackInterface` |
| `environments/nethack/nethack.py` | 3 | `load_environment`, verifiers env, rubric, tool dispatch |
| `environments/nethack/nethack_harness/prompt/` | 2 | variant registry, JSON/TOON encoders, image renderers, BALROG progression |
| `environments/nethack/nethack_harness/tools/` | 2 | skill registry, code-mode `nh` namespace, wiki tool |
| `environments/nethack/nethack_harness/curriculum/` | 2 | 13 named tiers + pluggable milestones + dynamic subgoals |
| `environments/nethack/nethack_harness/navigation/` | 2 | A* pathfinding + frontier autoexplore |
| `environments/nethack/nethack_harness/memory/` | 2 | journal + belief-state summarization |
| `environments/nethack/nethack_harness/refiner.py` | 2 | Continual-Harness self-refinement |
| `approaches/` | — | standalone agent strategies (go-explore, voyager, rlm, continuous-harness) |
| `tools/play_server.py` + `tools/webconsole/` | — | Flask web console: live play, difficulty knobs, snapshot/restore, trace scrubber |
| `tools/knob_gifs.py` | — | renders the difficulty-knob demo GIFs in `videos/` |
| `tools/rollout_view/` | — | in-browser dual-pane rollout viewer + stats dashboard |
| `tools/encoding_eval/` | — | run one task across encoding × model matrices |
| `tools/eval_instrument.py` | — | `summarize_eval` / `classify_failure` / `wilson_ci` |
| `third_party/NetHack/` | 0 | the fork submodule (engine source; build output is gitignored) |
| `tests/` | — | ~396 tests across 53 files |
| `configs/endpoints.toml` | — | vf-eval endpoint registry |
| `Dockerfile.prime` | — | builds the engine for Prime Sandbox / hosted training |
| `Dockerfile.console` | — | runs the web console in Linux (engine + Flask); for macOS where the engine has no native build |
| `docs/` | — | this map, `CAPABILITIES.md`, `design.md`, `engine-layer.md`, eval/training recipes, netplay parity writeups |

## Coordination seams worth knowing

- **Skill registry → action schema.** Skills register once in
  `nethack_harness/tools/skills.py`; both the tool-calling schema and code-mode
  dispatch derive from that registry, so the advertised action set cannot drift
  from the implemented one.
- **Map model → every encoding.** `build_map_model` is the single source; `JSON`
  and `TOON` are two serializations of the same object and cannot disagree.
- **Curriculum → termination.** A tier's success milestone is checked every step
  inside `env_response`, giving goal-conditioned early termination.
- **Snapshot/restore → exploration.** `branch(n)` and the live web-console
  checkpoint button both rest on O(1) in-memory snapshot/restore — no action
  replay.
- **Trace capture → viewer.** A per-turn NDJSON trace (game state + exact LLM
  input) is what the rollout viewer and web console replay.
