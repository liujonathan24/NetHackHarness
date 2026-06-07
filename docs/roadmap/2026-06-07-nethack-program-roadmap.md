# NetHack harness — program roadmap (2026-06-07)

Status: design pass (no implementation). Splits into **two Comet `full` changes**
(Group A obs/eval, Group B infra), sequenced on top of the paused
`image-observation-renderer` change.

## 1. Problem framing & assumptions

**Thesis:** the dominant lever on this NetHack RL/eval env is the *observation
encoding*. ASCII art is hard for LLMs to parse; rendered pixels are hard for
VLMs (the `IMG`/`IMG_TTY` work). The bet: **structured-text encodings
(JSON / TOON) and a code-interpretable map object read better than either**, and
we should measure that head-to-head.

**Locked decisions (user, 2026-06-07):**
- Customizable game: **hybrid** — MiniHack des-files now, NetHack-source fork
  later only where MiniHack can't express a knob.
- Repo structure: **monorepo uv-workspace packages** (alongside `nethack_core`,
  `environments/nethack`, `tools/launchpad`), not separate git repos.
- Structured-map schema: **entity-list canonical model** (sparse semantic
  entities + compact grid) → emit **both JSON and TOON** variants.
- Group A purpose: **benchmark evaluation across encodings** (ASCII vs IMG vs
  JSON vs TOON; VLM vs LLM). **No RL training in scope yet.**

**Grounding facts that shape this:**
- MiniHack is already integrated (`nethack_core/env.py` makes MiniHack envs,
  accepts `des_file`; `curriculum.py` swaps to MiniHack). Level/content
  customization is largely free.
- The `nh` code namespace already exists (`code_mode.py`: `nh.move`,
  `nh.map_view`, `nh.status`, `nh.autoexplore`…). The pysc2 interface and the
  code-interpretable map object **extend** it, not greenfield.
- The map is rendered today by `render_map_view` (tty→ASCII) in
  `nethack_core/observations.py`; a structured map is a sibling renderer over the
  same glyphs/tty data.
- Variants live in `VARIANT_REGISTRY`; new encodings register like `IMG`/`IMG_TTY`.

## 2. Unifying architecture — one map model, three consumers

```
        ┌──────────────────────────────────────────┐
        │  Canonical structured Map model           │  in nethack_core
        │  glyphs + tty + blstats → typed entities  │  (player, monsters, items,
        │  + compact grid                           │   stairs, doors, features @ coords)
        └───────────────┬──────────────────────────┘
                        │ three thin adapters
     ┌──────────────────┼─────────────────────────────┐
     ▼                  ▼                              ▼
 JSON / TOON       nh.map object                 pysc2-style
 obs renderer      in code namespace             ObservationSpec
 (Change A obs)    (Change A code)               (Change B interface)
```

**Build the map model once** (Change A foundation); the JSON/TOON serializer, the
`nh.map` object, and the pysc2 obs-spec are three adapters over it. This makes
Change B's interface reuse Change A's substrate — the groups are sequenced, not
independent.

## 3. The two Comet changes

### Change A — `structured-map-observation` + encoding eval (obs/eval layer)
Capabilities:
- `canonical-map-model` — glyph/tty → typed entity model + compact grid, in
  `nethack_core` (reuses glyph classification; NLE glyph ranges + GlyphMapper
  categories).
- `structured-map-observation` — `JSON` and `TOON` variants in `VARIANT_REGISTRY`
  (siblings to `IMG`/`IMG_TTY`), serializing the map model into the user message.
- `code-interpretable-map` — expose `nh.map` (queryable object: entities,
  `nh.map.at(x,y)`, `nh.map.monsters`, `nh.map.stairs`…) in the code namespace.
- `encoding-eval-harness` — run the encoding matrix and emit comparable metrics.

### Change B — `pysc2-interface` + `customizable-game` (infra layer)
Capabilities:
- `pysc2-style-interface` — a new workspace package: typed `ObservationSpec` /
  `ActionSpec` over `nethack_core`, with the canonical map model as its obs core;
  a cleaner, typed, growing successor to the ad-hoc `nh` namespace.
- `customizable-game` — a new workspace package wrapping MiniHack des-files
  (levels, layout, content, monsters) + a thin shim for `#floors` / player
  `attributes`; starts as base game. Fork-later gate documented.

## 4. Sequencing, milestones, metrics, gates

**Scope note (user, 2026-06-07): BOTH sets of changes are in scope** — the
original refactor + image capability AND the new Groups A & B. The roadmap does
not replace the image work; it sequences on top of it.

| M | Work | Change | Go/No-Go gate |
|---|------|--------|---------------|
| Base | `nethack_core → nethack_harness/legacy` reorg + file split + build_prompt/PromptSpec factory rewire | (done, uncommitted on branch) | Preserve/commit; known rough edge: `nethack.py:26` `from environments.nethack import harness_overlay` packaging import (hub_install failure) to fix |
| M0 | Finish + archive `image-observation-renderer` (provides IMG/IMG_TTY for the eval matrix) | (in-flight) | All new tests green; failure set ⊆ baseline 8 |
| M1 | Canonical map model + JSON/TOON obs variants | A | JSON & TOON render a real rollout obs; entity coords correct vs ASCII |
| M2 | `nh.map` code-interpretable object | A | Code-mode rollout can query map object; parity with `map_view` |
| M3 | Encoding eval harness + first benchmark | A | **Key gate:** does any structured encoding beat ASCII on progression at comparable $/run? |
| M4 | pysc2-style typed interface package | B | Interface drives a full rollout via typed obs/action; reuses map model |
| M5 | customizable-game package (MiniHack wrapper + #floors/attributes shim) | B | Can spawn a custom level + altered attributes; **fork gate** if MiniHack blocks a needed knob |

**Encoding matrix (M3):** ASCII (`B1`) vs IMG vs IMG_TTY vs JSON vs TOON, across
≥1 instruct LLM and ≥1 VLM. **Metrics:** progression score/tier
(`prompt/balrog.py` already computes these), max dlvl reached, scout coverage,
steps-to-first-descent, tokens/turn, $/run. Run via `prime eval` + existing eval
instrument (`tests/test_eval_instrument.py`, `configs/endpoints.toml`).

## 5. Risks / dependencies / open decisions

- **TOON tooling maturity** — verify whether a maintained Python TOON
  (Token-Oriented Object Notation) encoder exists; if not, we implement a small
  encoder. Decide at M1.
- **Map-model fidelity** — glyph→semantic classification (monster vs item vs
  feature vs stairs) must be correct; reuse NLE glyph ranges + GlyphMapper
  categories rather than hand-rolling.
- **Token cost of JSON** — mitigated by the sparse entity-list model (not dense
  per-tile); TOON exists precisely to cut that further. Track tokens/turn as a
  first-class metric.
- **`#floors` / `attributes` may force the fork early** (M5 gate) — hybrid plan
  accepts this.
- **VLM availability/cost** — confirm endpoint aliases in `configs/endpoints.toml`
  before M3.
- **Overlap with paused image-renderer** — IMG/IMG_TTY are the pixel arm of the
  same eval matrix; finish them (M0) before M3.

## 6. Distribution

Once Change A's variants are smoke-test stable, consider a Prime Hub push so the
encoding-comparison env is reusable. Visibility (PUBLIC/PRIVATE) — open decision
for the user.

## 7. Immediate next action

Per M0: resume and finish the paused `image-observation-renderer` build (Tasks
2–5, then verify + archive), then open **Change A** via `/comet`. Each group is
its own Comet `full` change referencing this roadmap.
