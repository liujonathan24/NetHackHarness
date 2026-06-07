## Context

`nethack_core/observations.py` already produces a `StructuredObservation`
(`map_view` ASCII, typed `inventory`, `status`, `character`, `adjacent`,
`under_player`). It lacks a typed **entity list with coordinates** — the piece a
structured-text encoding and a code-queryable map both need. NLE exposes the
classifiers to build it cheaply (`nle.nethack.glyph_is_monster/pet/object/trap`,
`glyph_to_mon/obj/cmap`, `GLYPH_*_OFF`); the repo already has `_glyph_kind`,
`_FEATURE_GLYPHS`, and `extract_adjacent`. Variants register in
`VARIANT_REGISTRY`; the `nh` code namespace already exposes `nh.map_view`.

## Goals / Non-Goals

**Goals:**
- One canonical, typed map model (entities + compact grid) built once in
  `nethack_core`, reused by JSON obs, TOON obs, `nh.map`, and (later) Group B.
- `JSON` and `TOON` observation variants; existing variants byte-identical.
- `nh.map` queryable object for code-mode agents.
- A benchmark comparing encodings (ASCII/IMG/IMG_TTY/JSON/TOON) on real metrics.

**Non-Goals:**
- No RL training. No Group B work. No change to ASCII/IMG rendered bytes.
- No dense per-tile JSON dump (sparse entity-list + compact grid instead).

## Decisions (high-level; deep design in /comet-design)

- **Map model in `nethack_core`** (layer-1), not `nethack_harness` (layer-2), so
  Group B's interface can reuse it without depending on the prompt layer.
- **Sparse entity-list + compact grid**, not dense per-tile JSON — controls token
  cost (the whole point of preferring TOON over verbose JSON).
- **Glyph classification reuses NLE helpers** — never a hand-maintained table.
- **TOON encoder is in-repo** (no maintained PyPI package) — a small serializer
  over the same model the JSON path uses; both consume one model so they can't
  diverge.
- **`nh.map` wraps the model** read-only, mirroring how `nh.status`/`nh.inventory`
  expose read-only views today.
- **Eval reuses existing instrumentation** (`test_eval_instrument.py` summarizer,
  `configs/eval/`, `balrog.py` progression) rather than a new metrics stack.

## Risks / Trade-offs

- [TOON spec ambiguity — no reference Python lib] → define a small, documented
  in-repo encoding; test round-trip/shape rather than chase an external spec.
- [Entity classification fidelity] → reuse NLE classifiers + existing helpers;
  test against known fixtures (a monster, an item, stairs, a door).
- [Scope: 4 capabilities is large] → sequence map-model → encodings → nh.map →
  eval; if the eval harness balloons past the build plan, split it into its own
  change (Comet 50% threshold rule).
- [Token cost of JSON] → sparse model + measure tokens/turn as a first-class eval
  metric; TOON exists to undercut JSON.

## Open Questions (for /comet-design)

- Exact entity schema (fields per entity; how much description vs raw glyph id).
- TOON encoding shape (delimiter/format) and how compact to go.
- Whether the grid is included in JSON/TOON or entities-only (lean: compact grid +
  entities).
- Eval matrix size for v1 (which LLM + which VLM; how many seeds/episodes).
